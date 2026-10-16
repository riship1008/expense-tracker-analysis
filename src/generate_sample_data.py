"""Generate 12 months of realistic sample bank transactions for a college student.

The output mimics a real bank CSV export (Chase-style columns and messy merchant
descriptions) so the tracker is tested against the same format it will see with
real data. Spending levels are based on typical college-student budgets: a
part-time job, living at home during breaks, commuting by car, food delivery
spikes around exams, textbooks at the start of each semester, and holiday gifts.

    python src/generate_sample_data.py
"""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sample" / "sample_bank_export.csv"
START, END = date(2025, 10, 1), date(2026, 9, 30)
rng = np.random.default_rng(1008)

EXAM_WEEKS = [(date(2025, 12, 8), date(2025, 12, 19)), (date(2026, 5, 4), date(2026, 5, 15))]
SEMESTER_STARTS = [date(2026, 1, 26), date(2026, 8, 31)]
SUMMER = (date(2026, 5, 20), date(2026, 8, 25))
WINTER_BREAK = (date(2025, 12, 20), date(2026, 1, 25))
SPRING_BREAK = (date(2026, 3, 14), date(2026, 3, 22))


def in_ranges(d, ranges):
    return any(a <= d <= b for a, b in ranges)


def days():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=1)


def money(x):
    return round(float(x), 2)


def generate() -> pd.DataFrame:
    tx = []
    next_fillup, next_grocery = START, START + timedelta(days=2)

    def add(d, desc, amount, kind="Sale"):
        tx.append({"Transaction Date": d, "Description": desc, "Amount": money(amount), "Type": kind})

    for d in days():
        dow, summer = d.weekday(), in_ranges(d, [SUMMER])
        exams = in_ranges(d, EXAM_WEEKS)
        break_time = in_ranges(d, [WINTER_BREAK, SPRING_BREAK])

        # Income: biweekly paycheck from the part-time job (more hours in summer)
        if dow == 4 and ((d - date(2025, 10, 3)).days % 14 == 0):
            hours = rng.normal(34 if summer else 22, 3)
            add(d, "D&L LIQUORS PAYROLL PPD ID: 1520384756", hours * 14.25 * 0.88, "ACH_CREDIT")
        if d.month == 6 and d.day == 15:
            add(d, "NNDYM CAMP MD DIRECT DEP", rng.normal(1150, 40), "ACH_CREDIT")

        # Fixed monthly bills and subscriptions
        if d.day == 3:
            add(d, "VERIZON WIRELESS PAYMENTS", -rng.normal(52, 1.5))
        if d.day == 7:
            add(d, "SPOTIFY USA", -6.29)
        if d.day == 12:
            add(d, "NETFLIX.COM", -7.99)
        if d.day == 18 and d >= date(2026, 2, 18):
            add(d, "PLANET FITNESS CLUB FEE", -15.00)
        if d.day == 21:
            add(d, "APPLE.COM/BILL ICLOUD 50GB", -0.99)
        if d.day == 25 and d < date(2026, 7, 1):
            add(d, "HULU 877-8244858 CA", -9.99)  # cancelled in July
        if d.day == 27:
            add(d, "GEICO *AUTO", -rng.normal(118, 2))

        # Gas: a fill-up every ~6 days while commuting to College Park, ~9 days otherwise
        if d >= next_fillup:
            add(d, rng.choice(["WAWA 8234", "SHELL OIL 57442", "EXXONMOBIL 4471", "ROYAL FARMS #187"]),
                -rng.normal(42, 5))
            next_fillup = d + timedelta(days=int(rng.integers(8, 11) if summer or break_time else rng.integers(5, 8)))

        # Groceries: roughly once every week and a half
        if d >= next_grocery:
            add(d, rng.choice(["GIANT FOOD #318", "WEIS MARKETS 0127", "TRADER JOE S #658", "WM SUPERCENTER #1817"]),
                -abs(rng.normal(30, 9)))
            next_grocery = d + timedelta(days=int(rng.integers(7, 14)))

        # Dining out (more on weekends)
        if rng.random() < (0.22 if dow >= 4 else 0.13):
            place = rng.choice(["CHIPOTLE 2873", "SQ *BOBA TEA HOUSE", "TST* NANDOS PERI PERI", "CHICK-FIL-A #03712",
                                "SWEETGREEN COLLEGE PK", "SQ *SHAWARMA SPOT", "STARBUCKS STORE 18823",
                                "TST* ROYAL INDIA RESTAU", "MCDONALD'S F19284", "QDOBA MEXICAN EATS"])
            amt = abs(rng.normal(7, 2)) if "STARBUCKS" in place or "BOBA" in place else abs(rng.normal(15, 5))
            add(d, place, -amt)

        # Food delivery: spikes during exam weeks and late semester
        p_delivery = 0.30 if exams else (0.05 if summer else 0.10)
        if rng.random() < p_delivery:
            add(d, rng.choice(["UBER *EATS PENDING", "DOORDASH*DASHPASS", "DD *DOORDASH CHIPOTLE", "GRUBHUB*TERRAPIN"]),
                -abs(rng.normal(27, 7)))

        # Rideshare on weekends
        if dow in (4, 5) and rng.random() < 0.18:
            add(d, rng.choice(["UBER *TRIP", "LYFT *RIDE SAT 11PM"]), -abs(rng.normal(19, 7)))

        # Shopping
        if rng.random() < 0.06:
            add(d, rng.choice(["AMAZON MKTPL*2K7HN3", "Amazon.com*RT4B81", "TARGET 00011234", "NIKE.COM", "ZARA USA 3301"]),
                -abs(rng.normal(38, 22)))

        # Entertainment
        if dow >= 4 and rng.random() < 0.05:
            add(d, rng.choice(["AMC 0445 ONLINE", "TICKETMASTER", "DAVE & BUSTERS ARUNDEL", "STEAM PURCHASE"]),
                -abs(rng.normal(26, 10)))

        # Money sent to friends (splitting bills)
        if rng.random() < 0.05:
            add(d, "VENMO PAYMENT 1038472", -abs(rng.normal(22, 12)))
        if rng.random() < 0.025:
            add(d, "VENMO CASHOUT", abs(rng.normal(25, 10)), "ACH_CREDIT")

    # One-off and seasonal expenses
    for s in SEMESTER_STARTS:
        add(s, "UMD BOOK CENTER", -rng.normal(185, 30))
        add(s + timedelta(days=3), "CHEGG ORDER", -19.95)
        add(s + timedelta(days=6), "AMAZON MKTPL*TEXTBOOK", -rng.normal(74, 10))
    add(date(2026, 1, 15), "UMD TERM PARKING PERMIT", -342.00)
    add(date(2026, 8, 20), "UMD TERM PARKING PERMIT", -342.00)
    for d, amt in [(date(2025, 12, 14), 64), (date(2025, 12, 18), 92), (date(2025, 12, 20), 48)]:
        add(d, "Amazon.com*GIFT", -amt)
    add(date(2025, 12, 21), "TARGET 00011234", -71.40)
    add(date(2026, 3, 13), "SPIRIT AIRL 4872619", -186.40)
    add(date(2026, 3, 16), "AIRBNB * HMQ8K2", -212.00)
    add(date(2026, 4, 9), "JIFFY LUBE #1928", -79.99)
    add(date(2026, 7, 2), "TIRE KINGDOM 422", -412.00)

    df = pd.DataFrame(tx).sort_values("Transaction Date").reset_index(drop=True)
    df["Post Date"] = [d + timedelta(days=int(rng.integers(0, 3))) for d in df["Transaction Date"]]
    df["Category"] = ""  # most bank exports leave this blank or use their own labels
    return df[["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount"]]


if __name__ == "__main__":
    df = generate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False, date_format="%m/%d/%Y")
    print(f"Wrote {len(df):,} transactions to {OUT.relative_to(ROOT)}")
