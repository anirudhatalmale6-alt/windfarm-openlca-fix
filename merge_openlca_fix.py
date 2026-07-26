#!/usr/bin/env python3
"""
merge_openlca_fix.py
--------------------
Merge an openLCA JSON-LD "fix package" (a small zip that contains only the
processes / flows that changed) into a FULL openLCA JSON-LD export, producing
one complete, self-consistent corrected database that imports cleanly.

WHY THIS EXISTS
    openLCA matches every object by its UUID (@id). When you import a small
    "changed objects only" package on top of an existing database, openLCA
    keeps the existing versions unless overwrite is explicitly forced, so the
    edits appear not to apply. Importing a COMPLETE corrected database into a
    fresh/empty database sidesteps that entirely: every object is created once,
    with the corrected values, and nothing needs to be overwritten.

WHAT IT DOES
    1. Copies the full export verbatim  (parameters, formulas, unit groups,
       flow properties, locations, currencies - ALL untouched).
    2. Overlays every process / flow from the fix package on top, matched by
       UUID (replace if it exists, add if it is new).
    3. Runs a mass-balance check on every process and prints an audit table so
       you can see which processes still don't balance BEFORE importing.
    4. Re-zips the result into a single import-ready JSON-LD archive.

USAGE
    python merge_openlca_fix.py  FULL_EXPORT.zip  FIX_PACKAGE.zip  [OUTPUT.zip]

    - FULL_EXPORT.zip   : the JSON-LD you exported from openLCA (the good, whole DB)
    - FIX_PACKAGE.zip   : the small JSON-LD with only the changed processes/flows
    - OUTPUT.zip        : optional, defaults to <FULL_EXPORT>-MERGED.zip

    You can also pass already-unzipped folders instead of .zip files.

Then in openLCA:  create a NEW empty database  ->  File > Import > Linked Data
(JSON-LD)  ->  pick OUTPUT.zip.  Calculate there. Repeat as often as you like:
re-export, re-run this, re-import.

No third-party libraries required. Python 3.8+.
"""

import sys, os, json, shutil, zipfile, tempfile

# reference Mass flow property (kg family) used for mass-balance grouping
MASS_PROP = "93a60a56-a3c8-11da-a746-0800200b9a66"


def _extract(path, workdir):
    """Return a folder path for `path`, extracting if it is a zip."""
    if os.path.isdir(path):
        return path
    if zipfile.is_zipfile(path):
        dest = os.path.join(workdir, os.path.basename(path) + "_x")
        os.makedirs(dest, exist_ok=True)
        with zipfile.ZipFile(path) as z:
            z.extractall(dest)
        # some exports nest everything one folder deep - find the real root
        entries = [e for e in os.listdir(dest) if not e.startswith("__MACOSX")]
        if len(entries) == 1 and os.path.isdir(os.path.join(dest, entries[0])) \
           and not os.path.exists(os.path.join(dest, "processes")):
            return os.path.join(dest, entries[0])
        return dest
    raise SystemExit(f"Not a folder or zip: {path}")


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _exch_map(d):
    """flow-name -> (isInput, amount, formula) for every exchange."""
    m = {}
    for e in d.get("exchanges", []):
        f = e.get("flow", {}) or {}
        m[f.get("name")] = (bool(e.get("isInput")),
                            round(float(e.get("amount", 0) or 0), 3),
                            e.get("amountFormula", "") or "")
    return m


def _preview_process_change(base_path, new_path):
    """Print a human diff of exchanges between the base (current DB) and the
    incoming fix, so a regenerated suggestion that would UNDO an earlier fix is
    visible BEFORE import."""
    base = _load(base_path)
    new = _load(new_path)
    a, b = _exch_map(base), _exch_map(new)
    added = [k for k in b if k not in a]
    removed = [k for k in a if k not in b]
    changed = [k for k in b if k in a and a[k] != b[k]]
    if not (added or removed or changed):
        return  # identical, nothing to report
    print(f"\n  CHANGE > {new.get('name')}")
    for k in added:
        print(f"      + add    {k}  ({b[k][1]:,})")
    for k in removed:
        print(f"      - REMOVE {k}  (was {a[k][1]:,})  <-- check this isn't undoing a fix")
    for k in changed:
        print(f"      ~ change {k}  {a[k][1]:,} -> {b[k][1]:,}")


def overlay(full_dir, fix_dir, out_dir):
    """Copy full export to out_dir, then overlay fix objects. Return counts.
    Prints a per-process change preview vs the current database."""
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    shutil.copytree(full_dir, out_dir)

    print("\n" + "=" * 78)
    print("CHANGE PREVIEW  (what the fix does to your CURRENT database)")
    print("=" * 78)

    counts = {}
    for sub in ("processes", "flows", "parameters", "flow_properties",
                "unit_groups", "locations", "currencies", "actors",
                "sources", "categories", "dq_systems"):
        src = os.path.join(fix_dir, sub)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(out_dir, sub)
        os.makedirs(dst, exist_ok=True)
        replaced = added = 0
        for name in os.listdir(src):
            if not name.endswith(".json"):
                continue
            target = os.path.join(dst, name)
            if os.path.exists(target):
                replaced += 1
                if sub == "processes":
                    _preview_process_change(target, os.path.join(src, name))
            else:
                added += 1
            shutil.copy2(os.path.join(src, name), target)
        counts[sub] = (replaced, added)
    return counts


def mass_balance(out_dir):
    """Print a per-process input/output balance table. Mass-property flows only."""
    pdir = os.path.join(out_dir, "processes")
    rows = []
    for name in sorted(os.listdir(pdir)):
        if not name.endswith(".json"):
            continue
        d = _load(os.path.join(pdir, name))
        inp = out = 0.0
        counted = False
        for e in d.get("exchanges", []):
            fp = (e.get("flowProperty") or {}).get("@id")
            # fall back to counting everything if flowProperty not annotated
            if fp is not None and fp != MASS_PROP:
                continue
            amt = float(e.get("amount", 0) or 0)
            counted = True
            if e.get("isInput"):
                inp += amt
            else:
                out += amt
        if not counted:
            continue
        delta = inp - out
        rows.append((d.get("name", name), inp, out, delta))

    # sort worst first
    rows.sort(key=lambda r: -abs(r[3]))
    print("\n" + "=" * 78)
    print("MASS BALANCE  (inputs - outputs, mass-property flows only)")
    print("=" * 78)
    print(f"{'process':<52}{'IN':>10}{'OUT':>10}{'  status'}")
    print("-" * 78)
    unbalanced = 0
    for nm, i, o, dlt in rows:
        tol = max(1.0, 0.001 * max(i, o))   # 0.1% or 1 kg tolerance
        ok = abs(dlt) <= tol
        if not ok:
            unbalanced += 1
        flag = "OK" if ok else f"X  d={dlt:+,.0f}"
        short = (nm[:49] + "...") if len(nm) > 52 else nm
        print(f"{short:<52}{i:>10,.0f}{o:>10,.0f}  {flag}")
    print("-" * 78)
    print(f"{len(rows)} processes checked, {unbalanced} not balanced "
          f"(> 0.1% / 1 kg tolerance)")
    return unbalanced


def rezip(out_dir, out_zip):
    if os.path.exists(out_zip):
        os.remove(out_zip)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(out_dir):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, out_dir)
                z.write(full, rel)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    full_in, fix_in = sys.argv[1], sys.argv[2]
    base = os.path.splitext(os.path.basename(full_in))[0]
    out_zip = sys.argv[3] if len(sys.argv) > 3 else base + "-MERGED.zip"

    work = tempfile.mkdtemp(prefix="olca_merge_")
    try:
        full_dir = _extract(full_in, work)
        fix_dir = _extract(fix_in, work)
        out_dir = os.path.join(work, "merged")

        counts = overlay(full_dir, fix_dir, out_dir)
        print("OVERLAY SUMMARY (from fix package):")
        for sub, (rep, add) in counts.items():
            print(f"  {sub:<16} {rep} replaced, {add} added")

        mass_balance(out_dir)
        rezip(out_dir, out_zip)
        print("\nWROTE:", os.path.abspath(out_zip))
        print("Import this into a NEW/empty openLCA database "
              "(File > Import > Linked Data / JSON-LD).")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
