"""Download the Berka (PKDD'99) Czech bank dataset into data/raw/.

The dataset contains real, anonymized transactions from a Czech bank (1993-1998),
released for the PKDD'99 Discovery Challenge. Source mirror:
https://github.com/jlacko/berka-dataset

    python src/download_data.py
"""

from pathlib import Path
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BASE = "https://raw.githubusercontent.com/jlacko/berka-dataset/master/"
FILES = ["trans.asc", "account.asc", "district.asc", "loan.asc", "order.asc"]


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        dest = RAW / name
        if dest.exists():
            print(f"already have {name}")
            continue
        print(f"downloading {name} ...")
        urlretrieve(BASE + name, dest)
    print(f"done -> {RAW.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
