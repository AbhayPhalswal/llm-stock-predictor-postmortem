"""
EVALUATION HARNESS  ·  walk-forward model bake-off

Scores every candidate predictor on identical out-of-sample folds, against the
baselines that actually matter, net of transaction costs.

═══════════════════════════════════════════════════════════════════════════════
WHY WALK-FORWARD WITH AN EMBARGO
═══════════════════════════════════════════════════════════════════════════════
Random k-fold on a time series trains on the future and tests on the past. It
inflates every metric and is the single most common way a backtest lies.

Here the training window only ever precedes the test window, an embargo gap sits
between them so that rolling features computed near the boundary cannot span the
split, and every transformer is fitted inside the fold on training data only.

═══════════════════════════════════════════════════════════════════════════════
WHAT COUNTS AS SUCCESS
═══════════════════════════════════════════════════════════════════════════════
Beating 50% is not success. The bar is:
  · always-long          — what the current live system effectively does
  · always-short         — the mirror, which exploits the negative intraday drift
  · always-flat          — holding cash, which costs nothing and loses nothing
A model that cannot beat all three, net of costs, has no value.

Run:  python evaluate.py
"""

import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import console_setup  # noqa: F401  — must precede any print()

import numpy as np
import pandas as pd

from sklearn.ensemble       import RandomForestClassifier, HistGradientBoostingClassifier, ExtraTreesClassifier
from sklearn.linear_model   import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.impute         import SimpleImputer
from sklearn.pipeline       import Pipeline
from sklearn.preprocessing  import StandardScaler
from sklearn.metrics        import roc_auc_score

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── EVALUATION CONFIGURATION ──────────────────────────────────────────────────
TRAIN_MIN   = 750     # ~3 years of history before the first prediction
TEST_SIZE   = 125     # ~6 months per fold
EMBARGO     = 5       # trading days dropped between train and test
COST_BPS    = 20.0    # round-trip cost in basis points (0.20%)
THRESHOLD   = 0.55    # trade only when the model is this confident


def walk_forward_splits(n: int):
    """Yields (train_idx, test_idx) with a strict temporal gap between them."""
    start = TRAIN_MIN
    while start + EMBARGO + TEST_SIZE <= n:
        tr = np.arange(0, start)
        te = np.arange(start + EMBARGO, start + EMBARGO + TEST_SIZE)
        yield tr, te
        start += TEST_SIZE


# ══════════════════════════════════════════════════════════════════════════════
#  ECONOMICS
# ══════════════════════════════════════════════════════════════════════════════

def economics(y_ret: np.ndarray, position: np.ndarray, cost_bps: float = COST_BPS) -> dict:
    """
    Converts a position series (+1 long, -1 short, 0 flat) into net performance.

    Cost is charged on any day a position is actually taken, since entering at
    the open and exiting at the close is a full round trip.
    """
    gross = position * y_ret
    traded = np.abs(position) > 0
    net    = gross - traded * (cost_bps / 10_000.0)

    n_days = len(net)
    ann    = (1.0 + net).prod() ** (250.0 / max(n_days, 1)) - 1.0
    sd     = net.std()
    sharpe = (net.mean() / sd * np.sqrt(250)) if sd > 0 else 0.0

    eq   = (1.0 + net).cumprod()
    dd   = (eq / np.maximum.accumulate(eq) - 1.0).min()

    return {
        "net_ann":   ann,
        "sharpe":    sharpe,
        "max_dd":    dd,
        "trade_pct": traded.mean(),
        "total_net": eq[-1] - 1.0 if len(eq) else 0.0,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MODEL ZOO
# ══════════════════════════════════════════════════════════════════════════════

def make_models() -> dict:
    """Every model is wrapped so imputation and scaling fit inside the fold."""
    def pipe(clf, scale=True):
        steps = [("imp", SimpleImputer(strategy="median"))]
        if scale:
            steps.append(("sc", StandardScaler()))
        steps.append(("clf", clf))
        return Pipeline(steps)

    return {
        "logistic_l2":  pipe(LogisticRegression(C=0.1, max_iter=2000)),
        "logistic_l1":  pipe(LogisticRegression(C=0.05, penalty="l1",
                                                solver="liblinear", max_iter=2000)),
        "random_forest": pipe(RandomForestClassifier(
            n_estimators=400, max_depth=5, min_samples_leaf=40,
            random_state=0, n_jobs=-1), scale=False),
        "extra_trees":  pipe(ExtraTreesClassifier(
            n_estimators=400, max_depth=6, min_samples_leaf=40,
            random_state=0, n_jobs=-1), scale=False),
        "hist_gb":      pipe(HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.03, max_iter=300,
            min_samples_leaf=40, l2_regularization=1.0,
            random_state=0), scale=False),
        "mlp":          pipe(MLPClassifier(
            hidden_layer_sizes=(32, 16), alpha=1.0, max_iter=800,
            early_stopping=True, random_state=0)),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN EVALUATION
# ══════════════════════════════════════════════════════════════════════════════

def run():
    panel = pd.read_csv(os.path.join(BASE_DIR, "panel.csv"),
                        index_col=0, parse_dates=True)
    with open(os.path.join(BASE_DIR, "feature_cols.txt"), encoding="utf-8") as fh:
        feature_cols = [ln.strip() for ln in fh if ln.strip()]

    X = panel[feature_cols].to_numpy(dtype=float)
    y = panel["y_dir"].to_numpy(dtype=int)
    r = panel["y_ret"].to_numpy(dtype=float)
    n = len(panel)

    folds = list(walk_forward_splits(n))
    print(f"Panel      : {n} days, {len(feature_cols)} features")
    print(f"Folds      : {len(folds)}  (train>={TRAIN_MIN}, test={TEST_SIZE}, embargo={EMBARGO})")
    oos_start = folds[0][1][0]
    print(f"OOS window : {panel.index[oos_start].date()} .. {panel.index[-1].date()}")
    print(f"Costs      : {COST_BPS:.0f} bps round trip   ·  trade threshold p>{THRESHOLD}")
    print()

    # Collect out-of-sample predictions for every model across all folds
    oos_idx   = np.concatenate([te for _, te in folds])
    preds     = {name: np.full(n, np.nan) for name in make_models()}

    for k, (tr, te) in enumerate(folds, 1):
        models = make_models()   # fresh, unfitted, every fold
        for name, mdl in models.items():
            try:
                mdl.fit(X[tr], y[tr])
                preds[name][te] = mdl.predict_proba(X[te])[:, 1]
            except Exception as exc:
                print(f"  fold {k} {name} failed: {str(exc)[:60]}")
        print(f"  fold {k:>2}/{len(folds)}  train={len(tr):>4}  "
              f"test={panel.index[te[0]].date()}..{panel.index[te[-1]].date()}")

    y_oos = y[oos_idx]
    r_oos = r[oos_idx]

    # ── BASELINES ─────────────────────────────────────────────────────────────
    rows = []
    for label, pos in [
        ("baseline: always-long",  np.ones(len(oos_idx))),
        ("baseline: always-short", -np.ones(len(oos_idx))),
        ("baseline: always-flat",  np.zeros(len(oos_idx))),
    ]:
        e = economics(r_oos, pos)
        acc = (y_oos == 1).mean() if label.endswith("long") else \
              ((y_oos == 0).mean() if label.endswith("short") else np.nan)
        rows.append((label, acc, np.nan, e))

    # ── MODELS ────────────────────────────────────────────────────────────────
    for name in preds:
        p = preds[name][oos_idx]
        if np.isnan(p).all():
            continue
        ok  = ~np.isnan(p)
        acc = ((p[ok] > 0.5).astype(int) == y_oos[ok]).mean()
        try:
            auc = roc_auc_score(y_oos[ok], p[ok])
        except Exception:
            auc = np.nan

        pos = np.zeros(len(p))
        pos[p > THRESHOLD]       = 1.0
        pos[p < (1 - THRESHOLD)] = -1.0
        rows.append((name, acc, auc, economics(r_oos, pos)))

    # ── REPORT ────────────────────────────────────────────────────────────────
    print()
    print("=" * 100)
    print(f"{'model':24} {'dir acc':>8} {'AUC':>7} {'net ann':>9} "
          f"{'sharpe':>8} {'max dd':>8} {'traded':>8}")
    print("=" * 100)
    for label, acc, auc, e in rows:
        acc_s = f"{acc*100:.2f}%" if pd.notna(acc) else "     —"
        auc_s = f"{auc:.4f}"      if pd.notna(auc) else "     —"
        print(f"{label:24} {acc_s:>8} {auc_s:>7} "
              f"{e['net_ann']*100:>8.2f}% {e['sharpe']:>8.2f} "
              f"{e['max_dd']*100:>7.1f}% {e['trade_pct']*100:>7.1f}%")
    print("=" * 100)

    np.save(os.path.join(BASE_DIR, "oos_idx.npy"), oos_idx)
    pd.DataFrame({k: v for k, v in preds.items()},
                 index=panel.index).to_csv(os.path.join(BASE_DIR, "oos_preds.csv"))
    print(f"\nSaved out-of-sample predictions to oos_preds.csv")
    return rows


if __name__ == "__main__":
    run()
