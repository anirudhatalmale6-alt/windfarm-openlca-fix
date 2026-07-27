#!/usr/bin/env python3
"""
apply_iea_masses.py
Rebuild the WINDFARM monopile model so every component mass matches the exact
IEA-15-240-RWT figures, composition preserved (proportional scaling), and every
EOL recovery process balances to the kilogram.

Input : a JSON-LD export directory (restr_27_7)
Output: a corrected copy + a change log.
"""
import os, json, shutil, glob, math

SRC = "restr_27_7"
DST = "restr_27_7_CORRECTED"
MASS = "93a60a56-a3c8-11da-a746-0800200b9a66"
TOL = 0.5

# component flow name -> (old_full_value, new_value). KEEP = absent.
# Manufactured / whole-life component flows
TARGET = {
 # generator whole (manufacturing/transport/install/disassembly)
 "PMSG Generator, direct-drive, manufactured": (371000, 368839),
 # generator EOL split
 "Nacelle-generator stator, recovered":        (371000, 238490),
 "Rotor+hub-generator (rotor side), recovered":(371000, 130349),
 # hub
 "Hub/Spinner manufactured":                   (190000, 69006),
 "Rotor+hub-hub, recovered":                   (190000, 69006),
 # blades (3x)
 "Blade SINGLE manufactured":                  (195000, 203763),
 "Rotor+hub-blades, recovered":                (195000, 203763),
 # tower
 "Tower manufactured-MP":                      (1263000, 853460),
 "Tower sections (4×) recovered":         (1263000, 853460),
 # monopile (two source values -> one IEA)
 "Monopile foundation manufactured":           (None, 1309950),   # 1318000 & 1300000
 "Monopile, recovered":                        (1300000, 1309950),
 # nacelle cover
 "Nacelle cover manufactured":                 (20000, 20556),
 "Nacelle-cover, recovered":                   (20000, 20556),     # only the 20000 one
 # cooling / hvac
 "Cooling & auxiliaries manufactured":         (25000, 9382),
 "Nacelle-cooling, recovered":                 (25000, 9382),
 # yaw
 "Yaw system Manufactured":                    (60000, 28187),
 "Nacelle-yaw system, recovered":              (60000, 28187),
 # main shaft / bedplate / structural
 "Main shaft, bedplate & structural nacelle manufactured": (225000, 203417),
 "Nacelle-mainshaft/bedplate, recovered":      (225000, 203417),
 # power converter
 "Power converter manufactured":               (22000, 11984),
 "POWER CONVERTER recovered":                  (22000, 11984),
 # transformer
 "Transformer manufactured":                   (45000, 30635),
 "TRANSFORMER (in-nacelle) recovered":         (45000, 30635),
 # KEEP (client value / not clean IEA): transition piece 370000, pitch/braking 35000,
 # dynamic cable 60000, switchgear 12000, control/scada 6000 -> deliberately absent.
}

# Special multi-valued flow: monopile foundation manufactured has 1318000 and 1300000
MONO_MFG_OLD = {1318000, 1300000}

def load(path):
    with open(path, encoding="utf-8") as f: return json.load(f)
def save(path, d):
    with open(path, "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False, indent=2)

def is_mass(e):
    return (e.get("flowProperty") or {}).get("@id") == MASS
def eq(a, b): return a is not None and abs(float(a)-float(b)) <= TOL

log = []

def main():
    if os.path.exists(DST): shutil.rmtree(DST)
    shutil.copytree(SRC, DST)
    procdir = os.path.join(DST, "processes")
    files = glob.glob(procdir+"/*.json")

    # ---- PASS 1: set every full-value occurrence of a targeted flow to its new value
    for fn in files:
        d = load(fn); pname = d.get("name",""); changed=False
        for e in d.get("exchanges", []):
            fname = (e.get("flow") or {}).get("name","")
            if fname not in TARGET: continue
            old, new = TARGET[fname]
            amt = e.get("amount")
            hit = False
            if fname == "Monopile foundation manufactured":
                hit = amt is not None and round(float(amt)) in MONO_MFG_OLD
            elif old is None:
                hit = False
            else:
                hit = eq(amt, old)
            if hit and not eq(amt, new):
                log.append(f"P1 {pname[:40]}: {fname} {amt:g} -> {new:g}")
                e["amount"] = float(new); changed=True
        if changed: save(fn, d)

    # ---- helper: classify
    def refout(d):
        for e in d.get("exchanges",[]):
            if e.get("isQuantitativeReference") and not e.get("isInput"): return e
        return None
    def refin(d):
        for e in d.get("exchanges",[]):
            if e.get("isQuantitativeReference") and e.get("isInput"): return e
        return None

    # ---- PASS 2: leaf MANUFACTURING processes (ref OUTPUT is a targeted manufactured flow)
    MFG_LEAF_PREFIX = ("Sub-Process M1.", "M1.3-", "M1.4-", "M1.6-", "M1.7-")
    for fn in files:
        d = load(fn); pname = d.get("name","")
        ro = refout(d)
        if not ro: continue
        rname = (ro.get("flow") or {}).get("name","")
        if rname not in TARGET: continue
        # skip aggregators (M1.5 nacelle, M1.10 BOP, M1.11 integration have component INPUTS)
        if any(k in pname for k in ("Nacelle complete","Electrical BOP","Integration")): continue
        old, new = TARGET[rname]
        # determine old ref value actually present (post-P1 it's already new) -> use mapping old
        if rname == "Monopile foundation manufactured":
            old_ref = 1318000
        if old is None: old_ref = 1318000
        else: old_ref = old
        f = new/old_ref
        # scale all NON-ref exchanges by f (preserve composition); ref already set in P1
        for e in d.get("exchanges",[]):
            if e is ro: continue
            if e.get("amount") is not None:
                e["amount"] = float(e["amount"]) * f
        log.append(f"P2 MFG {pname[:40]}: scaled inputs x{f:.4f} (ref {rname}->{new:g})")
        save(fn, d)

    # ---- PASS 3: leaf EOL recovery processes (ref INPUT is a targeted recovered flow)
    for fn in files:
        d = load(fn); pname = d.get("name","")
        ri = refin(d)
        if not ri: continue
        rname = (ri.get("flow") or {}).get("name","")
        if rname not in TARGET: continue
        if "agregator" in pname or "aggregator" in pname: continue
        new = float(ri.get("amount"))   # already set to new in P1
        # sum current mass outputs
        outs = [e for e in d.get("exchanges",[]) if is_mass(e) and not e.get("isInput")]
        cur = sum(float(e.get("amount") or 0) for e in outs)
        if cur <= 0:
            log.append(f"P3 EOL {pname[:40]}: no mass outputs, skipped"); continue
        s = new/cur
        for e in outs:
            e["amount"] = float(e.get("amount") or 0) * s
        # scale non-mass activity inputs (energy etc.) proportionally to input change
        log.append(f"P3 EOL {pname[:40]}: outputs rescaled x{s:.4f} to balance at {new:g}")
        save(fn, d)

    # ---- PASS 3b: balance EVERY remaining EOL recovery leaf (incl KEEP buckets:
    #      pitch, dynamic cable, switchgear, control/scada) by rescaling mass outputs
    #      to the (unchanged) reference input. Preserves composition, closes the gap.
    for fn in files:
        d = load(fn); pname = d.get("name","")
        if "Material recovery & waste" not in pname: continue
        if "agregator" in pname or "aggregator" in pname: continue
        ri = refin(d)
        if not ri or not is_mass(ri): continue
        rin = float(ri.get("amount") or 0)
        outs = [e for e in d.get("exchanges",[]) if is_mass(e) and not e.get("isInput")]
        cur = sum(float(e.get("amount") or 0) for e in outs)
        if cur <= 0 or abs(cur - rin) <= TOL: continue
        s = rin/cur
        for e in outs:
            e["amount"] = float(e.get("amount") or 0) * s
        log.append(f"P3b BAL {pname[:40]}: outputs rescaled x{s:.4f} to close at {rin:g}")
        save(fn, d)

    # ---- PASS 4: EOL aggregators -> ref input = sum(component mass outputs); zero adjustment
    for fn in files:
        d = load(fn); pname = d.get("name","")
        if not any(k in pname for k in ("(NACELLE) agregator","(Rotor+hub) recovery aggregator","(BOP) agregator")):
            continue
        ri = refin(d)
        outs = [e for e in d.get("exchanges",[]) if is_mass(e) and not e.get("isInput")]
        ssum = sum(float(e.get("amount") or 0) for e in outs)
        # zero any non-ref mass INPUT (the accounting adjustment)
        for e in d.get("exchanges",[]):
            if e.get("isInput") and not e.get("isQuantitativeReference") and is_mass(e):
                if abs(float(e.get("amount") or 0)) > 0:
                    log.append(f"P4 AGG {pname[:40]}: zeroed adjustment input {e.get('amount'):g}")
                    e["amount"] = 0.0
        if ri:
            log.append(f"P4 AGG {pname[:40]}: ref input {ri.get('amount'):g} -> {ssum:g} (=sum components)")
            ri["amount"] = float(ssum)
        save(fn, d)

    # ---- PASS 5: MFG aggregators M1.5 nacelle -> ref out = sum(component inputs) - scraps
    for fn in files:
        d = load(fn); pname = d.get("name","")
        if "Nacelle complete" not in pname: continue
        ro = refout(d)
        comp_in = sum(float(e.get("amount") or 0) for e in d.get("exchanges",[])
                      if e.get("isInput") and is_mass(e))
        scrap = sum(float(e.get("amount") or 0) for e in d.get("exchanges",[])
                    if (not e.get("isInput")) and is_mass(e) and e is not ro)
        if ro:
            newout = comp_in - scrap
            log.append(f"P5 M1.5 nacelle: assembled {ro.get('amount'):g} -> {newout:g} (comp {comp_in:g} - scrap {scrap:g})")
            ro["amount"] = float(newout)
        save(fn, d)

    with open(os.path.join(DST,"..","CHANGE-LOG.txt"),"w",encoding="utf-8") as f:
        f.write("\n".join(log)+"\n")
    print("\n".join(log))
    print(f"\n{len(log)} edits. Corrected model in {DST}/")

if __name__ == "__main__":
    main()
