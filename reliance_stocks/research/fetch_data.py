"""
DATA LAYER  ·  bulk historical download and local cache

Pulls 10 years of daily OHLCV for the target, its sector peers, Indian index and
volatility context, and the global/macro series that are already known by the
time NSE opens at 09:15 IST.

Everything is cached to research/data/<safe_ticker>.csv so downstream feature
work never re-hits the network.

Run:  python fetch_data.py
"""

import os
import sys
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import console_setup  # noqa: F401  — must precede any print()

import yfinance as yf

warnings.filterwarnings("ignore")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
YEARS    = "10y"

# ── UNIVERSE ──────────────────────────────────────────────────────────────────
# Grouped by the role each series plays in the feature set. The `lag` note marks
# series whose same-day value is NOT known at 09:15 IST and must be shifted.
UNIVERSE = {
    # target
    "RELIANCE.NS":   "target",

    # Indian index / volatility context — same-day OPEN is known at 09:15
    "^NSEI":         "index",
    "^NSEBANK":      "index",
    "^INDIAVIX":     "index",

    # sector peers: O2C refining complex + telecom (Jio read-across)
    "ONGC.NS":       "peer",
    "IOC.NS":        "peer",
    "BPCL.NS":       "peer",
    "BHARTIARTL.NS": "peer",

    # large-cap cross-section — market-wide breadth signal
    "TCS.NS":        "peer",
    "HDFCBANK.NS":   "peer",
    "INFY.NS":       "peer",
    "ICICIBANK.NS":  "peer",

    # commodities — RELIANCE is a refiner, so crude is a direct input cost
    "BZ=F":          "macro",
    "CL=F":          "macro",
    "GC=F":          "macro",

    # FX and rates
    "USDINR=X":      "macro",
    "DX-Y.NYB":      "macro",
    "^TNX":          "macro",

    # global risk — the US session CLOSES before India opens, so the previous
    # US close is genuinely known information at 09:15 IST
    "^GSPC":         "global",
    "^IXIC":         "global",
    "^VIX":          "global",
}


def safe_name(ticker: str) -> str:
    """Filesystem-safe filename for a ticker symbol."""
    return ticker.replace("^", "IDX_").replace("=", "_").replace(".", "_").replace("-", "_")


def fetch(ticker: str, retries: int = 3):
    """Download one ticker with retry, flattening yfinance's MultiIndex columns."""
    for attempt in range(1, retries + 1):
        try:
            df = yf.download(
                ticker, period=YEARS, interval="1d",
                progress=False, auto_adjust=False, threads=False,
            )
            if df is not None and not df.empty:
                # yfinance returns MultiIndex (field, ticker) even for one symbol
                if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                    df.columns = df.columns.get_level_values(0)
                df.index.name = "Date"
                return df
        except Exception as exc:
            print(f"    attempt {attempt} failed: {str(exc)[:70]}")
        if attempt < retries:
            time.sleep(2 * attempt)
    return None


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"Cache directory: {DATA_DIR}")
    print(f"Universe: {len(UNIVERSE)} tickers  ·  period: {YEARS}\n")

    ok, failed = 0, []
    for ticker, role in UNIVERSE.items():
        path = os.path.join(DATA_DIR, f"{safe_name(ticker)}.csv")
        df   = fetch(ticker)
        if df is None:
            print(f"  {ticker:14} {role:7} FAILED")
            failed.append(ticker)
            continue
        df.to_csv(path)
        print(f"  {ticker:14} {role:7} {len(df):>5} rows  "
              f"{df.index[0].date()} .. {df.index[-1].date()}")
        ok += 1

    print(f"\nCached {ok}/{len(UNIVERSE)} tickers.")
    if failed:
        print(f"Failed: {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
