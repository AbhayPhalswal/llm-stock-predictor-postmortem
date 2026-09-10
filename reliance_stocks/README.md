# Reliance Quantitative Engine

A daily open-to-close prediction and paper-trading loop for `RELIANCE.NS`, driven
by a local LLM served from LM Studio. State lives in a single SQLite file,
`trading_firm_memory.db`.

---

## Setup

```bash
pip install -r requirements.txt
```

LM Studio must be running with its server on `http://localhost:1234/v1` before
any script that talks to the model.

## Daily run order

| When | Command | What it does |
|---|---|---|
| after 09:15 IST | `python 1_fire_morning.py` | Gates on trading day + market open, reads the true NSE Open, asks the LLM for a close prediction, writes it to the vault |
| 11:00–14:00 IST | `python alpha_scraper.py` | Scrapes 4 Google News RSS feeds, dedups, re-scores sentiment, updates today's row |
| all day | `python dashboard.py` | Flet UI: capital, chart, ledger, order book |
| after 15:30 IST | `python 2_fire_afternoon.py` | Gates on market close, reads the official close, computes PnL, settles the row |

Each script is safe to re-run. The morning script upserts, and settlement is a
no-op on an already-settled day.

## Files

```
1_fire_morning.py     morning prediction pipeline
2_fire_afternoon.py   settlement + PnL
alpha_scraper.py      news aggregation and sentiment re-scoring
sentiment_engine.py   LLM client, prompt, 4-tier JSON extraction, risk clamp
memory_vault.py       SQLite schema, migrations, all reads and writes
market_calendar.py    trading-day gate (weekends + holiday list)
console_setup.py      UTF-8 console bootstrap — import before any print()
dashboard.py          Flet dashboard
trading_firm_memory.db  the vault
```

## Schema

`reliance_ledger` — one row per trading day:
`trade_date` (ISO, UNIQUE), `headline`, `alpha_sentiment`, `base_price`,
`predicted_close`, `actual_close`, `error_variance`, `realised_pnl`, `settled`

`capital_profile` — append-only equity curve: `active_capital`, `last_updated`

`initialize_vault()` is idempotent and runs the migrations on every startup.

---

## How the strategy actually performs

Measured over the 22 settled trades in the vault (2026-05-27 → 2026-06-26):

| Metric | Value |
|---|---|
| Direction accuracy | 40.9% (9/22) — *not* statistically distinguishable from a coin flip at n=22 (95% CI 23.3–61.3%, p=0.52) |
| Mean error (actual − predicted) | **−16.30 INR** |
| Over-predicted on | **20 of 22 days** |
| Mean absolute error | 17.08 INR (1.30% of price) |
| MAE of "predict close = open" | **10.90 INR** |
| Days it went long | 21 of 22 |
| Capital (recorded) | 100,000 → 99,030 (−0.97%) |
| Capital (all 22 trades compounded) | **−5.55%** — the recorded curve starts late and flatters the result |
| Same, with 0.2% round-trip costs | **−13.12%** |

Two things to sit with:

**The model is beaten by predicting no change at all.** A constant
`predicted_close = base_price` has 36% lower absolute error, and wins on 17 of
22 days (p=0.017). This one is statistically real, not sample noise.

**It is systematically biased upward.** It over-predicted on 20 of 22 days
(p=0.00012). This is the strongest signal in the data and it is a *calibration*
fault, which means it is correctable — see below.

**Direction accuracy is simply unmeasured.** 22 trades cannot separate 41% from
50%. Do not conclude the model picks direction badly; conclude that you do not
yet know.

**The self-correction loop does not work.** The prompt shows the model its last
five errors and instructs it to apply a corrective offset. It over-predicted on
20 of 22 days anyway, including on days where all five prior rows shown to it
were negative. The feedback string is built and ordered correctly — the model
simply does not act on it.

The strategy also never really chose: it went long on 21 of 22 days, so the
SKIP rule that is supposed to protect capital fired once. It is close to a
levered buy-and-hold with extra steps.

## How long until this is profitable

Time does not create edge, so the answerable question is how long until you
*know*. With daily volatility of 1.10% and a mean absolute open-to-close move of
0.83%:

**Breakeven accuracy required** (before any profit at all):

| Round-trip cost | Accuracy needed |
|---|---|
| 0.05% | 53.0% |
| 0.10% | 56.0% |
| 0.20% | 62.1% |
| 0.30% | 68.1% |

Your 95% confidence interval tops out at 61.3%, so even the most generous
reading of the current data only just reaches breakeven at low costs.

**Trades needed to prove an edge** (80% power, 95% confidence), at one trade
per day:

| If true accuracy is | Trades | Calendar time |
|---|---|---|
| 55% | 777 | 3.1 years |
| 60% | 188 | 0.8 years |
| 65% | 79 | 0.3 years |

Running live at one sample per day is the slowest possible way to answer this.
A backtest over five years of RELIANCE daily OHLC yields ~1,250 samples in a
single afternoon.

## Modelling caveats

These are not bugs, but they make the recorded results optimistic:

- **No costs.** Brokerage, STT, exchange fees, GST and slippage are not
  modelled. An open-to-close round trip on Indian equity runs roughly
  0.1–0.3%, which is larger than any edge visible above.
- **Optimistic fill.** Settlement assumes the entire position fills at exactly
  the 09:15 Open. The prediction is produced *after* that open is printed, so
  that price is not actually reachable.
- **No position sizing.** Every long deploys 100% of capital regardless of
  conviction or the alpha score.
- **`alpha_scraper` overwrites `alpha_sentiment` after the prediction is
  made**, so the score stored on a row is not the score the prediction was
  based on.

## Dashboard status

The vault read path is live: capital, chart, ledger, the AI target and
persistence on liquidation all use `memory_vault`.

Still simulated, and labelled as such in the source:

- `_simulate_tick()` — random walk, not live market data
- `_refresh_alpha()` — RSI / EMA Δ / Vol surge / ATR are random walks
- the order book is generated

Everything derived from the tick — unrealised PnL, the stop-loss trigger,
MARKET BUY fills — is therefore simulated too. Treat the dashboard as a monitor
for vault state, not as an execution surface.
