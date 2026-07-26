OPENLCA FIX MERGE — HOW TO GET CLAUDE'S PROCESS CORRECTIONS INTO YOUR MODEL
===========================================================================

WHY YOUR EARLIER IMPORT "DID NOTHING"
-------------------------------------
The fix package Claude made is actually correct — I checked it object by object:
  * All 16 corrected processes carry the SAME UUIDs as the ones in your model,
    with their version numbers bumped (so they are edits, not new objects).
  * The one new flow ("Nacelle recovery accounting adjustment") is included.
  * Every flow the corrected processes point to already exists in your export.
So the file is importable and self-consistent. The reason nothing changed is
openLCA's import behaviour: when it meets an object whose UUID already exists in
the target database, it KEEPS the existing one unless overwrite is forced. A
"changed-objects-only" package therefore looks like it did nothing.

Your parameters and formulas are NOT touched by any of this. The fix only edits
process exchanges (inputs/outputs) and two flows.


WHAT I DID
----------
I merged the fix package on top of your FULL export and produced one complete,
corrected database:

  WINDFARM-EOL-CORRECTED-MERGED.zip

Contents: 55 processes, 193 flows, 15 parameters (untouched), plus all unit
groups / flow properties / locations. It imports as one clean, whole database.


HOW TO USE IT  (recommended — guaranteed, no overwrite guesswork)
-----------------------------------------------------------------
1. In openLCA: Databases panel > right-click > New database > empty database.
2. Open it, then File > Import > Linked Data (JSON-LD).
3. Choose WINDFARM-EOL-CORRECTED-MERGED.zip. Import.
4. Everything lands with the corrections in place. Calculate / validate here.

Because the target DB is empty, there are no UUID conflicts — every object is
created once, already corrected.

ALTERNATIVE (keep working in your existing database):
Re-import the small fix package into your current DB, but make sure openLCA is
set to OVERWRITE / update existing data sets during the import (not "keep").
That forces the 16 edited processes to be replaced. The merged-into-empty-DB
route above avoids this setting entirely, which is why I recommend it.


WHAT'S FIXED vs WHAT STILL NEEDS YOUR DATA
------------------------------------------
Applied by this merge (audit items 4, 5, 7, 8):
  * Item 4 — EOL5.4.1/5.4.2/5.4.3 reference flows re-pointed to the correct
    Rotor+hub-blades / -generator / -hub partial flows (no more shared-flow clash).
  * Item 5 — Nacelle aggregator now balances: 630,888 + 105,112 = 736,000 kg
    in = 736,000 kg out.  (accounting-adjustment input added)
  * Item 7 — Rotor+hub aggregator reference changed off the phantom flow to the
    canonical "Rotor and hub, recovered" @ 756,000 kg.  Now 756,000 = 756,000.
  * Item 8 — category path typos fixed on the 12 Nacelle/BOP processes.

Still open — need YOUR NREL material composition (only you have the source):
  * Item 1 — EOL5.3.3.1 Generator stator: outputs only 28,700 of 371,000 kg in
    (missing ~342 t: electrical steel, structural steel, NdFeB, Cu windings…).
  * Item 2 — EOL5.4.2 Generator (rotor): missing ~158 t.
  * Item 3 — EOL5.4.3 Hub: missing ~50 t.
  * Item 6 — EOL5.3.6.4 SCADA reference exchange unit is null → set "kg" in the
    exchange editor (1-click, best done in the openLCA UI).


THE VALIDATOR / RE-RUN TOOL
---------------------------
merge_openlca_fix.py does the merge AND prints a mass-balance table so you can
see which processes don't balance BEFORE importing. Re-run it every round:

  python merge_openlca_fix.py  YOUR_EXPORT.zip  YOUR_FIX.zip  OUTPUT.zip

Read the mass-balance table like this:
  * Recovery / separation / aggregator processes SHOULD conserve mass — if one
    shows "X d=+NNN" there, that delta is a real gap to chase (it matches
    Claude's audit numbers exactly). The three items above are the current gaps.
  * Manufacturing / transport / installation processes are expected NOT to
    balance by a naive in=out sum (they consume materials + energy and emit a
    single reference product), so ignore their deltas.

Workflow loop: fix BOM in your source → regenerate the fix package → run this
script → check the table → import the merged zip into a fresh DB → calculate →
repeat until the recovery branch balances.

No third-party libraries needed. Python 3.8+.
