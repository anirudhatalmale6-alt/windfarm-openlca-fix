TITLE: OpenLCA CSV Export Prompt — 3 Stable CSVs per Run (openLCA 2.6 JSON-LD ZIP Ready) — v2.4 (Cradle-to-Grave + DEPENDENT Formula Enforcement + ISO 14044 Pedigree Uncertainty)

STUDY SETTINGS (FIXED FOR THIS PROJECT)
- Type: attributional research LCA (environmental: carbon / energy). Life-Cycle Costing (LCC) is NOT in scope — do NOT emit cost/revenue data.
- End-of-life: CUT-OFF approach. Recovered materials are NOT modelled as avoided products / recycling credits; waste flows are cut off at the point of recovery. Do NOT set isAvoidedProduct.
- Uncertainty: every non-reference exchange carries a lognormal distribution derived from an ecoinvent pedigree score (see DATA QUALITY section). The converter computes the geometric SD; you only supply the 1–5 scores.
- ISO documentation (goal, scope, functional unit, boundary, cut-off, data sources, representativeness) is injected into every process by the converter — you do not need to emit it.

ROLE
You are a senior LCA practitioner and openLCA database architect. Produce a complete foreground model snapshot for an IEL/NRL 15 MW offshore wind farm with two technology branches:
- Floating foundation (IEL15-FLT)
- Bottom-fixed monopile (IEL15-MP)

GOAL
Every time this prompt is run, you MUST generate a FULL, SELF-CONTAINED snapshot in EXACTLY THREE DOWNLOADABLE CSV files:
1) inventory.csv
2) mapping_background.csv
3) parameters.csv

The snapshot content may differ between runs, BUT the CSV SCHEMA MUST NEVER CHANGE and the snapshot must be internally consistent so a converter can always build a valid openLCA JSON-LD ZIP.

NON-NEGOTIABLE RULES
A) SINGLE SHOT: Output all 3 CSVs in this one response. DO NOT output markdown documentation, implementation guides, or any other format. ONLY output the three CSV files.
B) NO QUESTIONS: Do not ask follow-ups. Use blanks + comments when unknown.
C) STABLE CSV SCHEMA: Headers must match EXACTLY (see below). Output MUST be valid CSV data inside ```csv code blocks, NOT markdown tables, NOT prose descriptions.
D) CSV SAFETY (RFC4180): Wrap ALL TEXT FIELDS in double quotes. Escape " as "" inside text. Replace newlines with spaces.
E) DETERMINISTIC SORTING (for reproducibility within a run):
   - inventory.csv: sort by stage, tech, process_name, direction, flow_name
   - mapping_background.csv: sort by process_name, direction, flow_name
   - parameters.csv: sort by scope, kind, owner_process_name, parameter_name
F) UI REQUIREMENT: Each exchange MUST carry human-readable description text so it appears in the openLCA Inputs/Outputs panels. Therefore inventory.csv "comment" MUST be filled for every exchange row (reference + non-reference).
G) FORMAT ENFORCEMENT: Your ENTIRE response must contain ONLY three CSV code blocks. No introductions, no explanations, no summaries, no implementation guides, no markdown documentation. Just the three CSVs.

SYSTEM BOUNDARY (FIXED)
- Cradle-to-grave: include raw material extraction, manufacturing, transport, installation, operation and maintenance, and end-of-life.
- Stages must exist: RAW, MAN, TRP, INS, OM, EOL.
- RAW stage covers upstream raw material extraction and processing (mining, refining, smelting). These are typically linked to ecoinvent background processes via mapping_background.csv rather than modelled as foreground processes.
- Logistics scenario MUST be represented explicitly:
  Manufacturing Spain (ES) -> inland to Barcelona port -> sea to Netherlands port -> inland to staging/base -> offshore site (NorthSea).
- Electricity supply for manufacturing/port ops/vessels is allowed (not mining); link electricity supply in mapping_background.csv to background providers.

NAMING CONVENTIONS (MUST FOLLOW EXACTLY)

Processes:
"P-IEL15-<Stage>-<Component>-<Tech>-<Region>"
Stage must be one of: RAW, MAN, TRP, INS, OM, EOL
Tech must be one of: FLT, MP, BOTH
Region must be one of: ES, NL, NorthSea, EU (plus "EStoNL" for sea leg)

Flows (foreground reference products/wastes only; background links go in mapping):
"F-IEL15-<Type>-<Name>-<Tech>-<Unit>"
Type must be one of: PRD, WST

Parameters:
"p_<descriptive_name>_<tech_suffix>"
tech_suffix must be one of: ALL, FLT, MP
Formulas may reference p_* parameters only.

Category/Directory Structure:
Process categories MUST follow this pattern exactly:
- "00_RawMaterials/BOTH" or "00_RawMaterials/FLT" or "00_RawMaterials/MP"
- "01_Manufacturing/BOTH" or "01_Manufacturing/FLT" or "01_Manufacturing/MP"
- "02_Transport/BOTH" or "02_Transport/FLT" or "02_Transport/MP"
- "03_Installation/BOTH" or "03_Installation/FLT" or "03_Installation/MP"
- "04_OM/BOTH" or "04_OM/FLT" or "04_OM/MP"
- "05_EndOfLife/BOTH" or "05_EndOfLife/FLT" or "05_EndOfLife/MP"

CRITICAL: PARAMETER CATEGORIZATION RULES

OpenLCA displays parameters in THREE sections per process:
1. Global parameters - shared across the entire database
2. Input parameters - process-level editable values
3. Dependent parameters - process-level calculated values with formulas

You MUST correctly assign scope and kind for EVERY parameter. Follow these rules strictly:

SCOPE RULES:
- Use scope="GLOBAL" ONLY for parameters shared across multiple processes (e.g., project lifetime, capacity factor, distances, hours per year, farm capacity). These are database-wide constants.
- Use scope="PROCESS" for parameters specific to ONE process or used in ONE process context (e.g., mass of a specific component, electricity intensity for a specific manufacturing step, vessel days for a specific installation). ALWAYS fill owner_process_name for PROCESS-scoped parameters.

KIND RULES:
- Use kind="INPUT" for parameters where the user provides a direct numeric value (no formula needed). These appear in the "Input parameters" section in OpenLCA.
- Use kind="DEPENDENT" for parameters calculated from other parameters using a formula. These appear in the "Dependent parameters" section. ALWAYS fill the formula field for DEPENDENT parameters. Formulas must reference only p_* parameter names.

EXAMPLES OF CORRECT CATEGORIZATION:

GLOBAL + INPUT (shared constants with direct values):
parameter_name: p_project_lifetime_yr_ALL, scope: GLOBAL, kind: INPUT, default_value: 25, formula: ""
parameter_name: p_capacity_factor_ALL, scope: GLOBAL, kind: INPUT, default_value: 0.45, formula: ""
parameter_name: p_hours_per_year_ALL, scope: GLOBAL, kind: INPUT, default_value: 8760, formula: ""
parameter_name: p_farm_capacity_mw_ALL, scope: GLOBAL, kind: INPUT, default_value: 15, formula: ""

GLOBAL + DEPENDENT (calculated from other globals):
parameter_name: p_electricity_lifetime_kwh_ALL, scope: GLOBAL, kind: DEPENDENT, default_value: "", formula: "p_farm_capacity_mw_ALL*1000*p_hours_per_year_ALL*p_capacity_factor_ALL*p_project_lifetime_yr_ALL"

PROCESS + INPUT (process-specific editable values):
parameter_name: p_tower_steel_kg_ALL, scope: PROCESS, owner_process_name: "P-IEL15-MAN-Tower-BOTH-ES", kind: INPUT, default_value: 400000
parameter_name: p_nacelle_copper_kg_ALL, scope: PROCESS, owner_process_name: "P-IEL15-MAN-Nacelle-BOTH-ES", kind: INPUT, default_value: 5000
parameter_name: p_foundation_steel_kg_FLT, scope: PROCESS, owner_process_name: "P-IEL15-MAN-Foundation-FLT-ES", kind: INPUT, default_value: 300000

PROCESS + DEPENDENT (calculated within a process):
parameter_name: p_total_tower_steel_kg_ALL, scope: PROCESS, owner_process_name: "P-IEL15-MAN-Tower-BOTH-ES", kind: DEPENDENT, formula: "p_tower_steel_kg_ALL*p_turbine_count_ALL"

COMMON MISTAKES TO AVOID:
- DO NOT make all parameters GLOBAL. Only database-wide constants should be GLOBAL.
- DO NOT leave kind blank or default everything to INPUT. Parameters with formulas MUST be DEPENDENT.
- DO NOT leave owner_process_name blank for PROCESS-scoped parameters.
- DO NOT put formulas in INPUT parameters. INPUT parameters have direct values only.
- DO NOT create duplicate parameter names across different scopes without different owner processes.
- EVERY DEPENDENT parameter MUST have a non-empty formula field containing a valid expression using p_* parameter names. If you cannot write the formula, mark the parameter as INPUT instead and put a numeric value. NEVER leave formula blank for a DEPENDENT parameter.
- DEPENDENT parameter values should be left blank (the formula calculates them). Do NOT put a hardcoded number AND a formula.

MANDATORY PROCESSES

Manufacturing (MUST EXIST):
- "P-IEL15-MAN-ArrayCable-BOTH-ES"
- "P-IEL15-MAN-ExportCable-BOTH-EU"
- "P-IEL15-MAN-Nacelle-BOTH-ES"
- "P-IEL15-MAN-Rotor-BOTH-ES"
- "P-IEL15-MAN-Tower-BOTH-ES"
- "P-IEL15-MAN-TurbineAssembly-BOTH-ES"
- "P-IEL15-MAN-OffshoreSubstation-BOTH-ES"
- "P-IEL15-MAN-Blades-BOTH-ES"
- "P-IEL15-MAN-Foundation-FLT-ES"
- "P-IEL15-MAN-Foundation-MP-ES"

Transport (MUST EXIST):
- "P-IEL15-TRP-Inland-BOTH-ES"
- "P-IEL15-TRP-PortOps-BOTH-ES"
- "P-IEL15-TRP-Sea-BOTH-EStoNL"
- "P-IEL15-TRP-PortOps-BOTH-NL"
- "P-IEL15-TRP-Inland-BOTH-NL"

Installation, OM, EOL processes should also be included for both FLT and MP branches.

MANDATORY GLOBAL PARAMETERS (MUST EXIST):
- "p_project_lifetime_yr_ALL" (scope=GLOBAL, kind=INPUT)
- "p_capacity_factor_ALL" (scope=GLOBAL, kind=INPUT)
- "p_distance_inland_es_km_ALL" (scope=GLOBAL, kind=INPUT)
- "p_distance_sea_es_nl_km_ALL" (scope=GLOBAL, kind=INPUT)
- "p_distance_inland_nl_km_ALL" (scope=GLOBAL, kind=INPUT)
- "p_hours_per_year_ALL" (scope=GLOBAL, kind=INPUT)
- "p_farm_capacity_mw_ALL" (scope=GLOBAL, kind=INPUT)
- "p_turbine_count_ALL" (scope=GLOBAL, kind=INPUT)

MODEL CONSISTENCY RULES
1) Each unit process must have EXACTLY ONE quantitative reference OUTPUT exchange (is_reference="TRUE").
2) All other exchanges are is_reference="FALSE".
3) direction is "INPUT" or "OUTPUT".
4) Units MUST be compatible with flow properties:
   - Mass -> "Mass units" and unit in {"kg","g","t"}
   - Energy -> "Energy units" and unit in {"kWh","MJ"}
   - Items -> "Item units" and unit in {"piece"}
   - Length -> "Length units" and unit in {"m","km"}
5) Every parameter referenced in an amount_formula MUST exist in parameters.csv.
6) Every process referenced in provider_process_name MUST exist in inventory.csv.

BACKGROUND LINKING RULES
- Do NOT put "(background)" in provider fields in inventory.csv.
- Background provider mapping goes ONLY in mapping_background.csv.
- If a background provider is unknown, leave provider fields blank and set match_basis="TBD".
- Flows will NOT have providers set in inventory.csv because ecoinvent links will be connected manually in OpenLCA.

CSV 1: inventory.csv (HEADER MUST MATCH EXACTLY)
process_name,process_category,process_type,stage,tech,region,flow_name,flow_type,flow_property_name,unit_group_name,direction,is_reference,amount,unit,amount_formula,provider_process_name,provider_ref_flow_name,comment,dq_reliability,dq_completeness,dq_temporal,dq_geographical,dq_technological

Rules:
- process_type always "UNIT_PROCESS"
- process_category follows the directory structure defined above
- flow_type must be one of: PRODUCT_FLOW, WASTE_FLOW, ELEMENTARY_FLOW
- amount is numeric when known; if computed, leave amount blank and fill amount_formula
- comment MUST be populated for every exchange to appear in openLCA IO panels
- provider_process_name and provider_ref_flow_name: only fill for internal foreground links (e.g., TurbineAssembly consuming Nacelle from Nacelle manufacturing). Leave blank for flows that will be linked to ecoinvent manually.
- dq_* columns are the ecoinvent pedigree scores (see DATA QUALITY section). Fill all five with an integer 1–5 for every NON-reference exchange. Leave all five BLANK on the reference (is_reference="TRUE") row. If you fill some but not all five, the converter skips that row's uncertainty — so fill all five or none.

DATA QUALITY / UNCERTAINTY (PEDIGREE MATRIX)
Score each non-reference exchange 1 (best) to 5 (worst) on five indicators. The converter turns these into a lognormal geometric SD automatically; you never compute it.
- dq_reliability: 1 = measured/verified primary data; 3 = calculated from assumptions; 5 = non-qualified estimate.
- dq_completeness: 1 = representative data from a sufficient sample; 5 = single/limited data point.
- dq_temporal: 1 = within a few years of the reference year; 5 = age unknown or very old.
- dq_geographical: 1 = exact geography; 5 = clearly different/unknown geography.
- dq_technological: 1 = same technology & scale; 5 = different technology.
Suggested defaults by data source (use these unless you have better information):
- Primary IEA 15 MW / NREL TP-5000-75698 foreground data: 2,2,2,2,2
- ecoinvent 3.12 proxy used as-is: 3,3,3,2,3
- Rough estimate / placeholder: 4,4,4,3,4

CSV 2: mapping_background.csv (HEADER MUST MATCH EXACTLY)
process_name,flow_name,direction,provider_process_name,provider_ref_flow_name,provider_location,provider_database,match_basis,comment

Rules:
- This CSV provides hints for manual ecoinvent linking. It is NOT imported into OpenLCA.
- provider_database should be "ecoinvent_3.12" or the relevant version.
- match_basis should describe how to find the provider: "NAME+LOCATION", "NAME_ONLY", or "TBD".

CSV 3: parameters.csv (HEADER MUST MATCH EXACTLY)
parameter_name,scope,owner_process_name,tech,unit,default_value,kind,formula,description

Rules:
- scope MUST be "GLOBAL" or "PROCESS" (no other values)
- kind MUST be "INPUT" or "DEPENDENT" (no other values)
- For GLOBAL parameters: owner_process_name MUST be blank
- For PROCESS parameters: owner_process_name MUST contain the exact process name from inventory.csv
- For INPUT parameters: provide default_value (numeric), formula MUST be blank
- For DEPENDENT parameters: formula MUST contain a valid expression using p_* parameter names, default_value can be blank
- description MUST be filled for every parameter
- tech must be one of: ALL, FLT, MP

PARAMETER DISTRIBUTION GUIDELINE:
Aim for approximately this distribution:
- 8-15 GLOBAL INPUT parameters (project-wide constants like lifetime, capacity, distances)
- 3-8 GLOBAL DEPENDENT parameters (calculated from global inputs, like lifetime electricity)
- 30-60 PROCESS INPUT parameters (component masses, intensities, vessel days - one per process that needs them)
- 5-15 PROCESS DEPENDENT parameters (totals calculated from inputs, like total_steel = steel_per_unit * count)

OUTPUT FORMAT (STRICT — VIOLATION MEANS FAILURE)
Your response MUST contain EXACTLY this structure and NOTHING ELSE:

### inventory.csv
```csv
process_name,process_category,process_type,stage,tech,region,flow_name,flow_type,flow_property_name,unit_group_name,direction,is_reference,amount,unit,amount_formula,provider_process_name,provider_ref_flow_name,comment,dq_reliability,dq_completeness,dq_temporal,dq_geographical,dq_technological
[rows here]
```

### mapping_background.csv
```csv
process_name,flow_name,direction,provider_process_name,provider_ref_flow_name,provider_location,provider_database,match_basis,comment
[rows here]
```

### parameters.csv
```csv
parameter_name,scope,owner_process_name,tech,unit,default_value,kind,formula,description
[rows here]
```

FORBIDDEN OUTPUTS (any of these means you failed):
- Markdown documentation or implementation guides
- Prose explanations or summaries
- Tables in markdown format
- Executive summaries or model structure diagrams
- Multiple separate files that are not the three CSVs above
- Any text before the first ### or after the last ```
