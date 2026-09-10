# Multi-Agent Work Plan

How to split this project across Nemotron 3 Ultra (opencode), Gemini Pro,
ChatGPT Go, a second Claude Pro account, and this Claude Code session.

---

## The constraint that shapes everything

Most of this work **does not parallelise across chat assistants**, and pretending
otherwise produces a pile of incompatible code. Five agents writing to one repo
without a shared contract will each invent their own feature naming, their own
train/test split, and their own leakage bugs, and you will spend longer merging
than you saved.

Two rules make it work:

1. **Interfaces get frozen before anything fans out.** The data schema, the
   feature contract, the label definition and the evaluation harness are built
   once, serially, first. Everything downstream plugs into fixed slots.
2. **Exactly one agent writes to the repo.** That is this Claude Code session,
   because it has the filesystem and can run the tests. Every other agent
   delivers a *standalone file* against the contract, or delivers *findings*.
   You paste their output back; nothing else touches `reliance_stocks/`.

Break either rule and the speedup goes negative.

## What each tool is actually best at here

| Tool | Assign it | Why |
|---|---|---|
| **This Claude Code session** | Foundation, integration, all repo writes | Only agent with filesystem + execution. Can verify, not just assert. |
| **Nemotron 3 Ultra** (opencode) | Model implementations (Track B) | Runs in your terminal against real files. Free tier. Give it one track, in its own scratch dir. |
| **Gemini Pro** | Research (Track C) | Deep Research mode + large context. Findings, not code — no merge risk. |
| **ChatGPT Go** | Feature implementations (Track A) | Self-contained pure functions are easy to specify and easy to verify. |
| **2nd Claude Pro** | Prompt engineering + adversarial review (Track D) | Best at critiquing statistical method and finding leakage. |

Note: **Nemotron is not running locally.** Your LM Studio has Llama 3.1 8B and
Qwen2.5 7B at Q4 — that 8B quant was what produced the biased predictions.
`opencode/nemotron-3-ultra-free` is a hosted model reached through opencode.

---

## Phase 0 — Foundation (serial, this session, blocking)

Nothing else starts until these land.

| ID | Task | Output |
|---|---|---|
| F1 | Bulk data download, 22 tickers × 10y | `research/data/*.csv` |
| F2 | Leakage-safe panel: align all series to NSE trading days, define what is knowable at 09:15 IST | `research/build_panel.py` |
| F3 | Label definition: direction + magnitude bucket | in `build_panel.py` |
| F4 | Walk-forward evaluation harness + baselines | `research/evaluate.py` |

**F2 is the one that decides whether any of this is real.** Today's High, Low,
Close and Volume are *not* known at 09:15. The US session closed overnight so
its previous close *is* known. Every feature must be stamped with its
availability time, and the harness must refuse any feature that fails the check.

## Phase 1 — Parallel tracks (fan out after Phase 0)

### Track A — Features → ChatGPT Go
Each is a pure function `f(panel: pd.DataFrame) -> pd.DataFrame` returning only
columns computable from information available at 09:15 IST.

| ID | Family |
|---|---|
| A1 | Price & volatility: overnight gap, prior returns (1/5/20d), realised vol, ATR, RSI, EMA spreads, Bollinger position, lagged volume |
| A2 | Index & cross-section: NIFTY/BANKNIFTY gap, India VIX level & change, beta to NIFTY, peer-basket gap, O2C complex spread, breadth |
| A3 | Macro & global: Brent & WTI overnight move, crack-spread proxy, USD/INR, DXY, US 10y, S&P/Nasdaq previous close, US VIX |
| A4 | Calendar: day of week, F&O expiry, month/quarter end, earnings proximity, pre/post-holiday |

### Track B — Models → Nemotron 3 Ultra
Each implements `fit(X, y) / predict_proba(X) / predict_interval(X)` against the
Phase 0 interface.

| ID | Family |
|---|---|
| B1 | Regularised linear: logistic (direction), ridge/elastic-net (magnitude) |
| B2 | Tree ensembles: RandomForest, HistGradientBoosting, ExtraTrees |
| B3 | Time series: ARIMA on returns, GARCH on volatility → feeds the magnitude range |
| B4 | Neural: MLP and a small LSTM — expected to lose at this sample size; benchmark to prove it |
| B5 | **Conformal prediction** for calibrated magnitude intervals — this is the correct machinery for "direction with a range of magnitude" |

### Track C — Research → Gemini Pro
Findings documents. No code, so no merge risk.

| ID | Question |
|---|---|
| C1 | What does the literature say about intraday open-to-close predictability in liquid single names? What effect sizes are credible? |
| C2 | Exact Indian retail cost stack: brokerage, STT, exchange txn charges, SEBI fees, GST, stamp duty, slippage. Produce a total round-trip bps figure. |
| C3 | Survey backtesting/feature libraries: vectorbt, backtrader, mlfinlab, ta, skfolio. What should be adopted vs built? |
| C4 | LLM news-sentiment scoring for equities: prompt patterns, published accuracy, pitfalls, and whether it adds alpha over price features alone |

### Track D — Review → 2nd Claude Pro
| ID | Task |
|---|---|
| D1 | Adversarial leakage audit of `build_panel.py` — hunt lookahead bias line by line |
| D2 | Statistical method review: is the walk-forward valid? Multiple-testing correction across ~60 features? |
| D3 | Design the Nemotron sentiment-scoring prompt and its output contract |

## Phase 2 — Integration (serial, this session)

| ID | Task |
|---|---|
| I1 | Feature significance screen with multiple-testing correction; drop what doesn't survive |
| I2 | Model bake-off on identical walk-forward folds; select by out-of-sample economic return, net of C2's cost figure |
| I3 | Wire the winner into the live pipeline; rewrite `sentiment_engine.py` to Nemotron, sentiment-only |
| I4 | Full README rewrite with honest measured performance |

---

## The meta-prompt

Paste this into any capable model, then append a task row from the tables above.
It generates the full working prompt for that unit of work.

````text
You are a prompt engineer building task prompts for AI coding and research
agents working on a shared quantitative finance codebase. You will be given ONE
work unit. Produce ONE complete, self-contained prompt that a fresh agent — with
no memory of this project — can execute correctly on the first attempt.

=== PROJECT CONTEXT (carry into every prompt you generate) ===
Goal: predict the direction (up/down) and a calibrated magnitude range of
RELIANCE.NS's open-to-close move on the NSE, decided at 09:15 IST each trading
day, and only trade when the edge clears real transaction costs.

Hard facts the agent must respect:
- Data: 10 years daily OHLCV, 22 tickers, cached as CSV in research/data/.
  Target RELIANCE.NS; context = NIFTY 50, BANKNIFTY, India VIX, O2C peers
  (ONGC/IOC/BPCL), Airtel, large caps, Brent/WTI/Gold, USDINR, DXY, US 10y,
  S&P 500, Nasdaq, US VIX.
- CRITICAL — information availability. The decision is made at 09:15 IST.
  KNOWN: everything through yesterday's NSE close; last night's US close;
  today's NSE open; today's index opens; overnight commodity and FX moves.
  NOT KNOWN: today's NSE close, high, low, or volume. Any feature using them
  is lookahead bias and invalidates the entire result.
- Validation must be walk-forward with an embargo gap. No random k-fold on
  time series. No fitting any scaler, imputer or selector on the full dataset.
- The benchmark to beat is NOT 50%. It is (a) predict-close-equals-open, and
  (b) always-long. A model that loses to either is worthless.
- Realistic round-trip cost is 10-30 bps and must be subtracted before any
  profitability claim.
- Prior result on 22 live trades: 40.9% direction accuracy (not significant at
  that sample size), but a statistically real upward bias (over-predicted 20 of
  22 days, p=0.00012) and a real loss to the naive baseline (p=0.017).

=== YOUR OUTPUT FORMAT ===
Produce a prompt with exactly these sections:

1. ROLE — one or two sentences establishing the agent's specialty.
2. OBJECTIVE — the single deliverable, stated concretely.
3. CONTEXT — the project facts above, trimmed to only what this task needs.
4. INTERFACE CONTRACT — exact function signatures, input dtypes, output column
   names and dtypes. Be rigid; this is what makes the work mergeable.
5. REQUIREMENTS — numbered, testable, unambiguous.
6. FORBIDDEN — the specific failure modes for this task. Always include the
   information-availability rule for anything touching features or models.
7. SELF-CHECK — assertions the agent must run and show passing output for
   before declaring done.
8. DELIVERABLE — exact filename, and a statement that the agent must return one
   complete file with no elisions, no "# rest unchanged", no placeholders.

=== RULES FOR YOU ===
- Be specific over general. "Compute RSI(14) from the Close column, shifted one
  day" beats "compute technical indicators".
- Assume the agent CANNOT ask follow-up questions.
- Assume the agent CANNOT see the other agents' work. Never reference another
  task's internals — only the frozen interface.
- Include at least three concrete self-check assertions with expected results.
- Demand the agent state its assumptions explicitly rather than silently guess.
- For research tasks, demand sources with dates, and require the agent to
  separate measured findings from its own inference.
- Output only the generated prompt. No preamble, no commentary.

=== WORK UNIT ===
[paste one row here: the ID, family/question, and its track]
````

## Running order

```
Phase 0  (this session, ~serial)
   └─> Phase 1: A ‖ B ‖ C ‖ D   all four in parallel, different tools
          └─> Phase 2 (this session, serial)
```

Track C can start **immediately** — it has no dependency on Phase 0. Send C2
(the cost stack) to Gemini first; it is the number that decides whether any
edge found later is even worth having.
