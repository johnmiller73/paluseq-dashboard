"""Create the PALUSEQ dashboard in a running Superset through its REST API.

Usage: python build_dashboard.py <superset_url> <user> <password> <sqlalchemy_uri_of_openhexa_db>
"""
import json
import sys
import uuid

import requests

URL, USER, PWD, DB_URI = sys.argv[1:5]
TABLE = "paluseq_marker_prevalence"

s = requests.Session()
tok = s.post(f"{URL}/api/v1/security/login",
             json={"username": USER, "password": PWD, "provider": "db", "refresh": True}).json()["access_token"]
s.headers["Authorization"] = f"Bearer {tok}"
try:
    s.headers["X-CSRFToken"] = s.get(f"{URL}/api/v1/security/csrf_token/").json()["result"]
except Exception:
    pass


def call(method, path, **kw):
    r = s.request(method, f"{URL}/api/v1/{path}", **kw)
    if r.status_code >= 400:
        raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:800]}")
    return r.json()


# --- database + dataset ----------------------------------------------------------
db_id = call("POST", "database/", json={"database_name": "OpenHEXA workspace", "sqlalchemy_uri": DB_URI,
                                        "expose_in_sqllab": True})["id"]
ds_id = call("POST", "dataset/", json={"database": db_id, "schema": "public", "table_name": TABLE})["id"]
ds = call("GET", f"dataset/{ds_id}")["result"]

labels = {"report_date": "Report date", "drug": "Drug", "marker_group": "Marker group", "gene": "Gene",
          "marker": "Marker", "level": "Level", "province": "Province", "iso_3166_2": "ISO code",
          "n_mutant": "Mutant samples", "n_tested": "Samples genotyped", "prevalence_pct": "Prevalence (%)",
          "detected": "Detected", "detected_nationally": "Detected nationally", "sheet": "Source sheet", "loaded_at": "Loaded at"}
columns = [{"id": c["id"], "column_name": c["column_name"], "verbose_name": labels.get(c["column_name"]),
            "is_dttm": c["column_name"] in ("report_date", "loaded_at"),
            "filterable": True, "groupby": True} for c in ds["columns"]]
metrics = [
    {"metric_name": "prevalence", "verbose_name": "Prevalence (%)", "d3format": ",.1f",
     "expression": "100.0 * SUM(n_mutant) / NULLIF(SUM(n_tested), 0)",
     "description": "Pooled prevalence: mutant samples / samples genotyped"},
    {"metric_name": "mutant_samples", "verbose_name": "Mutant samples", "expression": "SUM(n_mutant)"},
    {"metric_name": "samples_tested", "verbose_name": "Samples genotyped", "expression": "SUM(n_tested)"},
]
call("PUT", f"dataset/{ds_id}?override_columns=true", json={"columns": columns, "metrics": metrics,
     "main_dttm_col": "report_date",
     "description": "PALUSEQ drug-resistance marker prevalence by province, loaded by the OpenHEXA pipeline"})


def f(col, op, val):
    return {"expressionType": "SIMPLE", "subject": col, "operator": op, "comparator": val, "clause": "WHERE"}


PROV = f("level", "==", "Province")
NAT = f("level", "==", "National")
NON_K13 = f("drug", "!=", "Artemisinin")
K13_DETECTED = {"expressionType": "SQL", "clause": "WHERE",
                "sqlExpression": "marker_group LIKE 'k13 - WHO%' AND detected_nationally"}


def sqlm(expr, label):
    return {"expressionType": "SQL", "sqlExpression": expr, "label": label}


def chart(name, viz, params, desc=""):
    params = {"datasource": f"{ds_id}__table", "viz_type": viz, **params}
    cid = call("POST", "chart/", json={"slice_name": name, "viz_type": viz, "datasource_id": ds_id,
                                       "datasource_type": "table", "params": json.dumps(params),
                                       "description": desc})["id"]
    return cid, name


def kpi(name, metric, filters, fmt="SMART_NUMBER", sub=""):
    return chart(name, "big_number_total", {"metric": metric, "adhoc_filters": filters,
                                            "y_axis_format": fmt, "subheader": sub, "header_font_size": 0.4,
                                            "subheader_font_size": 0.15})


def heatmap(name, filters, desc="", bounds=(0, 100)):
    return chart(name, "heatmap_v2", {
        "x_axis": "province", "groupby": "marker", "metric": "prevalence", "adhoc_filters": filters,
        "row_limit": 10000, "sort_x_axis": "alpha_asc", "sort_y_axis": "alpha_desc",
        "normalize_across": "heatmap", "linear_color_scheme": "oranges", "show_values": True,
        "show_legend": True, "legend_type": "continuous", "y_axis_format": ",.1f",
        "value_bounds": list(bounds), "left_margin": 130, "bottom_margin": 70,
        "xscale_interval": 1, "yscale_interval": 1}, desc)


def bars(name, markers, desc=""):
    return chart(name, "echarts_timeseries_bar", {
        "x_axis": "province", "metrics": ["prevalence"], "groupby": ["marker"],
        "adhoc_filters": [PROV, f("marker", "IN", markers)], "row_limit": 10000,
        "orientation": "vertical", "show_value": False, "y_axis_format": ",.1f",
        "y_axis_title": "Prevalence (%)", "y_axis_title_margin": 40, "y_axis_title_position": "Left",
        "x_axis_sort_asc": True, "show_legend": True, "legendType": "scroll", "legendOrientation": "top",
        "color_scheme": "supersetColors", "rich_tooltip": True, "truncateYAxis": False,
        "y_axis_bounds": [0, 100], "zoomable": False, "xAxisLabelRotation": 45,
        "x_axis_title_margin": 30}, desc)


C = {}
C["prov"] = kpi("Provinces covered", sqlm("COUNT(DISTINCT province)", "Provinces"), [PROV])
C["markers"] = kpi("Markers monitored", sqlm("COUNT(DISTINCT marker)", "Markers"), [])
C["k13n"] = kpi("WHO-validated k13 mutant samples", "mutant_samples",
                [NAT, f("marker_group", "==", "k13 - WHO validated")], sub="samples carrying a validated k13 mutation")
C["k13max"] = kpi("Highest provincial prevalence, validated k13", sqlm("MAX(prevalence_pct)", "Max prevalence"),
                  [PROV, f("marker_group", "==", "k13 - WHO validated")], fmt=",.1f",
                  sub="% (any validated marker, any province)")
C["heat"] = heatmap("Partner-drug resistance markers by province (%)", [PROV, NON_K13],
                    "Prevalence of lumefantrine, chloroquine, amodiaquine, pyrimethamine and sulfadoxine markers")
C["k13heat"] = heatmap("WHO-listed k13 mutations detected, by province (%, colour scale 0-5)", [PROV, K13_DETECTED],
                       "WHO validated / candidate / potential k13 markers found in at least one sample nationally",
                       bounds=(0, 5))
C["sp"] = bars("SP resistance: key dhfr / dhps markers",
               ["dhps-Lys540Glu", "dhps-Ala581Gly", "dhps-Ser436Ala", "dhfr-ts-Ile164Leu"])
C["cq"] = bars("Chloroquine / amodiaquine markers",
               ["crt-Lys76Thr", "mdr1-Asn86Tyr", "mdr1-Asp1246Tyr", "mdr1-Tyr184Phe"])
C["table"] = chart("Marker prevalence detail", "table", {
    "query_mode": "raw",
    "all_columns": ["marker_group", "marker", "province", "n_mutant", "n_tested", "prevalence_pct"],
    "order_by_cols": [json.dumps(["prevalence_pct", False])], "adhoc_filters": [PROV, f("n_tested", ">", 0)],
    "row_limit": 5000, "server_page_length": 25, "include_search": True, "show_cell_bars": True,
    "table_timestamp_format": "%Y-%m-%d", "allow_rearrange_columns": True,
    "column_config": {"prevalence_pct": {"d3NumberFormat": ",.1f"}}})

# chart uuids, so the layout survives export/import into another Superset
_u = {c["id"]: c["uuid"] for c in call("GET", "chart/?q=(columns:!(id,uuid),page_size:100)")["result"]}

# --- layout ------------------------------------------------------------------------
pos = {"DASHBOARD_VERSION_KEY": "v2",
       "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
       "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
       "HEADER_ID": {"id": "HEADER_ID", "type": "HEADER", "meta": {"text": "PALUSEQ – Antimalarial drug resistance markers (DRC)"}}}


def row(items):
    rid = f"ROW-{uuid.uuid4().hex[:8]}"
    pos["GRID_ID"]["children"].append(rid)
    pos[rid] = {"type": "ROW", "id": rid, "children": [], "parents": ["ROOT_ID", "GRID_ID"],
                "meta": {"background": "BACKGROUND_TRANSPARENT"}}
    for kind, val, w, h in items:
        eid = f"{kind}-{uuid.uuid4().hex[:8]}"
        pos[rid]["children"].append(eid)
        if kind == "CHART":
            cid, name = C[val]
            meta = {"width": w, "height": h, "chartId": cid, "sliceName": name, "uuid": _u[cid]}
        else:
            meta = {"width": w, "height": h, "code": val}
        pos[eid] = {"type": kind, "id": eid, "children": [], "parents": ["ROOT_ID", "GRID_ID", rid], "meta": meta}


INTRO = """### PALUSEQ genomic surveillance – drug-resistance markers
Prevalence = mutant samples / samples genotyped at each codon, per province.
Use the filters on the left to pick a report date, drug, marker group, marker or province.
Data: *Paluseq_dashboard_summaries* workbook, loaded into the OpenHEXA workspace database by the **PALUSEQ dashboard loader** pipeline."""

row([("MARKDOWN", INTRO, 12, 16)])
row([("CHART", "prov", 3, 26), ("CHART", "markers", 3, 26), ("CHART", "k13n", 3, 26), ("CHART", "k13max", 3, 26)])
row([("CHART", "heat", 12, 100)])
row([("CHART", "k13heat", 12, 55)])
row([("CHART", "sp", 6, 70), ("CHART", "cq", 6, 70)])
row([("CHART", "table", 12, 90)])

# --- native filters -------------------------------------------------------------------
ids = {c: C[c][0] for c in C}
kpis = [ids["prov"], ids["markers"], ids["k13n"], ids["k13max"]]


def nf(name, col, multi=True, parents=(), exclude=(), first=False, desc="", prefilter=None):
    fid = f"NATIVE_FILTER-{uuid.uuid4().hex[:10]}"
    return fid, {
        "id": fid, "name": name, "filterType": "filter_select", "type": "NATIVE_FILTER", "description": desc,
        "targets": [{"datasetId": ds_id, "column": {"name": col}}],
        "controlValues": {"enableEmptyFilter": first, "defaultToFirstItem": first, "multiSelect": multi,
                          "searchAllOptions": False, "inverseSelection": False, "sortAscending": not first},
        "defaultDataMask": {"extraFormData": {}, "filterState": {}, "ownState": {}},
        "cascadeParentIds": list(parents), "scope": {"rootPath": ["ROOT_ID"], "excluded": list(exclude)},
        "adhoc_filters": prefilter or [], "time_range": "No filter"}


f_date, c_date = nf("Report date", "report_date", multi=False, first=True,
                    desc="Charts show one report at a time (latest by default)")
f_drug, c_drug = nf("Drug", "drug", exclude=kpis)
f_grp, c_grp = nf("Marker group", "marker_group", parents=[f_drug], exclude=kpis)
f_mk, c_mk = nf("Marker", "marker", parents=[f_grp], exclude=kpis)
f_prov, c_prov = nf("Province", "province", exclude=kpis, prefilter=[PROV])

meta = {"native_filter_configuration": [c_date, c_drug, c_grp, c_mk, c_prov],
        "color_scheme": "supersetColors", "refresh_frequency": 0, "cross_filters_enabled": True,
        "chart_configuration": {}, "shared_label_colors": [], "color_scheme_domain": [],
        "expanded_slices": {}, "label_colors": {}, "timed_refresh_immune_slices": []}

dash = call("POST", "dashboard/", json={
    "dashboard_title": "PALUSEQ – Antimalarial drug resistance markers (DRC)", "slug": "paluseq",
    "position_json": json.dumps(pos), "json_metadata": json.dumps(meta), "published": True})
dash_id = dash["id"]
for cid, _ in C.values():
    call("PUT", f"chart/{cid}", json={"dashboards": [dash_id]})
print(json.dumps({"dashboard_id": dash_id, "dataset_id": ds_id, "database_id": db_id}))
