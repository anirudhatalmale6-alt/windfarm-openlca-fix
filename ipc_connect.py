#!/usr/bin/env python3
"""
ipc_connect.py  -  talk to a LIVE openLCA database over the IPC Server.

STAGE 1 (this file): READ-ONLY. It connects to your running openLCA, reads every
process straight from the open database, and runs the same validation + mass
reconciliation you already have on the zip exports - but with NO export/import
step and WITHOUT changing anything. It is safe to run any time.

SETUP (once):
  1. In openLCA: Tools > Developer tools > IPC Server -> Start. Note the port
     (default 8080).
  2. Install the client library (one time), in a terminal or via run_ipc.bat:
        pip install olca-ipc olca-schema
  3. Keep openLCA open with your database active.

RUN:
    python ipc_connect.py [port]         # default port 8080
  e.g.
    python ipc_connect.py 8080

It prints a validation + mass-balance summary and writes:
    live_validation.txt
    live_mass_balance.csv

Later stages (only when you're ready, added on request):
  - push  : apply corrections directly to the open database (no import)
  - calc  : build a product system, run it, dump CO2/energy to CSV for the paper

This stage does none of that - it only reads.
"""
import sys, csv, re, math

MASS_PROP = "93a60a56-a3c8-11da-a746-0800200b9a66"
MUST_BALANCE = re.compile(r"recovery *& *waste|recovery aggregat", re.I)
TOL_ABS, TOL_REL = 1.0, 0.001


def check_processes(processes):
    """Pure logic: takes a list of olca_schema.Process, returns (errors, warnings, mass_rows).
    Works identically on live IPC data or objects loaded from a JSON-LD export."""
    errors, warnings, mass_rows = [], [], []
    ref_producers = {}

    for p in processes:
        name = p.name or p.id
        refcount = 0
        mi = mo = 0.0
        counted = False
        seen_line = {}
        for e in (p.exchanges or []):
            flow = e.flow
            fname = flow.name if flow else "?"
            if e.is_quantitative_reference:
                refcount += 1
                if flow:
                    ref_producers.setdefault(flow.id, []).append(name)
            if e.unit is None:
                errors.append(f"[unit] {name}: exchange {fname!r} has no unit")
            if e.amount is None and not (e.amount_formula or "").strip():
                errors.append(f"[amount] {name}: exchange {fname!r} has no amount/formula")
            # identical-line duplicate (double-count within process)
            key = (bool(e.is_input), flow.id if flow else None,
                   (e.default_provider.id if e.default_provider else None),
                   e.amount_formula or round(float(e.amount or 0), 6))
            seen_line[key] = seen_line.get(key, 0) + 1
            # mass tally
            fp = e.flow_property
            if fp is not None and fp.id == MASS_PROP:
                counted = True
                v = float(e.amount or 0)
                if e.is_input: mi += v
                else: mo += v
        for key, c in seen_line.items():
            if c > 1:
                warnings.append(f"[dup-exchange] {name}: an identical exchange line repeats {c}x "
                                f"(possible double-count)")
        if refcount == 0:
            errors.append(f"[structure] {name}: no quantitative reference flow")
        elif refcount > 1:
            errors.append(f"[structure] {name}: {refcount} quantitative references (need 1)")

        if counted:
            delta = mi - mo
            must = bool(MUST_BALANCE.search(name))
            if not must:
                status = "n/a"
            else:
                tol = max(TOL_ABS, TOL_REL * max(mi, mo))
                status = "BALANCE" if abs(delta) <= tol else f"GAP {delta:+.0f} kg"
                if not status.startswith("BALANCE"):
                    warnings.append(f"[balance] {name}: IN {mi:,.0f} vs OUT {mo:,.0f} ({delta:+,.0f} kg)")
            mass_rows.append({"process": name, "mass_in_kg": round(mi, 1),
                              "mass_out_kg": round(mo, 1), "delta_kg": round(delta, 1),
                              "must_conserve": "yes" if must else "no", "status": status})

    for fid, names in ref_producers.items():
        if len(names) > 1:
            errors.append(f"[double-count] a flow is the reference of {len(names)} processes "
                          f"{names} - ambiguous provider, can double-count")

    mass_rows.sort(key=lambda r: (r["must_conserve"] != "yes", -abs(r["delta_kg"])))
    return errors, warnings, mass_rows


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    try:
        import olca_ipc as ipc
        import olca_schema as o
    except ImportError:
        print("Missing library. Run:  pip install olca-ipc olca-schema")
        sys.exit(2)

    name_filter = sys.argv[2] if len(sys.argv) > 2 else None
    url = f"http://localhost:{port}"

    # ---- PREFLIGHT: does the server actually RESPOND (fast, with a timeout)? ----
    # If it accepts the connection but never answers, the usual cause is that the
    # IPC Server was started as gRPC (checkbox ticked) instead of JSON-RPC, or no
    # database is open. We test with a tiny request so we fail clearly, not hang.
    import requests
    print(f"Checking the openLCA IPC Server on {url} ...")
    try:
        ping = requests.post(url, json={"jsonrpc": "2.0", "id": 0,
                             "method": "data/get/descriptors",
                             "params": {"@type": "UnitGroup"}}, timeout=15)
        ping.json()  # must be valid JSON-RPC
    except requests.exceptions.Timeout:
        print("\nThe server accepted the connection but did NOT respond within 15s.")
        print("Most likely cause: the IPC Server was started in gRPC mode.")
        print("Fix: in openLCA's 'Start an IPC Server' dialog, make sure")
        print("  'Start as gRPC service (experimental)' is UNCHECKED, then click the")
        print("  green run button again. Also confirm a database is OPEN (bold).")
        sys.exit(1)
    except Exception as ex:
        print(f"\nCould not reach the IPC server: {ex}")
        print("Is openLCA open, and is the IPC Server started (green run button) on this port?")
        sys.exit(1)
    print("Server is responding (JSON-RPC OK).")

    client = ipc.Client(port)
    # give every request a default timeout so nothing hangs forever
    _orig_post = client._s.post
    client._s.post = lambda *a, **k: _orig_post(*a, **{**k, "timeout": k.get("timeout", 300)})

    # Fetch lightweight descriptors first. A live database usually also contains
    # the ecoinvent BACKGROUND (tens of thousands of processes) - pulling all of
    # those in full would hang. We keep only FOREGROUND processes (not from a
    # mounted library), optionally narrowed by a name/category filter.
    print("Fetching the process list ...")
    try:
        descriptors = client.get_descriptors(o.Process)
    except Exception as ex:
        print(f"Could not list processes: {ex}")
        sys.exit(1)

    def is_foreground(d):
        if getattr(d, "library", None):        # background/ecoinvent library -> skip
            return False
        if name_filter and name_filter.lower() not in \
                ((d.name or "") + " " + (d.category or "")).lower():
            return False
        return True

    fg = [d for d in descriptors if is_foreground(d)]
    print(f"{len(descriptors)} processes in the database; {len(fg)} foreground "
          f"(non-library) to check" + (f" matching '{name_filter}'." if name_filter else "."))
    if not fg:
        print("No foreground processes found. If your model sits under a category, re-run with a "
              "filter word, e.g.:  run_ipc.bat  (then this script picks it up)  or  "
              "python ipc_connect.py 8080 EOL")
        sys.exit(1)
    if len(fg) > 400:
        print(f"That's a lot ({len(fg)}). If it's slow, re-run with a filter word to narrow it, "
              f"e.g.  python ipc_connect.py {port} <part-of-your-model-name>")

    processes = []
    for i, d in enumerate(fg, 1):
        try:
            p = client.get(o.Process, d.id)
            if p:
                processes.append(p)
        except Exception as ex:
            print(f"  (skipped {d.name!r}: {ex})")
        if i % 10 == 0 or i == len(fg):
            print(f"  read {i}/{len(fg)} ...")

    print(f"\nRead {len(processes)} foreground processes from the live database "
          f"(nothing was modified).\n")
    errors, warnings, mass_rows = check_processes(processes)

    with open("live_mass_balance.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["process", "mass_in_kg", "mass_out_kg",
                                          "delta_kg", "must_conserve", "status"])
        w.writeheader(); w.writerows(mass_rows)

    conserving = [r for r in mass_rows if r["must_conserve"] == "yes"]
    gaps = [r for r in conserving if r["status"].startswith("GAP")]
    lines = []
    lines.append("=" * 72)
    lines.append(f"LIVE openLCA VALIDATION  ({len(processes)} processes)")
    lines.append("=" * 72)
    lines.append(f"\nERRORS ({len(errors)}):")
    lines += [f"  x {m}" for m in errors] or ["  (none)"]
    lines.append(f"\nWARNINGS ({len(warnings)}):")
    lines += [f"  ! {m}" for m in warnings] or ["  (none)"]
    lines.append(f"\nMASS CONSERVATION: {len(conserving)-len(gaps)}/{len(conserving)} "
                 f"mass-conserving processes balance; {len(gaps)} with gaps.")
    for r in gaps:
        lines.append(f"    {r['status']:>16}  {r['process']}")
    report = "\n".join(lines)
    print(report)
    with open("live_validation.txt", "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print("\nWrote live_validation.txt and live_mass_balance.csv. Read-only run complete.")


if __name__ == "__main__":
    main()
