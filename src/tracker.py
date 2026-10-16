"""Expense tracker for real bank transactions (Berka Czech bank dataset).

Loads the raw bank export, translates the Czech transaction codes, categorizes
every transaction with rules from config/categories.json, and stores the result
in SQLite so any account can be summarized by month and category.

Usage:
    python src/download_data.py                     # one-time download
    python src/tracker.py build                     # 500-account sample -> data/bank.db
    python src/tracker.py summary --account 2630 --year 1998
    python src/tracker.py flags --account 2630 --year 1998
    python src/tracker.py fees --year 1998
"""

import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "bank.db"
CONFIG = json.loads((ROOT / "config" / "categories.json").read_text())

# The analysis uses a random sample of accounts (fixed seed, so results are reproducible).
SAMPLE_ACCOUNTS = 500
SAMPLE_SEED = 42

# Approximate 1998 average exchange rate, used only to show amounts in USD for context.
CZK_PER_USD = 32.3


def load_raw() -> tuple[pd.DataFrame, pd.DataFrame]:
    tx = pd.read_csv(RAW / "trans.asc", sep=";", low_memory=False,
                     dtype={"type": str, "operation": str, "k_symbol": str, "bank": str, "account": str})
    accounts = pd.read_csv(RAW / "account.asc", sep=";")
    return tx, accounts


def categorize(tx: pd.DataFrame) -> pd.DataFrame:
    """Apply the first matching rule to every transaction (vectorized)."""
    category = pd.Series("Uncategorized", index=tx.index)
    group = pd.Series("Other", index=tx.index)
    unassigned = pd.Series(True, index=tx.index)
    for rule in CONFIG["rules"]:
        match = unassigned.copy()
        for field in ("type", "operation", "k_symbol"):
            if field in rule:
                match &= tx[field].str.strip().eq(rule[field])
        category[match] = rule["category"]
        group[match] = rule["group"]
        unassigned &= ~match
    return pd.DataFrame({"category": category, "grp": group})


def clean(tx: pd.DataFrame, accounts: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse dates, translate codes, sign amounts, and categorize."""
    tr = CONFIG["translations"]
    out = tx.copy()
    out["date"] = pd.to_datetime(out["date"].astype(str), format="%y%m%d")
    for col in ("type", "operation", "k_symbol"):
        out[col] = out[col].fillna("").str.strip()
    out = out.join(categorize(out))
    out["operation_en"] = out["operation"].map(tr["operation"]).fillna("")
    out["purpose_en"] = out["k_symbol"].map(tr["k_symbol"]).fillna("")
    # The raw file stores every amount as positive; money out gets a negative sign here.
    out["signed_amount"] = np.where(out["type"] == "PRIJEM", out["amount"], -out["amount"])
    out = out[["trans_id", "account_id", "date", "category", "grp", "operation_en", "purpose_en",
               "amount", "signed_amount", "balance"]]

    acc = accounts.rename(columns={"date": "opened"}).copy()
    acc["opened"] = pd.to_datetime(acc["opened"].astype(str), format="%y%m%d")
    acc["statement_frequency"] = acc["frequency"].map(tr["frequency"])
    return out, acc[["account_id", "district_id", "opened", "statement_frequency"]]


def build_database(n_accounts: int | None = SAMPLE_ACCOUNTS, db_path: Path = DB_PATH) -> tuple[int, int]:
    """Clean and categorize the raw data and store it in SQLite.

    n_accounts: size of the random account sample (None = all 4,500 accounts).
    """
    raw_tx, raw_accounts = load_raw()
    if n_accounts:
        keep = raw_accounts["account_id"].sample(n_accounts, random_state=SAMPLE_SEED)
        raw_accounts = raw_accounts[raw_accounts["account_id"].isin(keep)]
        raw_tx = raw_tx[raw_tx["account_id"].isin(keep)]
    tx, accounts = clean(raw_tx, raw_accounts)
    db_path.unlink(missing_ok=True)
    with sqlite3.connect(db_path) as conn:
        accounts.to_sql("accounts", conn, index=False)
        tx.assign(date=tx["date"].dt.strftime("%Y-%m-%d")).to_sql("transactions", conn, index=False, chunksize=50_000)
        conn.executescript("""
            CREATE INDEX idx_tx_account_date ON transactions(account_id, date);
            CREATE INDEX idx_tx_category ON transactions(category);
        """)
    return len(tx), len(accounts)


def query(sql: str, params: tuple = (), db_path: Path = DB_PATH) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def monthly_spending(account_id: int | None = None, year: int | None = None) -> pd.DataFrame:
    """Spending (money out) by month and category, for one account or the whole bank."""
    where, params = ["signed_amount < 0"], []
    if account_id is not None:
        where.append("account_id = ?"); params.append(account_id)
    if year is not None:
        where.append("strftime('%Y', date) = ?"); params.append(str(year))
    df = query(f"""
        SELECT strftime('%Y-%m', date) AS month, category, SUM(amount) AS spent
        FROM transactions WHERE {' AND '.join(where)}
        GROUP BY month, category
    """, tuple(params))
    return df.pivot_table(index="month", columns="category", values="spent", fill_value=0)


def main() -> None:
    p = argparse.ArgumentParser(description="Bank expense tracker")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="load raw data, categorize, and store in SQLite")
    b.add_argument("--accounts", type=int, default=SAMPLE_ACCOUNTS,
                   help=f"random sample size (default {SAMPLE_ACCOUNTS}; 0 = all 4,500)")
    for name in ("summary", "flags"):
        s = sub.add_parser(name)
        s.add_argument("--account", type=int, required=True)
        s.add_argument("--year", type=int, default=1998)
    f = sub.add_parser("fees", help="avoidable fees and penalty interest across all accounts")
    f.add_argument("--year", type=int, default=1998)
    args = p.parse_args()
    pd.set_option("display.width", 140)

    if args.cmd == "build":
        n_tx, n_acc = build_database(args.accounts or None)
        print(f"Stored {n_tx:,} transactions for {n_acc:,} accounts in {DB_PATH.relative_to(ROOT)}")
    elif args.cmd == "summary":
        m = monthly_spending(args.account, args.year).round(0)
        m["TOTAL"] = m.sum(axis=1)
        print(f"Account {args.account}, {args.year} spending by month (CZK)\n")
        print(m.to_string())
    elif args.cmd == "flags":
        from analysis import flag_increases
        m = monthly_spending(args.account, args.year)
        flags = flag_increases(m, min_pct=0.30, min_amount=1000)
        print(flags.round(0).to_string(index=False) if len(flags) else "No unusual month-over-month increases.")
    elif args.cmd == "fees":
        print(query("""
            SELECT category, COUNT(DISTINCT account_id) AS accounts, COUNT(*) AS charges,
                   ROUND(SUM(amount), 0) AS total_czk
            FROM transactions
            WHERE grp = 'Avoidable' AND strftime('%Y', date) = ?
            GROUP BY category
        """, (str(args.year),)).to_string(index=False))


if __name__ == "__main__":
    main()
