# Findings — Maximised Rebuild

What happened when the system was rebuilt with every input that could plausibly
matter, evaluated honestly.

**Scope of the attempt:** 21 data sources, 10 years (2,474 trading days), 54
engineered features across 5 families, 6 model families, 13-fold walk-forward
validation with an embargo gap. That is roughly 112× the evidence the original
system had accumulated in a month of live running.

---

## 1. The structural finding

This is the most important result, and it has nothing to do with machine
learning.

| Window | Mean return | t-stat | p | Win rate |
|---|---|---|---|---|
| **Overnight** (close → next open) | **+12.67 bps/day** | **+7.55** | **<0.0001** | 60.7% |
| **Intraday** (open → close) | −4.40 bps/day | −1.44 | 0.15 | 47.1% |

RELIANCE's entire long-run drift accrues **overnight**. The intraday session —
the only window the system trades — has slightly negative drift and no
statistically significant direction at all.

The original system went long on 21 of 22 days in the open-to-close window. It
was structurally positioned in the one window where the stock does not go up,
and flat during the window where it does. Over 10 years, always-long open-to-close
compounds to **−13.2%/yr before costs**.

No amount of feature engineering fixes a window choice.

## 2. The models do have real skill — and it is far too small

| Model | Direction acc | z vs 50% | p | Gross edge |
|---|---|---|---|---|
| **random_forest** | **53.72%** | **3.00** | **0.0027** | 5.47 bps/day |
| hist_gb | 52.49% | 2.01 | 0.045 | 6.43 bps/day |
| logistic_l2 | 52.12% | 1.71 | 0.087 | 6.65 bps/day |
| extra_trees | 51.75% | 1.41 | 0.16 | 2.98 bps/day |
| logistic_l1 | 50.46% | 0.37 | 0.71 | 3.86 bps/day |
| mlp | 49.66% | −0.27 | 0.78 | −2.47 bps/day |

The random forest's 53.72% out-of-sample direction accuracy over 1,625 days is
**statistically real** (p=0.0027). This is not noise, and it is genuinely better
than the original system managed.

It is also worth nothing, because the gross edge is **5.47 bps/day** and a retail
round trip costs **10–30 bps**. Breakeven needs costs under ~5.5 bps.

Note too that while *direction accuracy* is significant, the *gross return* is
not (t=1.42). The models get direction right slightly more often but are wrong
on the larger moves — a classic pattern, and a reminder that accuracy and
profitability are different questions.

## 3. Net performance: everything loses to cash

Walk-forward out-of-sample, 2019-11 → 2026-09, at 20 bps round trip:

| Strategy | Net annualised | Sharpe | Max DD |
|---|---|---|---|
| baseline: always-flat (cash) | **0.00%** | 0.00 | 0.0% |
| extra_trees | −4.07% | −0.34 | −31.0% |
| logistic_l1 | −4.68% | −0.58 | −37.8% |
| random_forest | −10.14% | −0.64 | −55.6% |
| hist_gb | −15.96% | −0.72 | −85.0% |
| logistic_l2 | −16.96% | −0.79 | −72.8% |
| baseline: always-short | −32.35% | −1.47 | −93.7% |
| mlp | −34.57% | −1.83 | −93.9% |
| **baseline: always-long** *(what the original did)* | **−48.85%** | −2.61 | −98.8% |

Holding cash beats every model. The reason is arithmetic: a daily round trip at
20 bps costs **50% per year in fees alone**. No equity signal of this size
survives that.

Sensitivity — net annualised return of the best configuration:

| Threshold | 0 bps | 5 bps | 10 bps | 20 bps | 30 bps |
|---|---|---|---|---|---|
| 0.50 | +14.6% | +1.1% | — | — | — |
| 0.55 | +18.5% | +8.8% | +0.4% | — | — |
| 0.60 | +11.8% | +5.9% | +2.2% | +0.6% | — |
| 0.65 | +10.8% | +7.8% | +4.8% | +1.0% | +1.0% |

The signal is real at zero cost (+14–18%/yr). It dies between 5 and 10 bps.
Treat the 0.65-threshold row with suspicion: at that confidence the model trades
**4 times in 1,625 days**, so those cells are noise, not strategy.

## 4. Does adding more parameters help? No.

**Zero of 49 features survive Benjamini-Hochberg correction at FDR 5%.**

The strongest single feature is large-cap gap dispersion at ρ = −0.044
(p=0.028 uncorrected), which fails correction because 49 features were tested.

| Strongest features | ρ | p (uncorrected) |
|---|---|---|
| largecap_gap_disp | −0.0444 | 0.028 |
| banknifty_gap | −0.0361 | 0.074 |
| us10y | +0.0335 | 0.097 |
| brent_1d | +0.0327 | 0.106 |
| **gap** (overnight gap) | −0.0244 | 0.227 |

Even the overnight gap — the variable most likely a priori to predict the
intraday move — carries no significant univariate signal.

**This answers the parameter question directly.** More inputs is not the
constraint. Twenty-one data sources spanning Indian equities, the O2C complex,
crude, FX, rates, global indices and the calendar produce a combined edge of
about 5 bps/day. The ceiling here is cost and market efficiency, not information.

## 5. The comparison that settles it

| Strategy | Net annualised | Round trips/yr |
|---|---|---|
| **Buy & hold RELIANCE** | **+18.45%** | **1** |
| Overnight-only @ 10 bps | +5.99% | 250 |
| Overnight-only @ 20 bps | −17.46% | 250 |
| Best ML model @ 20 bps | −10.14% | ~80 |

Buy and hold beats every active strategy tested, at a fraction of the cost and
complexity. Even the overnight effect — which is *seven-sigma real* — cannot be
harvested profitably at retail cost, because capturing 12.67 bps/day requires
paying 10–30 bps/day to do it.

---

## 6. The overnight lead — tested, and closed

The intraday study pointed at the overnight window as the one place with a
strong signal. It was tested properly. The verdict is **real effect, real model
skill, dead strategy.**

### Overnight direction is genuinely predictable

Predicting the overnight move is an easier problem than the intraday one,
because the decision is taken at 15:30 with the full day's OHLCV known.

| Model | Direction acc | vs 50% | vs **base rate 57.91%** |
|---|---|---|---|
| hist_gb | **63.02%** | z=+10.49 | **+5.11pp, z=+4.17, p<0.0001** |
| rand_fst | 62.52% | z=+10.10 | +4.61pp |
| logistic | 61.72% | z=+9.45 | +3.81pp |

**The benchmark matters.** Overnight returns are positive 57.91% of the time, so
always going long overnight scores 57.91% for free. Measured against 50% the
model looks spectacular (z=+10.5); measured against the baseline that costs
nothing, its edge is +5.11pp. Still statistically real (p<0.0001) — but a fifth
as impressive as the naive framing suggests.

### The effect has decayed, and the strategy is now losing

| Period | Mean | t-stat |
|---|---|---|
| First half (2016–2021) | +19.85 bps/night | +7.45 |
| Second half (2021–2026) | +5.43 bps/night | +2.69 |
| Difference | | **t=+4.31, p<0.0001** |

Net return by year, best configuration (hist_gb, p>0.60, 20 bps cost):

| Year | Model net | Always-on net |
|---|---|---|
| 2020 | **+77.6%** | +23.9% |
| 2021 | +16.2% | +0.7% |
| 2022 | +5.2% | −42.6% |
| 2023 | −3.1% | −14.0% |
| 2024 | −9.9% | −32.8% |
| 2025 | −0.6% | −29.0% |
| 2026 | −7.9% | −20.9% |

**Every year from 2023 onward is negative.** The entire headline return comes
from 2020–2021 — the COVID volatility regime. A backtest reporting only the
aggregate would show a profitable strategy; the year-by-year view shows one that
stopped working four years ago.

The model does add value *relative to always-on* (2022: +5.2% vs −42.6%). But
losing less than a bad baseline is not a strategy.

### Weekday concentration: the opposite of the hypothesis

Friday→Monday spans three calendar days per round trip, so it should be the
cheapest way to harvest the effect. It is the weakest night in the sample
(+6.81 bps, t=+1.39, not significant), and nets **negative at every cost level**.
Mon→Tue and Tue→Wed carry the effect instead — the nights with no cost advantage.

### Verdict

| Strategy | Net annualised @ 20 bps |
|---|---|
| **Buy & hold RELIANCE** | **+18.06%** |
| Overnight, best model, p>0.60 | +8.7% *(all of it pre-2022)* |
| Overnight, every night | −20.0% |
| Overnight, Fri→Mon only | −9.5% |
| Best intraday model | −10.14% |

Buy and hold wins, on the full sample and on the recent sample, with one round
trip instead of hundreds.

**The last open question is closed.** The overnight anomaly was real and was
tradeable roughly 2017–2021. It has decayed to the point where it no longer
covers transaction costs. Nothing tested here has a live edge.

---

## What this means for the project

The engineering is now sound: leakage-safe panel construction, walk-forward
validation with embargo, honest cost accounting, multiple-testing correction.
Those are the parts worth keeping, and they will give a straight answer to any
future idea in an afternoon.

The strategy is not viable as designed, and the binding constraint is not model
quality. Three things would change the picture, in order of leverage:

1. **Establish your true cost per round trip.** Everything hinges on this. At
   ≤5 bps parts of this become viable; at 20 bps nothing does. This is a factual
   question with a definite answer — get it before anything else.
2. **Cut trading frequency.** Costs scale linearly with turnover. Daily trading
   at 20 bps burns 50%/yr; weekly burns 10%/yr. Any real edge is far more likely
   to survive at lower frequency.
3. **Trade the window that actually has drift.** The overnight effect is the
   strongest thing in this dataset by an order of magnitude (t=7.55 vs t=1.42).
   If anything here is worth pursuing, it is that — and probably as a
   hold-through position rather than a daily round trip.

What is *not* worth more effort: adding features, adding data sources, or
upgrading the LLM. Those were tested at scale and the answer was no.

---

## Reproducing

```bash
python fetch_data.py     # 21 tickers x 10y -> research/data/
python build_panel.py    # leakage-safe panel + audit -> panel.csv
python evaluate.py       # 13-fold walk-forward bake-off
```
