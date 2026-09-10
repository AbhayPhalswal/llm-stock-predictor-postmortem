"""
OVERNIGHT STRATEGY RESEARCH

The intraday study found the only strong signal in the data sits in the
overnight window: close[D] -> open[D+1] returns +12.67 bps/day at t=+7.55, while
the intraday open->close window returns -4.40 bps/day at t=-1.44.

A naive daily round trip cannot harvest that, because 250 round trips a year at
20 bps costs 50% a year. This module asks whether any *lower-turnover* variant
survives:

  1. Is the effect stable, or has it decayed?      (an anomaly that died is not a strategy)
  2. Is it concentrated in particular weekdays?    (Friday->Monday spans 3 calendar days per round trip)
  3. Can the good nights be selected in advance?   (fewer trades = proportionally less cost)
  4. What does 'buy and hold' cost by comparison?  (holding captures overnight AND intraday, with ~1 round trip)

═══════════════════════════════════════════════════════════════════════════════
INFORMATION AVAILABILITY  —  different from the intraday study
═══════════════════════════════════════════════════════════════════════════════
The overnight decision is taken at 15:30 IST, at the close of day D. At that
moment day D's FULL OHLCV is known — close, high, low and volume included. That
is a strictly richer information set than the 09:15 problem had.

The label is open[D+1] / close[D] - 1, which is strictly in the future of every
feature. Features use data through day D only; the label uses day D+1's open.

Run:  python overnight.py
"""

import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import console_setup  # noqa: F401  — must precede any print()

import numpy as np
import pandas as pd
from scipy import stats

from sklearn.ensemble      import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.linear_model  import LogisticRegression
from sklearn.impute        import SimpleImputer
from sklearn.pipeline      import Pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
TARGET   = "RELIANCE.NS"

TRAIN_MIN, TEST_SIZE, EMBARGO = 750, 125, 5


def safe_name(t: str) -> str:
    return t.replace("^", "IDX_").replace("=", "_").replace(".", "_").replace("-", "_")


def load(ticker: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(DATA_DIR, f"{safe_name(ticker)}.csv"),
                     index_col=0, parse_dates=True)
    return df[~df.index.duplicated(keep="last")].sort_index()


# ══════════════════════════════════════════════════════════════════════════════
#  PANEL
# ══════════════════════════════════════════════════════════════════════════════

def build_overnight_panel() -> tuple[pd.DataFrame, list[str]]:
    tgt = load(TARGET)
    idx = tgt.index

    o, h, l, c, v = (tgt["Open"], tgt["High"], tgt["Low"],
                     tgt["Close"], tgt["Volume"])

    p = pd.DataFrame(index=idx)
    p["close"] = c
    # LABEL: tomorrow's open versus tonight's close. Strictly future information.
    p["y_on"]  = c.shift(-1).pipe(lambda _: tgt["Open"].shift(-1)) / c - 1.0
    p["y_dir"] = (p["y_on"] > 0).astype(int)

    f = pd.DataFrame(index=idx)
    # Day D is fully observed at 15:30, so same-day OHLCV is legitimate here.
    f["o2c"]        = c / o - 1.0                      # today's intraday move
    f["range"]      = (h - l) / c
    f["close_pos"]  = (c - l) / (h - l).replace(0, np.nan)   # where in the day's range it closed
    f["gap_today"]  = o / c.shift(1) - 1.0
    f["vol_ratio"]  = v / v.rolling(20).mean()

    ret = c.pct_change()
    for n in (1, 2, 5, 10, 20):
        f[f"ret_{n}d"] = c / c.shift(n) - 1.0
    for n in (5, 10, 20):
        f[f"vol_{n}d"] = ret.rolling(n).std()

    f["ema_spread"] = c / c.ewm(span=20, adjust=False).mean() - 1.0
    f["hi20"]       = c / c.rolling(20).max() - 1.0
    f["lo20"]       = c / c.rolling(20).min() - 1.0

    # index / macro context, all observed by the Indian close
    nifty = load("^NSEI")["Close"].reindex(idx).ffill()
    f["nifty_o2c"] = (nifty / load("^NSEI")["Open"].reindex(idx) - 1.0)
    f["nifty_1d"]  = nifty.pct_change()
    vix = load("^INDIAVIX")["Close"].reindex(idx).ffill()
    f["vix"]       = vix
    f["vix_chg"]   = vix.pct_change()

    # US session of day D-1 closed at ~02:00 IST on day D, so it is known.
    for tk, name in [("^GSPC", "spx"), ("^VIX", "usvix")]:
        s = load(tk)["Close"]
        s = s.reindex(idx.union(s.index)).ffill().reindex(idx)
        f[f"{name}_1d"] = s.pct_change()

    brent = load("BZ=F")["Close"]
    brent = brent.reindex(idx.union(brent.index)).ffill().reindex(idx)
    f["brent_1d"] = brent.pct_change()

    f["dow"] = idx.dayofweek

    panel = pd.concat([p, f], axis=1).dropna(subset=["y_on"])
    cols  = list(f.columns)
    panel = panel[panel[cols].notna().mean(axis=1) > 0.9]

    # Leakage guard: no feature may correlate implausibly with the label.
    for cname in cols:
        s = panel[cname]
        if s.notna().sum() < 200 or s.nunique() < 3:
            continue
        r = s.corr(panel["y_on"])
        if pd.notna(r) and abs(r) > 0.30:
            raise AssertionError(f"LEAKAGE SUSPECTED: {cname} r={r:.3f}")
    return panel, cols


# ══════════════════════════════════════════════════════════════════════════════
#  ANALYSES
# ══════════════════════════════════════════════════════════════════════════════

def stability(panel: pd.DataFrame) -> None:
    print("=" * 78)
    print("1. IS THE OVERNIGHT EFFECT STABLE, OR HAS IT DECAYED?")
    print("=" * 78)
    y = panel["y_on"]
    print(f"  {'year':6} {'n':>5} {'mean bps':>10} {'t-stat':>8} {'win %':>8}")
    print("  " + "-" * 42)
    for yr, grp in y.groupby(y.index.year):
        if len(grp) < 30:
            continue
        t = grp.mean() / (grp.std() / np.sqrt(len(grp)))
        print(f"  {yr:6} {len(grp):>5} {grp.mean()*10000:>+10.2f} "
              f"{t:>+8.2f} {(grp>0).mean()*100:>7.1f}%")
    half = len(y) // 2
    a, b = y.iloc[:half], y.iloc[half:]
    print(f"\n  first half : {a.mean()*10000:+.2f} bps  (t={a.mean()/(a.std()/np.sqrt(len(a))):+.2f})")
    print(f"  second half: {b.mean()*10000:+.2f} bps  (t={b.mean()/(b.std()/np.sqrt(len(b))):+.2f})")
    ts, pv = stats.ttest_ind(a, b, equal_var=False)
    print(f"  difference : t={ts:+.2f}, p={pv:.4f}  "
          f"-> {'DECAYED' if pv < 0.05 and b.mean() < a.mean() else 'no significant decay'}")


def by_weekday(panel: pd.DataFrame) -> None:
    print("\n" + "=" * 78)
    print("2. IS IT CONCENTRATED IN PARTICULAR WEEKDAYS?")
    print("=" * 78)
    names = {0: "Mon->Tue", 1: "Tue->Wed", 2: "Wed->Thu", 3: "Thu->Fri", 4: "Fri->Mon"}
    y = panel["y_on"]
    print(f"  {'night':10} {'n':>5} {'mean bps':>10} {'t-stat':>8} {'win %':>8}")
    print("  " + "-" * 46)
    for d, grp in y.groupby(panel["dow"]):
        if d not in names or len(grp) < 30:
            continue
        t = grp.mean() / (grp.std() / np.sqrt(len(grp)))
        print(f"  {names[d]:10} {len(grp):>5} {grp.mean()*10000:>+10.2f} "
              f"{t:>+8.2f} {(grp>0).mean()*100:>7.1f}%")
    print("\n  Fri->Mon spans 3 calendar days for the same single round trip.")


def net_table(y: pd.Series, mask: np.ndarray, label: str, trades_per_yr: float) -> None:
    sel = y[mask]
    if len(sel) == 0:
        return
    print(f"  {label:34}", end="")
    for cost in (0, 5, 10, 20, 30):
        net = sel - cost / 10_000.0
        ann = (1 + net).prod() ** (250.0 / len(y)) - 1.0
        print(f"{ann*100:>9.1f}%", end="")
    print(f"   {trades_per_yr:>6.0f}")


def selection(panel: pd.DataFrame, cols: list[str]) -> None:
    print("\n" + "=" * 78)
    print("3. CAN THE GOOD NIGHTS BE SELECTED IN ADVANCE?")
    print("=" * 78)
    X = panel[cols].to_numpy(float)
    y = panel["y_dir"].to_numpy(int)
    r = panel["y_on"]
    n = len(panel)

    models = {
        "logistic": Pipeline([("i", SimpleImputer(strategy="median")),
                              ("s", StandardScaler()),
                              ("c", LogisticRegression(C=0.1, max_iter=2000))]),
        "rand_fst": Pipeline([("i", SimpleImputer(strategy="median")),
                              ("c", RandomForestClassifier(
                                  n_estimators=400, max_depth=5, min_samples_leaf=40,
                                  random_state=0, n_jobs=-1))]),
        "hist_gb":  Pipeline([("i", SimpleImputer(strategy="median")),
                              ("c", HistGradientBoostingClassifier(
                                  max_depth=3, learning_rate=0.03, max_iter=300,
                                  min_samples_leaf=40, l2_regularization=1.0,
                                  random_state=0))]),
    }
    preds = {k: np.full(n, np.nan) for k in models}

    start = TRAIN_MIN
    folds = 0
    while start + EMBARGO + TEST_SIZE <= n:
        tr = np.arange(0, start)
        te = np.arange(start + EMBARGO, start + EMBARGO + TEST_SIZE)
        for name, mdl in models.items():
            m = mdl.__class__(**{"steps": [(a, b.__class__(**b.get_params()))
                                           for a, b in mdl.steps]})
            m.fit(X[tr], y[tr])
            preds[name][te] = m.predict_proba(X[te])[:, 1]
        start += TEST_SIZE
        folds += 1

    oos = ~np.isnan(preds["logistic"])
    print(f"  walk-forward folds: {folds}   OOS nights: {oos.sum()}")
    print(f"  OOS window: {panel.index[oos][0].date()} .. {panel.index[oos][-1].date()}\n")

    y_oos = y[oos]
    r_oos = r[oos]
    print(f"  {'model':12} {'dir acc':>9} {'z':>7} {'p':>8}")
    print("  " + "-" * 40)
    for name, p in preds.items():
        pv = p[oos]
        acc = ((pv > 0.5).astype(int) == y_oos).mean()
        z = (acc - 0.5) / (0.5 / np.sqrt(len(pv)))
        print(f"  {name:12} {acc*100:>8.2f}% {z:>+7.2f} "
              f"{2*(1-stats.norm.cdf(abs(z))):>8.4f}")

    print("\n  NET ANNUALISED RETURN by round-trip cost")
    print(f"  {'strategy':34}{'0bps':>10}{'5bps':>9}{'10bps':>9}"
          f"{'20bps':>9}{'30bps':>9}   {'trd/yr':>6}")
    print("  " + "-" * 90)

    yrs = len(r_oos) / 250.0
    net_table(r_oos, np.ones(len(r_oos), bool), "overnight, every night", 250)

    dow_oos = panel["dow"].to_numpy()[oos]
    net_table(r_oos, dow_oos == 4, "overnight, Fri->Mon only", 50)

    for name, p in preds.items():
        pv = p[oos]
        for th in (0.55, 0.60):
            m = pv > th
            if m.sum() < 20:
                continue
            net_table(r_oos, m, f"{name}, p>{th}", m.sum() / yrs)


def buy_and_hold(panel: pd.DataFrame) -> None:
    print("\n" + "=" * 78)
    print("4. THE BENCHMARK: BUY AND HOLD")
    print("=" * 78)
    c = panel["close"]
    yrs = len(c) / 250.0
    ann = (c.iloc[-1] / c.iloc[0]) ** (1 / yrs) - 1
    print(f"  Buy & hold RELIANCE : {ann*100:+.2f}%/yr over {yrs:.1f} years")
    print(f"  Round trips required: 1")
    print(f"  Cost drag           : ~0.00%/yr")


if __name__ == "__main__":
    panel, cols = build_overnight_panel()
    print(f"Overnight panel: {len(panel)} nights, {len(cols)} features "
          f"({panel.index[0].date()} .. {panel.index[-1].date()})")
    print("Leakage guard: PASSED\n")
    stability(panel)
    by_weekday(panel)
    selection(panel, cols)
    buy_and_hold(panel)
