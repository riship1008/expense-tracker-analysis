"""Analysis helpers: month-over-month flags and forecast backtesting."""

import numpy as np
import pandas as pd


def flag_increases(monthly: pd.DataFrame, min_pct: float = 0.30, min_amount: float = 1000) -> pd.DataFrame:
    """Months where a category rose by at least min_pct AND min_amount vs. the previous month.

    Requiring both avoids flagging tiny categories (a fee going from 15 to 30 is +100%
    but doesn't matter) and normal swings in large categories.
    """
    prev = monthly.shift(1)
    long = pd.DataFrame({
        "previous": prev.stack(),
        "current": monthly.stack(),
    }).dropna(subset=["previous"]).reset_index()
    long.columns = ["month", "category", "previous", "current"]
    long["change"] = long["current"] - long["previous"]
    long["pct_change"] = long["change"] / long["previous"].replace(0, np.nan)
    keep = (long["change"] >= min_amount) & ((long["pct_change"] >= min_pct) | long["previous"].eq(0))
    out = long[keep]
    return out.sort_values("change", ascending=False).reset_index(drop=True)


def backtest(series: pd.Series, methods: dict, start: int) -> pd.DataFrame:
    """Rolling-origin backtest: forecast each month t using only months before t."""
    rows = []
    for t in range(start, len(series)):
        history, actual = series.iloc[:t], series.iloc[t]
        for name, fn in methods.items():
            rows.append({"month": series.index[t], "method": name, "forecast": float(fn(history)),
                         "actual": float(actual)})
    out = pd.DataFrame(rows)
    out["abs_error"] = (out["forecast"] - out["actual"]).abs()
    out["abs_pct_error"] = out["abs_error"] / out["actual"]
    return out
