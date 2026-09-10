import console_setup  # noqa: F401  — must precede any print()
import sys
import time
from datetime import datetime, date

import pytz
import yfinance as yf

import sentiment_engine
import market_calendar
import memory_vault

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║        MORNING IGNITION ENGINE  ·  V5.0  ·  NSE OPEN-PRICE TARGETING       ║
# ║        IST Market Gate  ·  True Open Anchor  ·  Chronological Feedback      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── MARKET TIME CONFIGURATION ─────────────────────────────────────────────────
IST              = pytz.timezone("Asia/Kolkata")
NSE_OPEN_HOUR    = 9
NSE_OPEN_MINUTE  = 15    # True price discovery is complete at 09:15 AM IST
TICKER           = "RELIANCE.NS"


# ══════════════════════════════════════════════════════════════════════════════
#  TELEMETRY CONSOLE
# ══════════════════════════════════════════════════════════════════════════════

def _ts() -> str:
    return datetime.now(IST).strftime("%H:%M:%S")

def log_info(msg: str):
    print(f"  [{_ts()} IST] ▸  {msg}")

def log_ok(msg: str):
    print(f"  [{_ts()} IST] ✔  {msg}")

def log_warn(msg: str):
    print(f"  [{_ts()} IST] ⚠  {msg}")

def log_err(msg: str):
    print(f"  [{_ts()} IST] ✖  {msg}")

def log_signal(msg: str):
    print(f"  [{_ts()} IST] ⚡ SIGNAL  ▸  {msg}")

def section(title: str):
    bar = "─" * (64 - len(title) - 3)
    print(f"\n  ┌─ {title} {bar}")

def section_end():
    print("  └" + "─" * 65)

def banner():
    now_ist = datetime.now(IST).strftime("%Y-%m-%d  %H:%M:%S")
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║    ☀  MORNING IGNITION ENGINE  ·  V5.0  ·  NSE OPEN TARGETING  ║")
    print(f"║    INIT: {now_ist} IST" + " " * (35 - len(now_ist)) + "║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE A — MARKET TIME GATE
# ══════════════════════════════════════════════════════════════════════════════

def enforce_market_time_gate() -> None:
    """
    Validates that the current IST time is at or after 09:15 AM — the point
    at which NSE's pre-open auction closes and the true opening price is
    permanently printed on the daily candle.

    Executing before this window means yfinance returns yesterday's Close
    as today's Open, silently anchoring the AI's entire prediction to stale,
    pre-gap data.  This gate prevents that class of error entirely.

    Exits with a non-zero status code on pre-open detection so that any
    calling shell scheduler can detect and re-queue the run.
    """
    section("PHASE 0 · TRADING-DAY VALIDATION")

    today_ist = datetime.now(IST).date()
    is_open, reason = market_calendar.is_trading_day(today_ist)
    log_info(f"Date (IST)       : {today_ist.isoformat()}")

    if not is_open:
        log_err(reason)
        log_err("yfinance would return the previous session's candle, creating a")
        log_err("phantom ledger row that can never settle. Aborting.")
        section_end()
        sys.exit(1)

    log_ok("Trading day confirmed — NSE equity segment is scheduled to trade.")
    section_end()

    section("PHASE 1 · MARKET TIME GATE VALIDATION")

    now_ist = datetime.now(IST)
    gate_dt = now_ist.replace(
        hour=NSE_OPEN_HOUR, minute=NSE_OPEN_MINUTE, second=0, microsecond=0
    )

    log_info(f"Current IST time : {now_ist.strftime('%H:%M:%S')}")
    log_info(f"NSE gate time    : {gate_dt.strftime('%H:%M:%S')}")

    if now_ist < gate_dt:
        remaining = gate_dt - now_ist
        mins, secs = divmod(int(remaining.total_seconds()), 60)

        section_end()
        print()
        print("  ╔══════════════════════════════════════════════════════════════╗")
        print("  ║  🔴  MARKET PRE-OPEN DETECTED                               ║")
        print("  ║                                                              ║")
        print("  ║  True price discovery is incomplete.                        ║")
        print("  ║  yfinance will return yesterday's Close as today's Open.    ║")
        print("  ║                                                              ║")
        print(f"  ║  Please re-run ignition after 09:15 AM IST.                 ║")
        print(f"  ║  Time remaining until gate opens: {mins:02d}m {secs:02d}s" +
              " " * (18 - len(f"{mins:02d}m {secs:02d}s")) + "║")
        print("  ╚══════════════════════════════════════════════════════════════╝")
        print()
        sys.exit(1)

    log_ok(f"Market gate CLEAR — NSE is open. True Open price available.")
    section_end()


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE A (cont.) — TRUE OPEN PRICE ACQUISITION
# ══════════════════════════════════════════════════════════════════════════════

def get_true_open_price() -> float | None:
    """
    Fetches the daily candle for RELIANCE.NS and isolates today's Open price.

    Why Open and not Close or live tick:
      - The Open price is the exact anchor printed at 09:15 AM after the
        pre-open auction.  It is immutable for the rest of the session.
      - Using a live 1-minute tick introduces micro-noise that has nothing
        to do with the structural gap the AI needs to predict against.
      - Using yesterday's Close silently hides overnight gaps and earnings
        surprises that occurred before the bell.

    Returns None on any fetch or data-shape failure so the caller can abort
    cleanly rather than proceeding with a bad anchor price.
    """
    section("PHASE 2 · TRUE OPEN PRICE ACQUISITION")
    log_info(f"Ticker           : {TICKER}")
    log_info(f"Query window     : period=1d, interval=1d (today's daily candle)")

    t0 = time.time()
    try:
        ticker     = yf.Ticker(TICKER)
        daily_data = ticker.history(period="1d", interval="1d")

        if daily_data.empty:
            log_err("yfinance returned an empty DataFrame. "
                    "Market may be closed or ticker invalid.")
            section_end()
            return None

        # Validate the candle's date is today in IST
        candle_date = daily_data.index[-1]
        # yfinance index is timezone-aware; normalise to IST date for comparison
        try:
            candle_date_ist = candle_date.tz_convert(IST).date()
        except Exception:
            candle_date_ist = candle_date.date()

        today_ist = datetime.now(IST).date()

        if candle_date_ist != today_ist:
            log_warn(
                f"Candle date mismatch: got {candle_date_ist}, expected {today_ist}. "
                f"Exchange may not have printed today's Open yet."
            )
            # Do not abort — the gate check already confirmed we are post 09:15.
            # A one-day-old candle here indicates a market holiday or data lag;
            # log it and allow the run to continue with the best available data.

        open_price = round(float(daily_data["Open"].iloc[-1]), 2)
        latency_ms = round((time.time() - t0) * 1000)

        log_ok(f"Open price acquired : ₹{open_price:.2f}  ({latency_ms}ms)")
        log_info(f"Candle date (IST)   : {candle_date_ist}")
        log_info(
            f"OHLC snapshot — "
            f"O: ₹{daily_data['Open'].iloc[-1]:.2f}  "
            f"H: ₹{daily_data['High'].iloc[-1]:.2f}  "
            f"L: ₹{daily_data['Low'].iloc[-1]:.2f}  "
            f"C: ₹{daily_data['Close'].iloc[-1]:.2f}"
        )
        section_end()
        return open_price

    except Exception as exc:
        latency_ms = round((time.time() - t0) * 1000)
        log_err(f"Price fetch failed after {latency_ms}ms: {exc}")
        section_end()
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE B — CHRONOLOGICAL MEMORY VAULT ALIGNMENT
# ══════════════════════════════════════════════════════════════════════════════

def get_historical_feedback() -> str:
    """
    Thin wrapper around memory_vault.get_recent_performance_feedback() that
    logs the retrieval step within the ignition pipeline's telemetry stream.

    The vault function internally:
      1. Queries the last 5 settled rows with ORDER BY date(trade_date) DESC LIMIT 5
      2. Calls rows.reverse() so the feedback string is built oldest → newest
      3. Returns the formatted Performance Report Card string

    This ordering is critical: the AI must read history as a timeline ending
    on yesterday's actual result, not as a reverse-chronological dump that
    presents the most recent event as the oldest reference point.
    """
    section("PHASE 3 · HISTORICAL PERFORMANCE FEEDBACK RETRIEVAL")
    log_info("Querying memory vault for last 5 settled trades...")

    feedback = memory_vault.get_recent_performance_feedback()

    line_count = feedback.count("\n") + 1
    log_ok(f"Feedback payload ready ({line_count} lines, "
           f"{len(feedback)} chars)")
    log_info("Chronological order: OLDEST record first → YESTERDAY last ✔")
    section_end()
    return feedback


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN IGNITION SEQUENCE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    pipeline_start = time.time()
    banner()

    # ── Phase 1: Market time gate ──────────────────────────────────────────────
    # Halts and exits if the NSE pre-open auction is still in progress.
    # No further code executes on a pre-open condition.
    enforce_market_time_gate()

    # ── Phase 2: DB initialisation ────────────────────────────────────────────
    section("PHASE 2a · VAULT INITIALISATION")
    log_info("Ensuring database schema is current...")
    memory_vault.initialize_vault()
    log_ok("Vault schema verified and ready.")
    section_end()

    # ── Phase 3: True Open price acquisition ──────────────────────────────────
    open_price = get_true_open_price()
    if open_price is None:
        log_err("ABORTING: Could not acquire a valid Open price from NSE.")
        log_err("Verify market hours, ticker symbol, and network connectivity.")
        sys.exit(1)

    # ── Phase 4: Historical feedback retrieval ────────────────────────────────
    historical_feedback = get_historical_feedback()

    # ── Phase 5: Headline acquisition ─────────────────────────────────────────
    # sentiment_engine.fetch_top_headline() already contains its own telemetry
    # section headers so no wrapper section is needed here.
    headline = sentiment_engine.fetch_top_headline()

    # ── Phase 6: AI intelligence matrix generation ────────────────────────────
    # Passes the True Open (not Close, not live tick) as the price anchor.
    # sentiment_engine handles the retry loop, risk clamping, and extraction cascade.
    section("PHASE 6 · INTELLIGENCE MATRIX GENERATION")
    log_info("Routing to local AI cluster via LM Studio...")
    section_end()

    ai_matrix = sentiment_engine.analyze_market_intelligence(
        headline, open_price, historical_feedback
    )

    alpha_score     = ai_matrix.get("alpha_sentiment_score",  0.0)
    predicted_close = ai_matrix.get("ai_predicted_close",     open_price)
    reasoning       = ai_matrix.get("financial_impact_reasoning", "No reasoning returned.")

    # ── Phase 7: Vault write ───────────────────────────────────────────────────
    section("PHASE 7 · PREDICTION VAULT COMMIT")
    log_info(f"Alpha sentiment score : {alpha_score:+.2f}")
    log_info(f"Base price (True Open): ₹{open_price:.2f}")
    log_info(f"AI predicted close    : ₹{predicted_close:.2f}")
    log_info(f"Reasoning             : {reasoning[:110]}{'…' if len(reasoning) > 110 else ''}")

    memory_vault.log_morning_prediction(
        headline, alpha_score, open_price, predicted_close
    )

    log_ok("Prediction committed to vault successfully.")
    section_end()

    # ── Pipeline completion summary ────────────────────────────────────────────
    total_elapsed = round(time.time() - pipeline_start, 2)
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  ✔  MORNING IGNITION COMPLETE                                   ║")
    print(f"║     Runtime    : {total_elapsed:.2f}s" + " " * (47 - len(f"{total_elapsed:.2f}s")) + "║")
    print(f"║     Base Price : ₹{open_price:.2f}  (True NSE Open)" +
          " " * (36 - len(f"₹{open_price:.2f}  (True NSE Open)")) + "║")
    print(f"║     AI Target  : ₹{predicted_close:.2f}" +
          " " * (49 - len(f"₹{predicted_close:.2f}")) + "║")
    print(f"║     Alpha Score: {alpha_score:+.2f}" +
          " " * (49 - len(f"{alpha_score:+.2f}")) + "║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    print("║  ✅  Launch dashboard.py and leave LM Studio running.           ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()
