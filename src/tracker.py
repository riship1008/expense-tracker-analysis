"""Personal expense tracker: import bank CSV exports, categorize, store in SQLite, summarize.

Usage:
    python src/tracker.py import data/sample/sample_bank_export.csv
    python src/tracker.py summary --month 2026-03
    python src/tracker.py uncategorized
    python src/tracker.py budget
"""

import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "expenses.db"
RULES_PATH = ROOT / "config" / "categories.json"

# Column names used by common bank exports -> our standard names
FORMATS = {
    "chase":       {"date": "Transaction Date", "description": "Description", "amount": "Amount"},
    "bofa":        {"date": "Date", "description": "Description", "amount": "Amount"},
    "capital_one": {"date": "Transaction Date", "description": "Description", "debit": "Debit", "credit": "Credit"},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,
    description TEXT NOT NULL,
    amount      REAL NOT NULL,          -- negative = money out, positive = money in
    category    TEXT NOT NULL,
    grp         TEXT NOT NULL,          -- Income / Essential / Discretionary / Transfer / Other
    source_file TEXT,
    UNIQUE (date, description, amount)  -- re-importing the same file never duplicates rows
);
"""


def detect_format(columns: list[str]) -> str:
    cols = set(columns)
    for name, spec in FORMATS.items():
        if set(spec.values()) <= cols:
            return name
    raise ValueError(f"Unrecognized bank export. Columns found: {columns}")


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert any supported bank export into date / description / amount."""
    fmt = FORMATS[detect_format(list(raw.columns))]
    out = pd.DataFrame({
        "date": pd.to_datetime(raw[fmt["date"]]).dt.strftime("%Y-%m-%d"),
        "description": raw[fmt["description"]].astype(str).str.strip().str.upper(),
    })
    if "amount" in fmt:
        out["amount"] = pd.to_numeric(raw[fmt["amount"]])
    else:  # Capital One splits money in and out into two columns
        out["amount"] = pd.to_numeric(raw[fmt["credit"]]).fillna(0) - pd.to_numeric(raw[fmt["debit"]]).fillna(0)
    return out


def load_rules(path: Path = RULES_PATH) -> list[dict]:
    return json.loads(path.read_text())["rules"]


def categorize(descriptions: pd.Series, rules: list[dict] | None = None) -> pd.DataFrame:
    """Keyword-based categorization. First matching rule wins."""
    rules = rules or load_rules()
    categories, groups = [], []
    for desc in descriptions.str.upper():
        match = next((r for r in rules if any(k in desc for k in r["keywords"])), None)
        categories.append(match["category"] if match else "Uncategorized")
        groups.append(match["group"] if match else "Other")
    return pd.DataFrame({"category": categories, "grp": groups}, index=descriptions.index)


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def import_csv(path: Path, db_path: Path = DB_PATH) -> int:
    tx = normalize(pd.read_csv(path))
    tx = tx.join(categorize(tx["description"]))
    tx["source_file"] = Path(path).name
    with connect(db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        conn.executemany(
            "INSERT OR IGNORE INTO transactions (date, description, amount, category, grp, source_file) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            tx[["date", "description", "amount", "category", "grp", "source_file"]].itertuples(index=False),
        )
        after = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    return after - before


def load_transactions(db_path: Path = DB_PATH) -> pd.DataFrame:
    with connect(db_path) as conn:
        df = pd.read_sql_query("SELECT * FROM transactions ORDER BY date", conn, parse_dates=["date"])
    df["month"] = df["date"].dt.to_period("M")
    df["spend"] = (-df["amount"]).clip(lower=0)
    return df


def monthly_summary(month: str, db_path: Path = DB_PATH) -> pd.DataFrame:
    query = """
        SELECT category, grp AS "group", COUNT(*) AS transactions, ROUND(-SUM(amount), 2) AS spent
        FROM transactions
        WHERE strftime('%Y-%m', date) = ? AND amount < 0 AND grp NOT IN ('Transfer')
        GROUP BY category, grp
        ORDER BY spent DESC
    """
    with connect(db_path) as conn:
        return pd.read_sql_query(query, conn, params=(month,))


def budget_report(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Suggested monthly budget per category.

    Regular categories use the median month, so one-off spikes don't inflate the budget.
    Lumpy categories (spent in only a few months, like textbooks or travel) get a
    "sinking fund": the yearly total spread evenly across 12 months.
    """
    df = load_transactions(db_path)
    spend = df[(df["grp"].isin(["Essential", "Discretionary"]))]
    monthly = spend.pivot_table(index="month", columns="category", values="spend", aggfunc="sum", fill_value=0)
    report = pd.DataFrame({
        "avg_month": monthly.mean(),
        "median_month": monthly.median(),
        "max_month": monthly.max(),
    }).round(0).sort_values("avg_month", ascending=False)
    lumpy = report["median_month"] == 0
    report["budget_type"] = lumpy.map({True: "sinking fund", False: "monthly"})
    report["suggested_budget"] = (report["median_month"].where(~lumpy, report["avg_month"]) / 5).round() * 5
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal expense tracker")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_import = sub.add_parser("import", help="import a bank CSV export")
    p_import.add_argument("csv", type=Path)
    p_summary = sub.add_parser("summary", help="spending by category for one month")
    p_summary.add_argument("--month", required=True, help="YYYY-MM")
    sub.add_parser("uncategorized", help="list transactions no rule matched")
    sub.add_parser("budget", help="suggested monthly budget per category")
    args = parser.parse_args()

    pd.set_option("display.width", 120)
    if args.cmd == "import":
        print(f"Imported {import_csv(args.csv)} new transactions from {args.csv.name}")
    elif args.cmd == "summary":
        s = monthly_summary(args.month)
        print(s.to_string(index=False))
        print(f"\nTotal spent in {args.month}: ${s['spent'].sum():,.2f}")
    elif args.cmd == "uncategorized":
        df = load_transactions()
        print(df[df["category"] == "Uncategorized"][["date", "description", "amount"]].to_string(index=False))
    elif args.cmd == "budget":
        print(budget_report().to_string())


if __name__ == "__main__":
    main()
