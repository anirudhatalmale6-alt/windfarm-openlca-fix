#!/usr/bin/env python3
"""
validate_openlca.py
-------------------
Structural / completeness validator for an openLCA JSON-LD export.

It does NOT judge whether your ecoinvent choices or emission factors are
scientifically right (that's your LCA expertise) - it systematically checks the
things a script CAN check across a whole model, so nothing slips through:

  A. Referential integrity  - exchanges / providers pointing at things that
                              don't exist in the package (phantom references).
  B. Process structure      - missing or duplicate reference (quantitative) flow,
                              exchanges with no unit or no amount.
  C. Mass balance           - inputs vs outputs per process (mass flows only),
                              with recovery / separation / aggregator processes
                              flagged as "must conserve mass".
  D. Parameters & formulas  - dependent parameters with no formula, formulas that
                              reference an undefined symbol, duplicate names.
  E. Flow hygiene           - flows defined but never used (orphans).

USAGE
    python validate_openlca.py  EXPORT.zip
    python validate_openlca.py  EXPORT_folder

Exit code is 0 if no ERRORS (warnings allowed), 1 if any ERROR found.
No third-party libraries. Python 3.8+.
"""

import sys, os, json, re, zipfile, tempfile, shutil
from collections import defaultdict, Counter

MASS_PROP = "93a60a56-a3c8-11da-a746-0800200b9a66"  # openLCA reference "Mass"
BAL_TOL_REL = 0.001    # 0.1%
BAL_TOL_ABS = 1.0      # or 1 kg
# process names that are expected to conserve mass: the material-recovery
# routing sub-processes and the component aggregators. Deliberately EXCLUDES
# disassembly / transport / cutting (they carry the turbine as an item + fuel,
# so a naive kg in=out sum does not apply to them).
MUST_BALANCE = re.compile(r"recovery *& *waste|recovery aggregat", re.I)
# math functions/constants allowed in formulas (openLCA formula interpreter)
KNOWN_FUNCS = {
    "abs","acos","asin","atan","atan2","ceil","cos","cosh","exp","floor","ln",
    "log","log10","max","min","mod","pow","round","sin","sinh","sqrt","tan",
    "tanh","if","and","or","not","pi","e","sum","avg","true","false",
}
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def extract(path, work):
    if os.path.isdir(path):
        return path
    if zipfile.is_zipfile(path):
        dest = os.path.join(work, "x")
        with zipfile.ZipFile(path) as z:
            z.extractall(dest)
        entries = [e for e in os.listdir(dest) if not e.startswith("__MACOSX")]
        if len(entries) == 1 and not os.path.exists(os.path.join(dest, "processes")):
            return os.path.join(dest, entries[0])
        return dest
    raise SystemExit(f"Not a folder or zip: {path}")


def load_dir(root, sub):
    out = {}
    d = os.path.join(root, sub)
    if not os.path.isdir(d):
        return out
    for n in os.listdir(d):
        if n.endswith(".json"):
            with open(os.path.join(d, n), encoding="utf-8") as f:
                obj = json.load(f)
            out[obj.get("@id", n[:-5])] = obj
    return out


def formula_symbols(expr):
    toks = []
    for m in IDENT.finditer(expr or ""):
        name = m.group(0)
        after = (expr[m.end():m.end()+1] or "")
        if after == "(":            # function call -> skip
            continue
        toks.append(name)
    return toks


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    work = tempfile.mkdtemp(prefix="olca_val_")
    try:
        root = extract(sys.argv[1], work)
        flows = load_dir(root, "flows")
        procs = load_dir(root, "processes")
        gparams = load_dir(root, "parameters")

        errors, warns, info = [], [], []
        def E(m): errors.append(m)
        def W(m): warns.append(m)

        # ---- symbol table for formulas (openLCA resolves names CASE-INSENSITIVELY) ----
        global_names = {p.get("name") for p in gparams.values()}
        global_lower = {(p.get("name") or "").lower() for p in gparams.values()}
        KNOWN_LOWER = {k.lower() for k in KNOWN_FUNCS}

        def check_symbol(sym, local_names, local_lower, where):
            """Return None if fine; emit error/warning otherwise."""
            if sym in global_names or sym in local_names or sym in KNOWN_FUNCS:
                return
            low = sym.lower()
            if low in global_lower or low in local_lower or low in KNOWN_LOWER:
                # resolves in openLCA (case-insensitive) but the casing differs
                W(f"[casing] {where}: formula uses {sym!r} but the parameter is "
                  f"defined with different capitalisation (resolves, but inconsistent)")
                return
            E(f"[formula] {where}: references UNDEFINED symbol {sym!r}")

        dup = [n for n, c in Counter((p.get("name") or "").lower()
               for p in gparams.values()).items() if c > 1]
        for n in dup:
            E(f"[params] duplicate GLOBAL parameter name (case-insensitive): {n!r}")

        # ---- global dependent params must have a formula; check refs ----
        for p in gparams.values():
            nm = p.get("name")
            if p.get("isInputParameter") is False and not (p.get("formula") or "").strip():
                W(f"[params] dependent global param {nm!r} has no formula (value={p.get('value')})")
            for sym in formula_symbols(p.get("formula")):
                check_symbol(sym, set(), set(), f"global param {nm!r}")

        # ---- track flow usage for orphan detection ----
        used_flows = set()
        proc_ids = set(procs.keys())
        missing_providers = 0
        background_flow_refs = 0

        for pid, d in procs.items():
            pname = d.get("name", pid)
            local_names = {lp.get("name") for lp in d.get("parameters", [])}
            local_lower = {(lp.get("name") or "").lower() for lp in d.get("parameters", [])}
            # local dependent params
            for lp in d.get("parameters", []):
                if lp.get("isInputParameter") is False and not (lp.get("formula") or "").strip():
                    W(f"[params] {pname}: dependent local param {lp.get('name')!r} has no formula")
                for sym in formula_symbols(lp.get("formula")):
                    check_symbol(sym, local_names, local_lower,
                                 f"{pname} / local param {lp.get('name')!r}")

            refcount = 0
            massin = massout = 0.0
            for e in d.get("exchanges", []):
                fl = e.get("flow") or {}
                fid = fl.get("@id")
                used_flows.add(fid)
                # A. referential integrity (background flows/providers live outside
                #    a foreground export - counted, not flagged per-line)
                if fid not in flows:
                    background_flow_refs += 1
                prov = (e.get("defaultProvider") or {}).get("@id")
                if prov and prov not in proc_ids:
                    missing_providers += 1
                # B. structure
                if e.get("isQuantitativeReference"):
                    refcount += 1
                if e.get("unit") is None:
                    E(f"[unit] {pname}: exchange {fl.get('name')!r} has NO unit set")
                amt = e.get("amount")
                if amt is None and not (e.get("amountFormula") or "").strip():
                    E(f"[amount] {pname}: exchange {fl.get('name')!r} has no amount and no formula")
                # formula refs on exchange
                for sym in formula_symbols(e.get("amountFormula")):
                    check_symbol(sym, local_names, local_lower,
                                 f"{pname} / exchange {fl.get('name')!r}")
                # C. mass balance (mass-property flows only)
                if (e.get("flowProperty") or {}).get("@id") == MASS_PROP:
                    v = float(amt or 0)
                    if e.get("isInput"): massin += v
                    else: massout += v

            if refcount == 0:
                E(f"[structure] {pname}: NO quantitative reference (reference flow) set")
            elif refcount > 1:
                E(f"[structure] {pname}: {refcount} quantitative references (should be exactly 1)")

            # balance verdict for mass-conserving processes
            if (massin or massout) and MUST_BALANCE.search(pname):
                tol = max(BAL_TOL_ABS, BAL_TOL_REL * max(massin, massout))
                if abs(massin - massout) > tol:
                    W(f"[balance] {pname}: IN {massin:,.0f} vs OUT {massout:,.0f} "
                      f"(delta {massin-massout:+,.0f} kg)")

        # E. orphan flows
        orphans = [f for fid, f in flows.items() if fid not in used_flows]
        for f in orphans:
            W(f"[orphan] flow never used by any process: {f.get('name')!r}")

        # background links are expected in a foreground export -> informational
        if missing_providers:
            info.append(f"{missing_providers} exchange default-providers point to background "
                        f"datasets not in this export (normal for a foreground model).")
        if background_flow_refs:
            info.append(f"{background_flow_refs} exchange flows are not in this export "
                        f"(normal if they are ecoinvent/background flows).")

        # dedupe warnings while preserving order
        seen = set(); uwarns = []
        for m in warns:
            if m not in seen:
                seen.add(m); uwarns.append(m)

        # ---------- report ----------
        print("=" * 78)
        print(f"openLCA MODEL VALIDATION   ({len(procs)} processes, "
              f"{len(flows)} flows, {len(gparams)} global params)")
        print("=" * 78)
        print(f"\nERRORS ({len(errors)})  - would break calculation / import:")
        for m in errors: print("  x", m)
        if not errors: print("  (none)")
        print(f"\nWARNINGS ({len(uwarns)})  - review, not necessarily wrong:")
        for m in uwarns: print("  !", m)
        if not uwarns: print("  (none)")
        print(f"\nINFO:")
        for m in info: print("  -", m)
        print("\n" + "-" * 78)
        print(f"RESULT: {len(errors)} error(s), {len(uwarns)} warning(s)")
        sys.exit(1 if errors else 0)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
