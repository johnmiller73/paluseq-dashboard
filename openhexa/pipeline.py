"""PALUSEQ dashboard loader for OpenHEXA.

Reads a PALUSEQ "dashboard summaries" workbook (one sheet per marker group, cells like
"21.4% (866/4041)") and writes a tidy table to the OpenHEXA workspace database, where
Superset reads it.

Output table: paluseq_marker_prevalence (one row per report x marker x province)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from openhexa.sdk import File, current_run, parameter, pipeline, workspace
from sqlalchemy import create_engine, inspect, text

TABLE = "paluseq_marker_prevalence"

# Sheet name -> (marker group label, drug / class it is associated with)
SHEETS = {
    "WHO_validated_k13_markers": ("k13 - WHO validated", "Artemisinin"),
    "WHO_candidate_k13_markers": ("k13 - WHO candidate", "Artemisinin"),
    "WHO_potential_k13_markers": ("k13 - WHO potential", "Artemisinin"),
    "Other_k13_markers": ("k13 - other", "Artemisinin"),
    "lumefantrine_associated": ("Lumefantrine", "Lumefantrine"),
    "chloroquine_associated": ("Chloroquine", "Chloroquine"),
    "amodiaquine_associated": ("Amodiaquine", "Amodiaquine"),
    "pyrimethamine_associated": ("Pyrimethamine", "Pyrimethamine (SP)"),
    "sulfadoxine_associated": ("Sulfadoxine", "Sulfadoxine (SP)"),
}

# DRC provinces -> ISO 3166-2 code (used by the Superset country map)
PROVINCE_ISO = {
    "Bas-Uele": "CD-BU", "Equateur": "CD-EQ", "Haut Katanga": "CD-HK", "Haut Lomami": "CD-HL",
    "Haut Uele": "CD-HU", "Ituri": "CD-IT", "Kasai": "CD-KS", "Kasai Central": "CD-KC",
    "Kasai Oriental": "CD-KE", "Kinshasa": "CD-KN", "Kongo Central": "CD-BC", "Kwango": "CD-KG",
    "Kwilu": "CD-KL", "Lomami": "CD-LO", "Lualaba": "CD-LU", "Mai Ndombe": "CD-MN",
    "Maniema": "CD-MA", "Mongala": "CD-MO", "Nord Kivu": "CD-NK", "Nord Ubangi": "CD-NU",
    "Sankuru": "CD-SA", "Sud Kivu": "CD-SK", "Sud Ubangi": "CD-SU", "Tanganyika": "CD-TA",
    "Tshopo": "CD-TO", "Tshuapa": "CD-TU",
}

CELL_RE = re.compile(r"^\s*([\d.]+)%\s*\((\d+)\s*/\s*(\d+)\)\s*$")


def _norm(name: str) -> str:
    return re.sub(r"[\s_-]+", " ", str(name).strip()).replace("ï", "i").replace("é", "e").title()


def tidy_workbook(path: str | Path, report_date: date) -> pd.DataFrame:
    """Turn the wide workbook into one row per (marker, province)."""
    xls = pd.ExcelFile(path)
    frames = []
    for sheet in xls.sheet_names:
        group, drug = SHEETS.get(sheet, (sheet.replace("_", " "), "Other"))
        wide = xls.parse(sheet, dtype=str)
        wide = wide.rename(columns={wide.columns[0]: "marker"}).dropna(subset=["marker"])
        long = wide.melt(id_vars="marker", var_name="province", value_name="cell").dropna(subset=["cell"])
        parsed = long["cell"].str.extract(CELL_RE)
        bad = long[parsed.isna().any(axis=1)]
        if not bad.empty:
            raise ValueError(f"{sheet}: unparseable cells, e.g. {bad['cell'].head(3).tolist()}")
        long["n_mutant"] = parsed[1].astype(int)
        long["n_tested"] = parsed[2].astype(int)
        long["marker_group"] = group
        long["drug"] = drug
        long["sheet"] = sheet
        frames.append(long.drop(columns="cell"))

    df = pd.concat(frames, ignore_index=True)
    df["marker"] = df["marker"].str.strip()
    df["gene"] = df["marker"].str.extract(r"^([A-Za-z0-9]+(?:-ts)?)-")[0].fillna("crt")  # CVIET / SVMNT are crt 72-76 haplotypes
    df["is_overall"] = df["province"].str.strip().str.lower().eq("overall")
    df["level"] = df["is_overall"].map({True: "National", False: "Province"})
    df["province"] = df["province"].where(df["is_overall"], df["province"].map(_norm))
    df.loc[df["is_overall"], "province"] = "DRC (overall)"
    df["iso_3166_2"] = df["province"].map({_norm(k): v for k, v in PROVINCE_ISO.items()})
    df["prevalence_pct"] = (100.0 * df["n_mutant"] / df["n_tested"]).where(df["n_tested"] > 0).round(2)
    df["detected"] = df["n_mutant"] > 0
    nat_hits = df.loc[df["is_overall"] & df["detected"], "marker"]
    df["detected_nationally"] = df["marker"].isin(nat_hits)
    df["report_date"] = report_date
    df["loaded_at"] = pd.Timestamp(datetime.utcnow())
    cols = ["report_date", "drug", "marker_group", "gene", "marker", "level", "province",
            "iso_3166_2", "n_mutant", "n_tested", "prevalence_pct", "detected", "detected_nationally", "sheet", "loaded_at"]
    return df[cols]


def report_date_from_name(name: str) -> date:
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", name)
    return datetime.strptime("".join(m.groups()), "%Y%m%d").date() if m else date.today()


def write_table(df: pd.DataFrame, database_url: str) -> None:
    """Replace rows for this report date, keep earlier reports so trends build up."""
    # Pin the driver that is installed (SQLAlchemy 2.1 defaults to psycopg 3, OpenHEXA ships psycopg2)
    if database_url.startswith("postgresql://"):
        try:
            import psycopg2  # noqa: F401
            database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        except ImportError:
            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(database_url)
    with engine.begin() as conn:
        if inspect(conn).has_table(TABLE):
            conn.execute(text(f"DELETE FROM {TABLE} WHERE report_date = :d"),
                         {"d": df["report_date"].iloc[0]})
        df.to_sql(TABLE, conn, if_exists="append", index=False, chunksize=1000)


@pipeline(name="PALUSEQ dashboard loader")
@parameter("workbook", type=File, name="PALUSEQ summaries workbook (.xlsx)", required=True)
@parameter("report_date", type=str, name="Report date (YYYY-MM-DD)",
           help="Leave empty to read it from the file name (e.g. ..._20261015.xlsx)", required=False)
def paluseq_dashboard_loader(workbook: File, report_date: str | None = None):
    df = transform(workbook, report_date)
    load(df)


@paluseq_dashboard_loader.task
def transform(workbook: File, report_date: str | None) -> pd.DataFrame:
    rd = date.fromisoformat(report_date) if report_date else report_date_from_name(workbook.name)
    current_run.log_info(f"Reading {workbook.name} (report date {rd})")
    df = tidy_workbook(workbook.path, rd)
    unmapped = df.loc[(df["level"] == "Province") & df["iso_3166_2"].isna(), "province"].unique()
    if len(unmapped):
        current_run.log_warning(f"No ISO code for provinces: {', '.join(unmapped)} (map will skip them)")
    current_run.log_info(f"{len(df)} rows, {df['marker'].nunique()} markers, "
                         f"{df.loc[df['level'] == 'Province', 'province'].nunique()} provinces")
    return df


@paluseq_dashboard_loader.task
def load(df: pd.DataFrame) -> None:
    write_table(df, workspace.database_url)
    current_run.log_info(f"Wrote {len(df)} rows to workspace database table '{TABLE}'")


if __name__ == "__main__":
    paluseq_dashboard_loader()
