#!/usr/bin/env python3
"""
reconcile_mass.py
-----------------
Produce a paper-ready MASS-CONSERVATION table from an openLCA JSON-LD export.

For every process it reports mass IN, mass OUT (mass-property flows only), the
delta, and a status - so you can show, and a reviewer can reproduce, that the
model conserves mass everywhere it should. Writes both a CSV (for the paper's
supplementary data) and a readable summary.

    python reconcile_mass.py  EXPORT.zip  [out.csv]

Recovery / separation / aggregator processes are expected to conserve mass and
are marked BALANCE / GAP. Disassembly / transport / manufacturing carry the
turbine as an item + fuel, so a naive kg in=out does not apply - they are marked
n/a so they don't look like errors in the table.

No third-party libraries. Python 3.8+.
"""
import sys, os, json, zipfile, tempfile, shutil, csv, re

MASS_PROP = "93a60a56-a3c8-11da-a746-0800200b9a66"
MUST_BALANCE = re.compile(r"recovery *& *waste|recovery aggregat", re.I)
TOL_ABS, TOL_REL = 1.0, 0.001


def load_procs(path):
    work = tempfile.mkdtemp(prefix="olca_rec_")
    try:
        if os.path.isdir(path):
            root = path
        else:
            with zipfile.ZipFile(path) as z:
                z.extractall(work)
            root = work
            if not os.path.isdir(os.path.join(root, "processes")):
                subs = [d for d in os.listdir(work) if os.path.isdir(os.path.join(work, d))]
                for s in subs:
                    if os.path.isdir(os.path.join(work, s, "processes")):
                        root = os.path.join(work, s); break
        procs = []
        for n in os.listdir(os.path.join(root, "processes")):
            if n.endswith(".json"):
                with open(os.path.join(root, "processes", n), encoding="utf-8") as f:
                    procs.append(json.load(f))
        return procs
    finally:
        # copy out before cleanup not needed; we already loaded into memory
        shutil.rmtree(work, ignore_errors=True)


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    out_csv = sys.argv[2] if len(sys.argv) > 2 else "mass_balance_table.csv"
    procs = load_procs(sys.argv[1])

    rows = []
    for d in procs:
        name = d.get("name", "")
        mi = mo = 0.0
        counted = False
        for e in d.get("exchanges", []):
            if (e.get("flowProperty") or {}).get("@id") != MASS_PROP:
                continue
            counted = True
            v = float(e.get("amount", 0) or 0)
            if e.get("isInput"): mi += v
            else: mo += v
        if not counted:
            continue
        delta = mi - mo
        must = bool(MUST_BALANCE.search(name))
        if not must:
            status = "n/a (not mass-conserving by design)"
        else:
            tol = max(TOL_ABS, TOL_REL * max(mi, mo))
            status = "BALANCE" if abs(delta) <= tol else f"GAP {delta:+.0f} kg"
        rows.append({"process": name, "mass_in_kg": round(mi, 1),
                     "mass_out_kg": round(mo, 1), "delta_kg": round(delta, 1),
                     "must_conserve": "yes" if must else "no", "status": status})

    rows.sort(key=lambda r: (r["must_conserve"] != "yes", -abs(r["delta_kg"])))
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["process", "mass_in_kg", "mass_out_kg",
                                          "delta_kg", "must_conserve", "status"])
        w.writeheader(); w.writerows(rows)

    conserving = [r for r in rows if r["must_conserve"] == "yes"]
    gaps = [r for r in conserving if r["status"].startswith("GAP")]
    print("=" * 74)
    print("MASS-CONSERVATION SUMMARY")
    print("=" * 74)
    print(f"Mass-conserving processes (recovery / aggregator): {len(conserving)}")
    print(f"  Balanced : {len(conserving) - len(gaps)}")
    print(f"  With gap : {len(gaps)}")
    if gaps:
        print("\nOPEN GAPS (need source material data before the paper's numbers close):")
        for r in gaps:
            print(f"  {r['status']:>16}   {r['process']}")
    else:
        print("\nAll mass-conserving processes balance - model closes for publication.")
    print(f"\nFull table written to: {os.path.abspath(out_csv)}")
    print("(one row per process: mass_in, mass_out, delta, status - drop into the paper's SI.)")


if __name__ == "__main__":
    main()
