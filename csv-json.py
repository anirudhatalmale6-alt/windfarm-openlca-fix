
import csv
import json
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

# ================= CONFIGURATION =================
CSV_INVENTORY = "inventory.csv"
CSV_MAPPING = "mapping_background.csv"
CSV_PARAMS = "parameters.csv"

OUTPUT_DIR = "openlca_package"
ZIP_FILENAME = "FINAL_STRUCTURED_IMPORT.zip"

EXPORT_MAPPING_REPORT = True

# Make process UI panes look "tailored": only attach globals referenced by that process (+ mandatory globals)
FILTER_GLOBALS_PER_PROCESS = True

MANDATORY_GLOBALS = {
    "p_project_lifetime_yr_ALL",
    "p_capacity_factor_ALL",
    "p_distance_inland_es_km_ALL",
    "p_distance_sea_es_nl_km_ALL",
    "p_distance_inland_nl_km_ALL",
}

# Mandatory manufacturing processes to exist even if CSV misses them
MANDATORY_MANUFACTURING_SPECS = [
    # process_name, category, tech, region, ref_flow_name, ref_unit, ref_flow_property, ref_unit_group
    ("P-IEL15-MAN-ArrayCable-BOTH-EU",       "01_Manufacturing/BOTH", "BOTH", "EU", "F-IEL15-PRD-ArrayCable-BOTH-m",         "m",     "Length", "Length units"),
    ("P-IEL15-MAN-ExportCable-BOTH-EU",      "01_Manufacturing/BOTH", "BOTH", "EU", "F-IEL15-PRD-ExportCable-BOTH-m",        "m",     "Length", "Length units"),
    ("P-IEL15-MAN-Nacelle-BOTH-ES",          "01_Manufacturing/BOTH", "BOTH", "ES", "F-IEL15-PRD-Nacelle-BOTH-piece",        "piece", "Items",  "Item units"),
    ("P-IEL15-MAN-Rotor-BOTH-ES",            "01_Manufacturing/BOTH", "BOTH", "ES", "F-IEL15-PRD-Rotor-BOTH-piece",          "piece", "Items",  "Item units"),
    ("P-IEL15-MAN-Tower-BOTH-ES",            "01_Manufacturing/BOTH", "BOTH", "ES", "F-IEL15-PRD-Tower-BOTH-piece",          "piece", "Items",  "Item units"),
    ("P-IEL15-MAN-TurbineAssembly-BOTH-ES",  "01_Manufacturing/BOTH", "BOTH", "ES", "F-IEL15-PRD-TurbineAssembly-BOTH-piece","piece", "Items",  "Item units"),
    ("P-IEL15-MAN-OffshoreSubstation-BOTH-ES","01_Manufacturing/BOTH","BOTH", "ES", "F-IEL15-PRD-OffshoreSubstation-BOTH-piece","piece","Items","Item units"),
]

# Electricity flow used as manufacturing input (foreground flow, background link via mapping hints)
ELECTRICITY_FLOW_NAME = "F-IEL15-PRD-Electricity-BOTH-kWh"

# Cable electricity intensity params expected (PROCESS params)
ARRAY_ELEC_PARAM = "p_man_array_electricity_kwh_per_m_ALL"
EXPORT_ELEC_PARAM = "p_man_export_electricity_kwh_per_m_ALL"

# ================= ISO 14044 DATA QUALITY / UNCERTAINTY =================
# Ecoinvent pedigree-matrix uncertainty factors. Each data-quality indicator is
# scored 1 (best) .. 5 (worst); the value below is that score's contribution
# factor. The lognormal geometric SD is:
#     sigma_g = exp( sqrt( sum( ln(factor_i)^2 ) + ln(basic_uncertainty)^2 ) )
# This is what makes an openLCA Monte Carlo run meaningful (ISO 14044 interp.).
PEDIGREE_FACTORS = {
    "reliability":   [1.00, 1.05, 1.10, 1.20, 1.50],
    "completeness":  [1.00, 1.02, 1.05, 1.10, 1.20],
    "temporal":      [1.00, 1.03, 1.10, 1.20, 1.50],
    "geographical":  [1.00, 1.01, 1.02, 1.00, 1.10],
    "technological": [1.00, 1.05, 1.20, 1.50, 2.00],
}
# basic uncertainty (u_b) default by flow type - conservative, editable
BASIC_UNCERTAINTY = {
    "PRODUCT_FLOW": 1.05,
    "WASTE_FLOW": 1.05,
    "ELEMENTARY_FLOW": 1.10,
}
# If pedigree columns are missing from inventory.csv, optionally apply this
# default score set so every exchange still gets a defensible uncertainty.
# Set to None to leave uncertainty empty when no pedigree is supplied.
DEFAULT_PEDIGREE = (3, 3, 3, 3, 3)   # e.g. proxy/secondary data; None to disable

# ISO documentation block injected into every process's processDocumentation.
# Edit these once for your study; region/tech specifics are added per process.
ISO_DOC = {
    "intendedApplication":
        "Research LCA of an IEA/NREL 15 MW offshore wind farm (floating & monopile). "
        "Not intended for comparative assertions disclosed to the public.",
    "restrictionsDescription":
        "Attributional, cradle-to-grave. End-of-life modelled with a CUT-OFF approach "
        "(no recycling credits / avoided products). Life-cycle costing NOT in scope.",
    "dataSelectionDescription":
        "Foreground from IEA 15 MW reference turbine & NREL TP-5000-75698; "
        "background from ecoinvent 3.12.",
    "dataCompletenessDescription":
        "Mass balance closed on all component-recovery and aggregator processes; "
        "known material-inventory gaps documented per process.",
    "dataTreatmentDescription":
        "Parameterised foreground; dependent quantities via formulas. Uncertainty via "
        "the ecoinvent pedigree matrix (lognormal).",
    "inventoryMethodDescription":
        "Functional unit: one wind farm over its service life (cradle-to-grave).",
}

# ================= DETERMINISTIC IDs (UUIDv5) =================
NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace


import math

def compute_uncertainty(scores, flow_type, amount):
    """Return an openLCA lognormal Uncertainty dict from 5 pedigree scores, or None."""
    if scores is None:
        return None
    try:
        s = [int(round(float(x))) for x in scores]
    except (TypeError, ValueError):
        return None
    if len(s) != 5 or any(v < 1 or v > 5 for v in s):
        return None
    keys = ["reliability", "completeness", "temporal", "geographical", "technological"]
    var = 0.0
    for k, sc in zip(keys, s):
        f = PEDIGREE_FACTORS[k][sc - 1]
        var += math.log(f) ** 2
    ub = BASIC_UNCERTAINTY.get(flow_type, 1.05)
    var += math.log(ub) ** 2
    sigma_g = math.exp(math.sqrt(var))
    unc = {
        "@type": "Uncertainty",
        "distributionType": "LOG_NORMAL_DISTRIBUTION",
        "geomSd": round(sigma_g, 5),
    }
    # geomMean is only meaningful for a real positive amount; for formula-driven
    # exchanges openLCA derives the mean from the calculated value, so omit it.
    if amount is not None and float(amount) > 0:
        unc["geomMean"] = float(amount)
    return unc


def pedigree_scores_from_row(row):
    """Read optional dq_* pedigree columns; fall back to DEFAULT_PEDIGREE."""
    cols = ["dq_reliability", "dq_completeness", "dq_temporal",
            "dq_geographical", "dq_technological"]
    vals = [safe_str(row.get(c)) for c in cols]
    if all(v == "" for v in vals):
        return DEFAULT_PEDIGREE
    if any(v == "" for v in vals):
        return None  # partial -> skip rather than guess
    return vals


def build_process_documentation(region: str, tech: str) -> Dict:
    doc = {"@type": "ProcessDocumentation"}
    doc.update({k: v for k, v in ISO_DOC.items()})
    geo = {"ES": "Spain", "NL": "Netherlands", "NorthSea": "North Sea",
           "EU": "Europe", "EStoNL": "Spain to Netherlands (sea leg)"}.get(region, region or "")
    if geo:
        doc["geographyDescription"] = f"Geographical representativeness: {geo}."
    if tech:
        doc["technologyDescription"] = f"Technology branch: {tech} (IEA 15 MW reference turbine)."
    return doc


def did(kind: str, key: str) -> str:
    return str(uuid.uuid5(NS, f"IEL15::{kind}::{key}"))


def now_iso() -> str:
    return datetime.now().isoformat()


# ================= HELPERS =================
def safe_str(v) -> str:
    return "" if v is None else str(v).strip()


def clean_number(v) -> Optional[float]:
    s = safe_str(v)
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def normalize_unit(u: str) -> str:
    s = safe_str(u)
    if s.lower() == "kwh":
        return "kWh"
    return s


def require_columns(found_cols: List[str], required_cols: List[str], file_label: str):
    missing = [c for c in required_cols if c not in found_cols]
    if missing:
        raise ValueError(
            f"{file_label} is missing required columns: {missing}\n"
            f"Found columns: {list(found_cols)}"
        )


def make_ref(type_name: str, _id: str, name: str) -> Dict:
    return {"@type": type_name, "@id": _id, "name": name}


def write_json(path: str, data: Dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


PARAM_REF_RE = re.compile(r"\b(p_[A-Za-z0-9_]+)\b")


def extract_param_refs(text: str) -> Set[str]:
    if not text:
        return set()
    return set(PARAM_REF_RE.findall(text))


# ================= OPENLCA OBJECT BUILDERS =================
def make_parameter(
    name: str,
    scope_token: str,
    owner_process_name: str,
    is_input: bool,
    value: float,
    formula: str,
    description: str,
) -> Dict:
    """
    CRITICAL: prevent collisions.
      - GLOBAL param id key: GLOBAL::<name>
      - PROCESS param id key: PROCESS::<owner>::<name>
    """
    if scope_token == "GLOBAL_SCOPE":
        key = f"GLOBAL::{name}"
    else:
        key = f"PROCESS::{owner_process_name}::{name}"

    return {
        "@type": "Parameter",
        "@id": did("Parameter", key),
        "name": name,
        "parameterScope": scope_token,          # GLOBAL_SCOPE / PROCESS_SCOPE
        "isInputParameter": bool(is_input),
        "value": float(value),
        "formula": safe_str(formula),
        "description": safe_str(description),
        "lastChange": now_iso(),
        "version": "00.00.000",
        "category": "",
    }


def build_process_description(p_name: str, rows: List[Dict], proc_params: List[Dict]) -> str:
    stage = safe_str(rows[0].get("stage")) if rows else ""
    tech = safe_str(rows[0].get("tech")) if rows else ""
    region = safe_str(rows[0].get("region")) if rows else ""

    ref_flow = ""
    ref_comment = ""
    for r in rows:
        if safe_str(r.get("is_reference")).upper() == "TRUE" and safe_str(r.get("direction")).upper() == "OUTPUT":
            ref_flow = safe_str(r.get("flow_name"))
            ref_comment = safe_str(r.get("comment"))
            break

    proc_param_names = sorted({safe_str(p.get("name")) for p in (proc_params or []) if safe_str(p.get("name"))})

    parts = []
    parts.append("IEL15 foreground unit process (auto-generated).")
    if stage or tech or region:
        parts.append(f"Stage={stage}, Tech={tech}, Region={region}.")
    if ref_flow:
        parts.append(f"Reference product: {ref_flow}.")
    if ref_comment:
        parts.append(f"Reference note: {ref_comment}")
    parts.append("System boundary: manufacturing-to-grave; excludes mining/extraction.")
    parts.append("Logistics scenario explicitly represented (ES → Barcelona → NL port → staging/base → NorthSea) where applicable.")
    if proc_param_names:
        parts.append(
            "Process parameters: "
            + ", ".join(proc_param_names[:25])
            + (" …" if len(proc_param_names) > 25 else "")
            + "."
        )
    return " ".join([p.strip() for p in parts if p.strip()])


# ================= CSV AUGMENTATION: ensure mandatory processes & exchanges =================
def make_inventory_row(
    process_name: str,
    process_category: str,
    stage: str,
    tech: str,
    region: str,
    flow_name: str,
    flow_type: str,
    flow_property_name: str,
    unit_group_name: str,
    direction: str,
    is_reference: str,
    amount: str,
    unit: str,
    amount_formula: str,
    provider_process_name: str,
    provider_ref_flow_name: str,
    comment: str,
) -> Dict:
    return {
        "process_name": process_name,
        "process_category": process_category,
        "process_type": "UNIT_PROCESS",
        "stage": stage,
        "tech": tech,
        "region": region,
        "flow_name": flow_name,
        "flow_type": flow_type,
        "flow_property_name": flow_property_name,
        "unit_group_name": unit_group_name,
        "direction": direction,
        "is_reference": is_reference,
        "amount": amount,
        "unit": unit,
        "amount_formula": amount_formula,
        "provider_process_name": provider_process_name,
        "provider_ref_flow_name": provider_ref_flow_name,
        "comment": comment,
    }


def ensure_mandatory_manufacturing_processes(
    inventory_by_process: Dict[str, List[Dict]],
    process_categories: Dict[str, str],
):
    """
    If some mandatory manufacturing processes are missing from inventory.csv, create minimal placeholders:
    - one reference OUTPUT exchange
    - (for cables) electricity INPUT exchange
    """
    for (p_name, cat, tech, region, ref_flow, ref_unit, ref_fp, ref_ug) in MANDATORY_MANUFACTURING_SPECS:
        if p_name not in inventory_by_process:
            # create minimal process with reference output exchange
            inventory_by_process[p_name] = []
            process_categories[p_name] = cat

            inventory_by_process[p_name].append(
                make_inventory_row(
                    process_name=p_name,
                    process_category=cat,
                    stage="MAN",
                    tech=tech,
                    region=region,
                    flow_name=ref_flow,
                    flow_type="PRODUCT_FLOW",
                    flow_property_name=ref_fp,
                    unit_group_name=ref_ug,
                    direction="OUTPUT",
                    is_reference="TRUE",
                    amount="1",
                    unit=ref_unit,
                    amount_formula="",
                    provider_process_name="",
                    provider_ref_flow_name="",
                    comment=f"Reference product for {p_name}.",
                )
            )

        # ensure cables have electricity input
        if p_name == "P-IEL15-MAN-ArrayCable-BOTH-EU":
            ensure_electricity_input_exchange(
                inventory_by_process, process_categories, p_name,
                amount_formula=ARRAY_ELEC_PARAM,
                comment="Manufacturing electricity per meter of array cable."
            )
        elif p_name == "P-IEL15-MAN-ExportCable-BOTH-EU":
            ensure_electricity_input_exchange(
                inventory_by_process, process_categories, p_name,
                amount_formula=EXPORT_ELEC_PARAM,
                comment="Manufacturing electricity per meter of export cable."
            )


def ensure_electricity_input_exchange(
    inventory_by_process: Dict[str, List[Dict]],
    process_categories: Dict[str, str],
    process_name: str,
    amount_formula: str,
    comment: str,
):
    rows = inventory_by_process.get(process_name, [])
    # check if electricity input already exists
    for r in rows:
        if safe_str(r.get("flow_name")) == ELECTRICITY_FLOW_NAME and safe_str(r.get("direction")).upper() == "INPUT":
            return

    # infer stage/tech/region from existing rows
    stage = safe_str(rows[0].get("stage")) or "MAN"
    tech = safe_str(rows[0].get("tech")) or "BOTH"
    region = safe_str(rows[0].get("region")) or "EU"
    cat = process_categories.get(process_name, "01_Manufacturing/BOTH")

    rows.append(
        make_inventory_row(
            process_name=process_name,
            process_category=cat,
            stage=stage,
            tech=tech,
            region=region,
            flow_name=ELECTRICITY_FLOW_NAME,
            flow_type="PRODUCT_FLOW",
            flow_property_name="Energy",
            unit_group_name="Energy units",
            direction="INPUT",
            is_reference="FALSE",
            amount="",  # computed
            unit="kWh",
            amount_formula=amount_formula,
            provider_process_name="",
            provider_ref_flow_name="",
            comment=comment,
        )
    )


# ================= PARAM AUGMENTATION: auto-add placeholders for referenced-but-missing params =================
def ensure_missing_parameters(
    inventory_by_process: Dict[str, List[Dict]],
    global_params_by_name: Dict[str, Dict],
    process_params_by_owner: Dict[str, List[Dict]],
):
    existing_globals = set(global_params_by_name.keys())
    existing_proc = {
        owner: {safe_str(p.get("name")) for p in plist if safe_str(p.get("name"))}
        for owner, plist in process_params_by_owner.items()
    }

    for p_name, rows in inventory_by_process.items():
        refs: Set[str] = set()

        for r in rows:
            refs |= extract_param_refs(safe_str(r.get("amount_formula")))

        for pp in process_params_by_owner.get(p_name, []):
            refs |= extract_param_refs(safe_str(pp.get("formula")))

        existing_here = existing_proc.get(p_name, set())
        missing_here = sorted([x for x in refs if (x not in existing_globals and x not in existing_here)])

        for pname in missing_here:
            placeholder = make_parameter(
                name=pname,
                scope_token="PROCESS_SCOPE",
                owner_process_name=p_name,
                is_input=True,
                value=0.0,
                formula="",
                description="AUTO_ADDED placeholder (referenced in a formula but missing in parameters.csv). Please set value/unit/description in CSV.",
            )
            process_params_by_owner.setdefault(p_name, []).append(placeholder)
            existing_proc.setdefault(p_name, set()).add(pname)


def ensure_required_cable_params(process_params_by_owner: Dict[str, List[Dict]]):
    """
    Ensure the cable electricity intensity parameters exist as PROCESS inputs for cable processes,
    even if parameters.csv forgot them.
    """
    # Array cable
    owner = "P-IEL15-MAN-ArrayCable-BOTH-EU"
    if owner not in process_params_by_owner or ARRAY_ELEC_PARAM not in {p["name"] for p in process_params_by_owner.get(owner, [])}:
        process_params_by_owner.setdefault(owner, []).append(
            make_parameter(
                name=ARRAY_ELEC_PARAM,
                scope_token="PROCESS_SCOPE",
                owner_process_name=owner,
                is_input=True,
                value=0.0,
                formula="",
                description="Cable manufacturing electricity per meter (kWh/m). Set value in parameters.csv.",
            )
        )

    # Export cable
    owner = "P-IEL15-MAN-ExportCable-BOTH-EU"
    if owner not in process_params_by_owner or EXPORT_ELEC_PARAM not in {p["name"] for p in process_params_by_owner.get(owner, [])}:
        process_params_by_owner.setdefault(owner, []).append(
            make_parameter(
                name=EXPORT_ELEC_PARAM,
                scope_token="PROCESS_SCOPE",
                owner_process_name=owner,
                is_input=True,
                value=0.0,
                formula="",
                description="Cable manufacturing electricity per meter (kWh/m). Set value in parameters.csv.",
            )
        )


# ================= MAIN =================
def run_conversion():
    print("=== IEL15 CSV -> openLCA JSON-LD ZIP (with mandatory manufacturing + electricity input) ===")

    inv_required = [
        "process_name", "process_category", "process_type", "stage", "tech", "region",
        "flow_name", "flow_type", "flow_property_name", "unit_group_name",
        "direction", "is_reference", "amount", "unit", "amount_formula",
        "provider_process_name", "provider_ref_flow_name", "comment"
    ]

    map_required = [
        "process_name", "flow_name", "direction", "provider_process_name",
        "provider_ref_flow_name", "provider_location", "provider_database",
        "match_basis", "comment"
    ]

    par_required = [
        "parameter_name", "scope", "owner_process_name", "tech", "unit",
        "default_value", "kind", "formula", "description"
    ]

    if not os.path.exists(CSV_INVENTORY):
        print(f"ERROR: missing required file: {CSV_INVENTORY}")
        return

    # ================= 1) READ INVENTORY =================
    inventory_by_process: Dict[str, List[Dict]] = {}
    process_categories: Dict[str, str] = {}

    unit_groups_needed: Dict[str, Set[str]] = {}
    flow_prop_to_unit_group: Dict[str, str] = {}

    flow_to_prop: Dict[str, str] = {}
    flow_to_unit_group: Dict[str, str] = {}
    flow_to_flow_type: Dict[str, str] = {}

    with open(CSV_INVENTORY, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        require_columns(reader.fieldnames or [], inv_required, "inventory.csv")

        for row in reader:
            p = safe_str(row.get("process_name")) or "Imported_Process"
            cat = safe_str(row.get("process_category")).replace("\\", "/")

            inventory_by_process.setdefault(p, []).append(row)
            process_categories.setdefault(p, cat)

            fl = safe_str(row.get("flow_name"))
            fp = safe_str(row.get("flow_property_name")) or "Items"
            ug = safe_str(row.get("unit_group_name")) or "Item units"
            un = normalize_unit(row.get("unit"))

            if fl:
                flow_to_prop[fl] = fp
                flow_to_unit_group[fl] = ug
                flow_to_flow_type[fl] = safe_str(row.get("flow_type")).upper() or "PRODUCT_FLOW"

            flow_prop_to_unit_group[fp] = ug
            if un:
                unit_groups_needed.setdefault(ug, set()).add(un)

    # Ensure electricity flow metadata exists if we add it later
    flow_to_prop.setdefault(ELECTRICITY_FLOW_NAME, "Energy")
    flow_to_unit_group.setdefault(ELECTRICITY_FLOW_NAME, "Energy units")
    flow_to_flow_type.setdefault(ELECTRICITY_FLOW_NAME, "PRODUCT_FLOW")
    unit_groups_needed.setdefault("Energy units", set()).add("kWh")
    flow_prop_to_unit_group.setdefault("Energy", "Energy units")

    # ================= 1b) AUGMENT INVENTORY: ensure mandatory manufacturing + electricity input =================
    ensure_mandatory_manufacturing_processes(inventory_by_process, process_categories)

    print(f"> Processes after augmentation: {len(inventory_by_process)}")

    # ================= 2) READ MAPPING (optional) =================
    mapping_dict: Dict[Tuple[str, str, str], Dict] = {}
    mapping_rows: List[Dict] = []

    if os.path.exists(CSV_MAPPING):
        with open(CSV_MAPPING, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            require_columns(reader.fieldnames or [], map_required, "mapping_background.csv")
            for row in reader:
                p = safe_str(row.get("process_name"))
                fl = safe_str(row.get("flow_name"))
                di = safe_str(row.get("direction")).upper()
                key = (p, fl, di)
                mapping_dict[key] = {
                    "provider_process_name": safe_str(row.get("provider_process_name")),
                    "provider_ref_flow_name": safe_str(row.get("provider_ref_flow_name")),
                    "provider_location": safe_str(row.get("provider_location")),
                    "provider_database": safe_str(row.get("provider_database")),
                    "match_basis": safe_str(row.get("match_basis")),
                    "comment": safe_str(row.get("comment")),
                }
                mapping_rows.append({"key": key, **mapping_dict[key]})
        print(f"> Mapping rows: {len(mapping_dict)}")
    else:
        print("> mapping_background.csv not found (OK).")

    # ================= 3) READ PARAMETERS =================
    global_params_by_name: Dict[str, Dict] = {}
    process_params_by_owner: Dict[str, List[Dict]] = {}

    if os.path.exists(CSV_PARAMS):
        with open(CSV_PARAMS, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            require_columns(reader.fieldnames or [], par_required, "parameters.csv")

            for row in reader:
                name = safe_str(row.get("parameter_name")) or "param"
                scope_csv = safe_str(row.get("scope")).upper() or "GLOBAL"
                owner = safe_str(row.get("owner_process_name"))
                kind = safe_str(row.get("kind")).upper() or "INPUT"
                formula = safe_str(row.get("formula"))
                desc = safe_str(row.get("description"))
                unit = safe_str(row.get("unit"))
                tech = safe_str(row.get("tech"))

                full_desc = desc.strip() if desc else "TBD: missing description"
                meta = []
                if unit:
                    meta.append(f"unit={unit}")
                if tech:
                    meta.append(f"tech={tech}")
                if meta:
                    full_desc = f"{full_desc} [{', '.join(meta)}]"

                is_input = (kind == "INPUT")
                val = clean_number(row.get("default_value"))
                value = 0.0 if val is None else val

                if scope_csv == "GLOBAL":
                    p = make_parameter(
                        name=name,
                        scope_token="GLOBAL_SCOPE",
                        owner_process_name="",
                        is_input=is_input,
                        value=value,
                        formula="" if is_input else formula,
                        description=full_desc,
                    )
                    global_params_by_name[name] = p
                else:
                    if not owner:
                        continue
                    p = make_parameter(
                        name=name,
                        scope_token="PROCESS_SCOPE",
                        owner_process_name=owner,
                        is_input=is_input,
                        value=value,
                        formula="" if is_input else formula,
                        description=full_desc,
                    )
                    process_params_by_owner.setdefault(owner, []).append(p)
    else:
        print("> parameters.csv not found (OK, but will auto-add placeholders).")

    # Ensure cable electricity intensity params exist (PROCESS)
    ensure_required_cable_params(process_params_by_owner)

    # Auto-add placeholders for referenced params missing from CSV
    ensure_missing_parameters(inventory_by_process, global_params_by_name, process_params_by_owner)

    global_params_list = list(global_params_by_name.values())
    print(f"> Global parameters: {len(global_params_list)}")
    print(f"> Process parameters: {sum(len(v) for v in process_params_by_owner.values())}")

    # ================= 4) PREP OUTPUT DIRS =================
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)

    os.makedirs(os.path.join(OUTPUT_DIR, "processes"), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "flows"), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "parameters"), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "flow_properties"), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "unit_groups"), exist_ok=True)
    if EXPORT_MAPPING_REPORT:
        os.makedirs(os.path.join(OUTPUT_DIR, "reports"), exist_ok=True)

    # ================= 5) FLOW PROPERTIES =================
    flowprop_ids: Dict[str, str] = {}
    for fp_name in sorted(flow_prop_to_unit_group.keys()):
        fp_id = did("FlowProperty", fp_name)
        flowprop_ids[fp_name] = fp_id
        fp = {
            "@type": "FlowProperty",
            "@id": fp_id,
            "name": fp_name,
            "flowPropertyType": "PHYSICAL_QUANTITY",
            "category": "Technical flow properties",
            "lastChange": now_iso(),
            "version": "00.00.000",
        }
        write_json(os.path.join(OUTPUT_DIR, "flow_properties", f"{fp_id}.json"), fp)

    # ================= 6) UNIT GROUPS =================
    preferred_ref_unit = {
        "Mass units": "kg",
        "Energy units": "kWh",
        "Item units": "piece",
        "Length units": "m",
    }

    unit_ids: Dict[Tuple[str, str], str] = {}

    for ug_name in sorted(unit_groups_needed.keys()):
        ug_id = did("UnitGroup", ug_name)

        units_sorted = sorted([u for u in unit_groups_needed[ug_name] if u])
        if not units_sorted:
            units_sorted = [preferred_ref_unit.get(ug_name, "piece")]

        ref_unit_name = preferred_ref_unit.get(ug_name, units_sorted[0])
        if ref_unit_name not in units_sorted:
            units_sorted = [ref_unit_name] + units_sorted

        units = []
        for u in units_sorted:
            u_id = did("Unit", f"{ug_name}:{u}")
            unit_ids[(ug_name, u)] = u_id
            units.append({
                "@type": "Unit",
                "@id": u_id,
                "name": u,
                "description": "",
                "isRefUnit": (u == ref_unit_name),
                "conversionFactor": 1.0,
            })

        default_fp_name = None
        for fp, ug in flow_prop_to_unit_group.items():
            if ug == ug_name:
                default_fp_name = fp
                break

        ug = {
            "@type": "UnitGroup",
            "@id": ug_id,
            "name": ug_name,
            "category": "Technical unit groups",
            "lastChange": now_iso(),
            "version": "00.00.000",
            "units": units,
        }
        if default_fp_name and default_fp_name in flowprop_ids:
            ug["defaultFlowProperty"] = make_ref("FlowProperty", flowprop_ids[default_fp_name], default_fp_name)

        write_json(os.path.join(OUTPUT_DIR, "unit_groups", f"{ug_id}.json"), ug)

    # ================= 7) FLOWS =================
    flow_ids: Dict[str, str] = {}
    for flow_name in sorted(flow_to_flow_type.keys()):
        f_id = did("Flow", flow_name)
        flow_ids[flow_name] = f_id

        fp_name = flow_to_prop.get(flow_name, "Items")
        fp_id = flowprop_ids.get(fp_name, did("FlowProperty", fp_name))

        flow = {
            "@type": "Flow",
            "@id": f_id,
            "name": flow_name,
            "category": "IEL15/Foreground",
            "flowType": flow_to_flow_type.get(flow_name, "PRODUCT_FLOW"),
            "lastChange": now_iso(),
            "version": "00.00.000",
            "flowProperties": [
                {
                    "@type": "FlowPropertyFactor",
                    "isRefFlowProperty": True,
                    "conversionFactor": 1.0,
                    "flowProperty": make_ref("FlowProperty", fp_id, fp_name),
                }
            ],
        }
        write_json(os.path.join(OUTPUT_DIR, "flows", f"{f_id}.json"), flow)

    # ================= 8) WRITE GLOBAL PARAMETER DATASETS =================
    for p in global_params_list:
        write_json(os.path.join(OUTPUT_DIR, "parameters", f"{p['@id']}.json"), p)

    # ================= 9) PROCESSES =================
    process_ids: Dict[str, str] = {p: did("Process", p) for p in inventory_by_process.keys()}

    for p_name, rows in inventory_by_process.items():
        exchanges = []
        ref_count = 0
        last_internal_id = 0

        referenced_params: Set[str] = set()
        for r in rows:
            referenced_params |= extract_param_refs(safe_str(r.get("amount_formula")))
        for pp in process_params_by_owner.get(p_name, []):
            referenced_params |= extract_param_refs(safe_str(pp.get("formula")))

        for idx, row in enumerate(rows, start=1):
            last_internal_id = idx

            flow_name = safe_str(row.get("flow_name")) or f"Flow_{idx}"
            direction = safe_str(row.get("direction")).upper()
            is_ref = (safe_str(row.get("is_reference")).upper() == "TRUE")
            flow_type = safe_str(row.get("flow_type")).upper() or "PRODUCT_FLOW"

            if is_ref:
                ref_count += 1

            f_id = flow_ids.get(flow_name) or did("Flow", flow_name)

            fp_name = safe_str(row.get("flow_property_name")) or flow_to_prop.get(flow_name, "Items")
            fp_id = flowprop_ids.get(fp_name) or did("FlowProperty", fp_name)

            ug_name = safe_str(row.get("unit_group_name")) or flow_to_unit_group.get(flow_name, "Item units")
            unit_name = normalize_unit(row.get("unit"))
            u_id = unit_ids.get((ug_name, unit_name)) or did("Unit", f"{ug_name}:{unit_name}")

            amount = clean_number(row.get("amount"))
            amount_formula = safe_str(row.get("amount_formula"))
            comment = safe_str(row.get("comment"))

            ex = {
                "@type": "Exchange",
                "internalId": idx,
                "flow": make_ref("Flow", f_id, flow_name),
                "isInput": (direction == "INPUT"),
                "isQuantitativeReference": bool(is_ref),
                "isAvoidedProduct": False,
                "flowProperty": make_ref("FlowProperty", fp_id, fp_name),
                "unit": make_ref("Unit", u_id, unit_name),
            }

            if amount is not None:
                ex["amount"] = float(amount)
            else:
                ex["amount"] = 0.0
                if amount_formula:
                    ex["amountFormula"] = amount_formula

            # Put description into IO panels
            desc_parts = []
            if comment:
                desc_parts.append(comment)

            map_key = (p_name, flow_name, direction)
            if map_key in mapping_dict:
                m = mapping_dict[map_key]
                hint = (
                    f"BG_HINT provider='{m.get('provider_process_name')}', "
                    f"ref='{m.get('provider_ref_flow_name')}', "
                    f"loc='{m.get('provider_location')}', "
                    f"db='{m.get('provider_database')}', "
                    f"basis='{m.get('match_basis')}'"
                )
                desc_parts.append(hint)

            if desc_parts:
                ex["description"] = " | ".join(desc_parts)

            prov_p = safe_str(row.get("provider_process_name"))
            if prov_p and prov_p in process_ids:
                ex["defaultProvider"] = make_ref("Process", process_ids[prov_p], prov_p)

            # ISO 14044 uncertainty via pedigree matrix (optional dq_* columns).
            # Skip the reference flow: the functional unit is deterministic.
            if not is_ref:
                scores = pedigree_scores_from_row(row)
                unc = compute_uncertainty(scores, flow_type, amount)
                if unc is not None:
                    ex["uncertainty"] = unc
                    if scores and scores != DEFAULT_PEDIGREE:
                        ex["dqEntry"] = "(" + ";".join(str(int(round(float(x)))) for x in scores) + ")"

            exchanges.append(ex)

        if ref_count != 1:
            print(f"WARNING: process '{p_name}' has {ref_count} reference exchanges (expected exactly 1).")

        proc_specific = list(process_params_by_owner.get(p_name, []))

        if FILTER_GLOBALS_PER_PROCESS:
            wanted = set(referenced_params) | set(MANDATORY_GLOBALS)
            globals_for_process = [global_params_by_name[n] for n in sorted(wanted) if n in global_params_by_name]
        else:
            globals_for_process = list(global_params_list)

        proc_params = []
        proc_params.extend(globals_for_process)
        proc_params.extend(proc_specific)

        proc_id = process_ids[p_name]
        cat = process_categories.get(p_name, "")
        p_tech = safe_str(rows[0].get("tech")) if rows else ""
        p_region = safe_str(rows[0].get("region")) if rows else ""

        process_obj = {
            "@type": "Process",
            "@id": proc_id,
            "name": p_name,
            "processType": "UNIT_PROCESS",
            "category": cat,
            "description": build_process_description(p_name, rows, proc_specific),
            "lastChange": now_iso(),
            "version": "00.00.000",
            "lastInternalId": last_internal_id,
            "processDocumentation": build_process_documentation(p_region, p_tech),
            "exchanges": exchanges,
            "parameters": proc_params,
        }

        write_json(os.path.join(OUTPUT_DIR, "processes", f"{proc_id}.json"), process_obj)

    # ================= 10) OPTIONAL REPORT =================
    if EXPORT_MAPPING_REPORT and mapping_rows:
        report = {
            "generatedAt": now_iso(),
            "note": (
                "This report captures mapping_background.csv rows. "
                "This ZIP does not include resolvable ecoinvent provider datasets. "
                "Use these hints for manual linking or extend exporter to create provider processes."
            ),
            "mappings": mapping_rows,
        }
        write_json(os.path.join(OUTPUT_DIR, "reports", "mapping_report.json"), report)

    # ================= 11) ZIP =================
    if os.path.exists(ZIP_FILENAME):
        os.remove(ZIP_FILENAME)

    with zipfile.ZipFile(ZIP_FILENAME, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(OUTPUT_DIR):
            for fn in files:
                full = os.path.join(root, fn)
                arc = os.path.relpath(full, OUTPUT_DIR)
                z.write(full, arc)

    print(f"\nSUCCESS: wrote {ZIP_FILENAME}")
    print("Import in openLCA via: File -> Import -> openLCA package (JSON-LD).")
    print("This version auto-adds mandatory manufacturing processes and the missing electricity input for cable manufacturing.")


if __name__ == "__main__":
    run_conversion()
