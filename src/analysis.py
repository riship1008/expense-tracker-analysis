"""Analysis helpers: recurring charges, month-over-month flags, forecasting, savings scenarios."""

import numpy as np
import pandas as pd

SPEND_GROUPS = ["Essential", "Discretionary"]


def monthly_by_category(df: pd.DataFrame) -> pd.DataFrame:
    spend = df[df["grp"].isin(SPEND_GROUPS)]
    return spend.pivot_table(index="month", columns="category", values="spend", aggfunc="sum", fill_value=0)


def flag_increases(monthly: pd.DataFrame, min_pct: float = 0.30, min_dollars: float = 40) -> pd.DataFrame:
    """Months where a category jumped by at least min_pct AND min_dollars vs. the previous month.

    Requiring both avoids flagging tiny categories ($5 -> $10 is +100% but doesn't matter)
    and big-but-normal categories (a $20 change on a $400 base).
    """
    prev = monthly.shift(1)
    change = monthly - prev
    pct = change / prev.replace(0, np.nan)
    flags = (change >= min_dollars) & ((pct >= min_pct) | prev.eq(0))
    out = (
        pd.DataFrame({"previous": prev[flags].stack(), "current": monthly[flags].stack(),
                      "change": change[flags].stack(), "pct_change": pct[flags].stack()})
        .reset_index()
        .rename(columns={"level_1": "category"})
        .sort_values("change", ascending=False)
    )
    return out


def detect_recurring(df: pd.DataFrame, min_months: int = 3, max_amount_cv: float = 0.05) -> pd.DataFrame:
    """Find subscription-like charges: same merchant, roughly monthly, nearly the same amount."""
    spend = df[df["amount"] < 0].copy()
    spend["merchant"] = spend["description"].str.replace(r"[\d#*]+.*$", "", regex=True).str.strip()
    rows = []
    for merchant, g in spend.groupby("merchant"):
        g = g.sort_values("date")
        if g["month"].nunique() < min_months:
            continue
        gaps = g["date"].diff().dt.days.dropna()
        amount_cv = g["spend"].std() / g["spend"].mean()
        if gaps.between(25, 35).mean() >= 0.8 and amount_cv <= max_amount_cv:
            last = g["date"].max()
            rows.append({
                "merchant": merchant,
                "category": g["category"].mode()[0],
                "monthly_cost": round(g["spend"].median(), 2),
                "months_charged": g["month"].nunique(),
                "first_charge": g["date"].min().date(),
                "last_charge": last.date(),
                "active": (df["date"].max() - last).days <= 35,
            })
    out = pd.DataFrame(rows).sort_values("monthly_cost", ascending=False).reset_index(drop=True)
    out["annual_cost"] = (out["monthly_cost"] * 12).round(2)
    return out


def backtest(series: pd.Series, methods: dict, start: int = 6) -> pd.DataFrame:
    """Rolling-origin backtest: forecast month t using only months before t."""
    rows = []
    for t in range(start, len(series)):
        history, actual = series.iloc[:t], series.iloc[t]
        for name, fn in methods.items():
            rows.append({"month": series.index[t], "method": name, "forecast": fn(history), "actual": actual})
    out = pd.DataFrame(rows)
    out["abs_error"] = (out["forecast"] - out["actual"]).abs()
    return out
