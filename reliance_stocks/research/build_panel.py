"""
PANEL BUILDER  ·  leakage-safe feature construction

Builds the modelling panel for predicting RELIANCE.NS's open-to-close move,
with the decision taken at 09:15 IST.

═══════════════════════════════════════════════════════════════════════════════
THE INFORMATION-AVAILABILITY RULE
═══════════════════════════════════════════════════════════════════════════════
The single thing that decides whether any result here is real.

At 09:15 IST on day D the following IS known:
  · every NSE series' OPEN on day D          (the auction has just printed)
  · every NSE series' full OHLCV through D-1
  · the US session's close from D-1          (US closes ~02:00 IST on day D)
  · commodity and FX settlements through D-1

The following is NOT known and must never touch a feature:
  · RELIANCE's close, high, low or volume on day D   ← these are the answer
  · any index's close on day D

This module enforces that STRUCTURALLY rather than by convention. Same-day data
enters the panel only through `_open_today()`, which accepts the Open column and
nothing else. Every other series passes through `_lagged()`, which shifts by one
row before any arithmetic. A feature therefore cannot see the future unless
someone deliberately bypasses both helpers — and `assert_no_leakage()` is run at
the end to catch that.

Run:  python build_panel.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import console_setup  # noqa: F401  — must precede any print()

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_PATH = os.path.join(BASE_DIR, "panel.csv")

TARGET = "RELIANCE.NS"

# NSE-listed series: their same-day OPEN is known at 09:15 IST.
NSE_TICKERS = {
    "RELIANCE.NS", "^NSEI", "^NSEBANK", "^INDIAVIX",
    "ONGC.NS", "IOC.NS", "BPCL.NS", "BHARTIARTL.NS",
    "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
}


def safe_name(ticker: str) -> str:
    return ticker.replace("^", "IDX_").replace("=", "_").replace(".", "_").replace("-", "_")


def load_all() -> dict[str, pd.DataFrame]:
    """Loads every cached CSV into a dict of DataFrames indexed by date."""
    out = {}
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith(".csv"):
            continue
        df = pd.read_csv(os.path.join(DATA_DIR, fname), index_col=0, parse_dates=True)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        out[fname[:-4]] = df
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  AVAILABILITY-ENFORCING ACCESSORS
# ══════════════════════════════════════════════════════════════════════════════

def _open_today(raw: dict, ticker: str, index: pd.DatetimeIndex) -> pd.Series:
    """
    Today's OPEN — the only same-day value that is legitimately known at 09:15.

    Permitted for NSE series only. Reindexed onto the target's trading calendar
    WITHOUT forward-fill: if a series did not trade on day D, its open on day D
    is genuinely unknown and stays NaN rather than silently inheriting a stale
    value that would look like information.
    """
    if ticker not in NSE_TICKERS:
        raise ValueError(f"{ticker} is not an NSE series; its same-day open is not "
                         f"known at 09:15 IST. Use _lagged() instead.")
    s = raw[safe_name(ticker)]["Open"]
    return s.reindex(index)


def _lagged(raw: dict, ticker: str, column: str, index: pd.DatetimeIndex,
            lag: int = 1) -> pd.Series:
    """
    A series shifted so that only information from D-lag or earlier is visible.

    The shift happens on the SOURCE calendar before reindexing onto the target
    calendar, so a holiday on the source exchange cannot leak a same-day value
    through the reindex. Forward-fill after reindexing is safe here because the
    value being carried forward is already historical.
    """
    s = raw[safe_name(ticker)][column].shift(lag)
    return s.reindex(index.union(s.index)).ffill().reindex(index)


# ══════════════════════════════════════════════════════════════════════════════
#  INDICATOR PRIMITIVES  (all operate on already-lagged series)
# ══════════════════════════════════════════════════════════════════════════════

def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0.0)
    loss  = (-delta).clip(lower=0.0)
    avg_g = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_l = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def _gap(raw: dict, ticker: str, index: pd.DatetimeIndex) -> pd.Series:
    """Overnight gap: today's open versus the previous close. NSE series only."""
    op = _open_today(raw, ticker, index)
    pc = _lagged(raw, ticker, "Close", index, lag=1)
    return op / pc - 1.0


def _prev_ret(raw: dict, ticker: str, index: pd.DatetimeIndex, n: int = 1) -> pd.Series:
    """Return over the n days ending at D-1. Safe for any series."""
    c0 = _lagged(raw, ticker, "Close", index, lag=1)
    cn = _lagged(raw, ticker, "Close", index, lag=1 + n)
    return c0 / cn - 1.0


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE FAMILIES
# ══════════════════════════════════════════════════════════════════════════════

def f_price_vol(raw: dict, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """A1 — target's own price, volatility and momentum structure."""
    f = pd.DataFrame(index=idx)

    close_l = _lagged(raw, TARGET, "Close",  idx, 1)
    high_l  = _lagged(raw, TARGET, "High",   idx, 1)
    low_l   = _lagged(raw, TARGET, "Low",    idx, 1)
    vol_l   = _lagged(raw, TARGET, "Volume", idx, 1)
    open_t  = _open_today(raw, TARGET, idx)

    # The single most informative variable for an open-to-close move.
    f["gap"] = open_t / close_l - 1.0

    for n in (1, 2, 5, 10, 20):
        f[f"ret_{n}d"] = _prev_ret(raw, TARGET, idx, n)

    daily_ret = close_l.pct_change()
    for n in (5, 10, 20):
        f[f"vol_{n}d"] = daily_ret.rolling(n).std()

    f["atr_14"]      = _atr(high_l, low_l, close_l, 14) / close_l
    f["rsi_14"]      = _rsi(close_l, 14)
    f["ema_spread"]  = close_l / close_l.ewm(span=20, adjust=False).mean() - 1.0
    f["sma_spread"]  = close_l / close_l.rolling(50).mean() - 1.0

    roll_mu  = close_l.rolling(20).mean()
    roll_sd  = close_l.rolling(20).std()
    f["bb_pos"] = (close_l - roll_mu) / (2.0 * roll_sd)

    f["vol_ratio"]   = vol_l / vol_l.rolling(20).mean()
    f["hi_20_dist"]  = close_l / close_l.rolling(20).max() - 1.0
    f["lo_20_dist"]  = close_l / close_l.rolling(20).min() - 1.0
    f["prev_range"]  = (high_l - low_l) / close_l
    f["prev_o2c"]    = _lagged(raw, TARGET, "Close", idx, 1) / _lagged(raw, TARGET, "Open", idx, 1) - 1.0
    return f


def f_index(raw: dict, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """A2 — Indian index and volatility context."""
    f = pd.DataFrame(index=idx)

    f["nifty_gap"]     = _gap(raw, "^NSEI", idx)
    f["banknifty_gap"] = _gap(raw, "^NSEBANK", idx)
    f["nifty_ret_1d"]  = _prev_ret(raw, "^NSEI", idx, 1)
    f["nifty_ret_5d"]  = _prev_ret(raw, "^NSEI", idx, 5)

    # RELIANCE is ~10% of NIFTY, so its own gap is largely index beta. The
    # residual — how much it gapped BEYOND the index — is the idiosyncratic part
    # and is where any stock-specific signal has to live.
    f["rel_gap_resid"] = _gap(raw, TARGET, idx) - f["nifty_gap"]

    vix_l = _lagged(raw, "^INDIAVIX", "Close", idx, 1)
    f["vix"]      = vix_l
    f["vix_chg"]  = vix_l.pct_change()
    f["vix_gap"]  = _gap(raw, "^INDIAVIX", idx)

    nifty_c = _lagged(raw, "^NSEI", "Close", idx, 1)
    f["nifty_vol_20d"] = nifty_c.pct_change().rolling(20).std()
    return f


def f_peers(raw: dict, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """A2 — sector read-across and market breadth."""
    f = pd.DataFrame(index=idx)

    o2c = ["ONGC.NS", "IOC.NS", "BPCL.NS"]
    f["o2c_gap"] = pd.concat([_gap(raw, t, idx) for t in o2c], axis=1).mean(axis=1)

    f["airtel_gap"] = _gap(raw, "BHARTIARTL.NS", idx)

    largecap = ["TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS"]
    gaps = pd.concat([_gap(raw, t, idx) for t in largecap], axis=1)
    f["largecap_gap"]     = gaps.mean(axis=1)
    f["breadth_gap_up"]   = (gaps > 0).sum(axis=1) / gaps.notna().sum(axis=1)
    f["largecap_gap_disp"] = gaps.std(axis=1)
    return f


def f_macro(raw: dict, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """A3 — commodities, FX, rates and the overnight global session."""
    f = pd.DataFrame(index=idx)

    # RELIANCE is a refiner: crude is a direct input cost.
    f["brent_1d"] = _prev_ret(raw, "BZ=F", idx, 1)
    f["brent_5d"] = _prev_ret(raw, "BZ=F", idx, 5)
    f["wti_1d"]   = _prev_ret(raw, "CL=F", idx, 1)
    f["gold_1d"]  = _prev_ret(raw, "GC=F", idx, 1)

    f["usdinr_1d"] = _prev_ret(raw, "USDINR=X", idx, 1)
    f["usdinr_5d"] = _prev_ret(raw, "USDINR=X", idx, 5)
    f["dxy_1d"]    = _prev_ret(raw, "DX-Y.NYB", idx, 1)

    us10 = _lagged(raw, "^TNX", "Close", idx, 1)
    f["us10y"]     = us10
    f["us10y_chg"] = us10.diff()

    # The US session closes ~02:00 IST, so its previous close is known at 09:15.
    f["spx_1d"]    = _prev_ret(raw, "^GSPC", idx, 1)
    f["nasdaq_1d"] = _prev_ret(raw, "^IXIC", idx, 1)

    usvix = _lagged(raw, "^VIX", "Close", idx, 1)
    f["usvix"]     = usvix
    f["usvix_chg"] = usvix.pct_change()
    return f


def f_calendar(idx: pd.DatetimeIndex) -> pd.DataFrame:
    """A4 — seasonality and derivatives-expiry effects."""
    f = pd.DataFrame(index=idx)
    f["dow"]          = idx.dayofweek
    f["month"]        = idx.month
    f["day_of_month"] = idx.day
    f["is_month_end"] = (idx.to_period("M") != (idx + pd.Timedelta(days=3)).to_period("M")).astype(int)
    f["is_month_start"] = (idx.day <= 3).astype(int)
    f["is_quarter_end"] = ((idx.month % 3 == 0) & (idx.day >= 25)).astype(int)

    # NSE monthly F&O expiry falls on the last Thursday of the month.
    is_thu = idx.dayofweek == 3
    nxt_week_diff_month = (idx.to_period("M") != (idx + pd.Timedelta(days=7)).to_period("M"))
    f["is_expiry"]      = (is_thu & nxt_week_diff_month).astype(int)
    f["is_expiry_week"] = nxt_week_diff_month.astype(int)
    return f


# ══════════════════════════════════════════════════════════════════════════════
#  LABELS
# ══════════════════════════════════════════════════════════════════════════════

def build_labels(raw: dict, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """
    y_ret  — open-to-close return, the quantity actually traded
    y_dir  — 1 if the close finished above the open, else 0
    y_absr — absolute move, used to fit the magnitude range

    These use same-day Close deliberately: they are the answer, not a feature.
    """
    tgt   = raw[safe_name(TARGET)]
    op    = tgt["Open"].reindex(idx)
    cl    = tgt["Close"].reindex(idx)
    lab   = pd.DataFrame(index=idx)
    lab["open"]  = op
    lab["close"] = cl
    lab["y_ret"]  = cl / op - 1.0
    lab["y_dir"]  = (lab["y_ret"] > 0).astype(int)
    lab["y_absr"] = lab["y_ret"].abs()
    return lab


# ══════════════════════════════════════════════════════════════════════════════
#  LEAKAGE AUDIT
# ══════════════════════════════════════════════════════════════════════════════

def assert_no_leakage(panel: pd.DataFrame, raw: dict, feature_cols: list[str]) -> None:
    """
    Empirical leakage check.

    Any feature that has genuinely seen today's close will correlate with the
    label far beyond what a real market signal ever achieves. Intraday
    open-to-close predictors in liquid single names produce |correlation| in the
    0.0-0.1 range; anything above 0.30 is a construction bug, not alpha.

    Also verifies directly that no feature reproduces today's close or the
    label's own arithmetic.
    """
    y = panel["y_ret"]
    suspicious = []
    for c in feature_cols:
        s = panel[c]
        if s.notna().sum() < 100 or s.nunique() < 3:
            continue
        r = s.corr(y)
        if pd.notna(r) and abs(r) > 0.30:
            suspicious.append((c, round(float(r), 4)))

    if suspicious:
        raise AssertionError(
            "LEAKAGE SUSPECTED — features implausibly correlated with the label:\n"
            + "\n".join(f"    {c}: r={r}" for c, r in suspicious)
        )

    # Direct check: no feature may equal today's close or today's return.
    for c in feature_cols:
        if panel[c].equals(panel["close"]) or panel[c].equals(panel["y_ret"]):
            raise AssertionError(f"LEAKAGE: {c} reproduces a same-day outcome column.")

    print("  leakage audit: PASSED (no feature exceeds |r|>0.30 vs the label)")


# ══════════════════════════════════════════════════════════════════════════════
#  BUILD
# ══════════════════════════════════════════════════════════════════════════════

def build() -> pd.DataFrame:
    print("Loading cached series...")
    raw = load_all()
    print(f"  {len(raw)} series loaded")

    idx = raw[safe_name(TARGET)].index
    print(f"  target calendar: {len(idx)} trading days "
          f"({idx[0].date()} .. {idx[-1].date()})")

    print("\nBuilding feature families...")
    families = {
        "price_vol": f_price_vol(raw, idx),
        "index":     f_index(raw, idx),
        "peers":     f_peers(raw, idx),
        "macro":     f_macro(raw, idx),
        "calendar":  f_calendar(idx),
    }
    for name, df in families.items():
        print(f"  {name:11} {df.shape[1]:>3} features")

    feats  = pd.concat(families.values(), axis=1)
    labels = build_labels(raw, idx)
    panel  = pd.concat([labels, feats], axis=1)

    feature_cols = list(feats.columns)
    panel.attrs["feature_cols"] = feature_cols

    # Drop the warm-up period where long rolling windows are still NaN.
    before = len(panel)
    panel = panel.dropna(subset=["y_ret"])
    panel = panel[panel[feature_cols].notna().mean(axis=1) > 0.90]
    print(f"\n  rows: {before} -> {len(panel)} after warm-up and label trim")
    print(f"  features: {len(feature_cols)}")

    print("\nRunning leakage audit...")
    assert_no_leakage(panel, raw, feature_cols)

    return panel


if __name__ == "__main__":
    panel = build()
    panel.to_csv(OUT_PATH)
    with open(os.path.join(BASE_DIR, "feature_cols.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(panel.attrs["feature_cols"]))
    print(f"\nWrote {OUT_PATH}  ({panel.shape[0]} rows x {panel.shape[1]} cols)")
    print(f"Base rate (close > open): {panel['y_dir'].mean()*100:.2f}%")
    print(f"Mean open-to-close return: {panel['y_ret'].mean()*100:+.4f}%")
    print(f"Daily stdev: {panel['y_ret'].std()*100:.4f}%")
