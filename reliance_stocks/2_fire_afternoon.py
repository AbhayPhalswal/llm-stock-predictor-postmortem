import console_setup  # noqa: F401  — must precede any print()
import sys
import time
from datetime import datetime

import pytz
import yfinance as yf

import market_calendar
import memory_vault

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║     AFTERNOON SETTLEMENT ENGINE  ·  V5.0  ·  NSE CLOSE-PRICE EXECUTION     ║
# ║     PnL Calculation  ·  Capital Vault Update  ·  AI Feedback Loop Write     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── MARKET TIME CONFIGURATION ─────────────────────────────────────────────────
IST               = pytz.timezone("Asia/Kolkata")
NSE_CLOSE_HOUR    = 15
NSE_CLOSE_MINUTE  = 30    # Settlement valid only after 15:30 IST
TICKER            = "RELIANCE.NS"


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

def log_pnl(msg: str):
    print(f"  [{_ts()} IST] 💰 PNL    ▸  {msg}")

def log_trade(msg: str):
    print(f"  [{_ts()} IST] 📊 TRADE  ▸  {msg}")

def section(title: str):
    bar = "─" * (64 - len(title) - 3)
    print(f"\n  ┌─ {title} {bar}")

def section_end():
    print("  └" + "─" * 65)

def banner():
    now_ist = datetime.now(IST).strftime("%Y-%m-%d  %H:%M:%S")
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║   📉  AFTERNOON SETTLEMENT ENGINE  ·  V5.0  ·  NSE CLOSE EXEC  ║")
    print(f"║   INIT: {now_ist} IST" + " " * (35 - len(now_ist)) + "║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — MARKET CLOSE TIME GATE
# ══════════════════════════════════════════════════════════════════════════════

def enforce_close_time_gate() -> None:
    """
    Validates that the current IST time is at or after 15:30 — the point at
    which NSE's continuous trading session ends and the official closing price
    is permanently printed on the daily candle.

    Executing before this window fetches an intra-day tick, not the official
    exchange close.  The error_variance written to the ledger would be wrong,
    poisoning tomorrow's AI calibration feedback.

    Exits with code 1 on pre-close detection so any calling scheduler can
    detect and re-queue.
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

    section("PHASE 1 · MARKET CLOSE TIME GATE VALIDATION")

    now_ist  = datetime.now(IST)
    gate_dt  = now_ist.replace(
        hour=NSE_CLOSE_HOUR, minute=NSE_CLOSE_MINUTE, second=0, microsecond=0
    )

    log_info(f"Current IST time  : {now_ist.strftime('%H:%M:%S')}")
    log_info(f"NSE close gate    : {gate_dt.strftime('%H:%M:%S')}")

    if now_ist < gate_dt:
        remaining        = gate_dt - now_ist
        mins, secs       = divmod(int(remaining.total_seconds()), 60)

        section_end()
        print()
        print("  ╔══════════════════════════════════════════════════════════════╗")
        print("  ║  🔴  MARKET SESSION STILL ACTIVE                            ║")
        print("  ║                                                              ║")
        print("  ║  The NSE continuous session has not yet closed.             ║")
        print("  ║  Settling now would write an intra-day tick, not the        ║")
        print("  ║  official closing price, corrupting the AI feedback loop.   ║")
        print("  ║                                                              ║")
        print(f"  ║  Please re-run settlement after 15:30 IST.                  ║")
        print(f"  ║  Time remaining until close gate: {mins:02d}m {secs:02d}s" +
              " " * (18 - len(f"{mins:02d}m {secs:02d}s")) + "║")
        print("  ╚══════════════════════════════════════════════════════════════╝")
        print()
        sys.exit(1)

    log_ok("Market close gate CLEAR — session ended. Official close available.")
    section_end()


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — OFFICIAL CLOSE PRICE ACQUISITION
# ══════════════════════════════════════════════════════════════════════════════

def get_official_close_price() -> float | None:
    """
    Fetches today's official NSE closing price for RELIANCE.NS.

    Uses the daily candle (period='1d', interval='1d') and reads
    data['Close'].iloc[-1].  This is the exchange-printed closing auction
    price, not a live 1-minute tick — important for P&L accuracy and for
    producing a clean error_variance that the AI can learn from tomorrow.

    Returns None on any fetch or data-shape failure so the caller can abort
    cleanly without writing bad data to the vault.
    """
    section("PHASE 2 · OFFICIAL CLOSE PRICE ACQUISITION")
    log_info(f"Ticker        : {TICKER}")
    log_info(f"Query window  : period=1d, interval=1d (official daily close)")

    t0 = time.time()
    try:
        ticker     = yf.Ticker(TICKER)
        daily_data = ticker.history(period="1d", interval="1d")

        if daily_data.empty:
            log_err("yfinance returned an empty DataFrame. "
                    "Verify ticker and network connectivity.")
            section_end()
            return None

        # Validate candle date is today in IST
        candle_date = daily_data.index[-1]
        try:
            candle_date_ist = candle_date.tz_convert(IST).date()
        except Exception:
            candle_date_ist = candle_date.date()

        today_ist = datetime.now(IST).date()
        if candle_date_ist != today_ist:
            log_warn(
                f"Candle date mismatch: got {candle_date_ist}, expected {today_ist}. "
                f"This may indicate a market holiday or a data feed lag."
            )

        close_price = round(float(daily_data["Close"].iloc[-1]), 2)
        latency_ms  = round((time.time() - t0) * 1000)

        log_ok(f"Official close acquired : ₹{close_price:.2f}  ({latency_ms}ms)")
        log_info(f"Candle date (IST)       : {candle_date_ist}")
        log_info(
            f"OHLC snapshot — "
            f"O: ₹{daily_data['Open'].iloc[-1]:.2f}  "
            f"H: ₹{daily_data['High'].iloc[-1]:.2f}  "
            f"L: ₹{daily_data['Low'].iloc[-1]:.2f}  "
            f"C: ₹{close_price:.2f}"
        )
        section_end()
        return close_price

    except Exception as exc:
        latency_ms = round((time.time() - t0) * 1000)
        log_err(f"Close price fetch failed after {latency_ms}ms: {exc}")
        section_end()
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 3 — VAULT QUERY & SETTLEMENT ELIGIBILITY
# ══════════════════════════════════════════════════════════════════════════════

def get_and_validate_todays_record() -> dict | None:
    """
    Fetches today's prediction row from the vault and validates settlement
    eligibility.

    Returns the row dict if the trade is open and eligible for settlement.
    Returns None (with descriptive logging) if:
      - No morning ignition was run today
      - The trade was already settled in a previous run
    """
    section("PHASE 3 · VAULT QUERY & SETTLEMENT ELIGIBILITY")

    today = datetime.now(IST).strftime("%Y-%m-%d")
    log_info(f"Querying vault for trade date: {today}")

    record = memory_vault.get_todays_prediction()

    if record is None:
        log_err(f"No prediction record found for {today}.")
        log_err("Run '1_fire_morning.py' first to seed today's base price.")
        section_end()
        return None

    if record["settled"] == 1:
        log_warn(f"Trade for {today} is already marked settled.")
        log_warn("Re-running settlement on an already-closed trade is a no-op.")
        section_end()
        return None

    log_ok(f"Open position confirmed for {today}.")
    log_info(f"Base price (Open anchor) : ₹{record['base_price']:.2f}")
    log_info(f"AI predicted close       : ₹{record['predicted_close']:.2f}")

    predicted_direction = "📈 BULLISH" if record["predicted_close"] > record["base_price"] \
                          else "📉 BEARISH / FLAT"
    log_info(f"AI signal direction      : {predicted_direction}")
    section_end()
    return record


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 4 — PNL EXECUTION & CAPITAL UPDATE
# ══════════════════════════════════════════════════════════════════════════════

def execute_pnl_and_settle(record: dict, actual_close: float) -> None:
    """
    Core settlement logic.  Implements the firm's algorithmic execution rules:

    LONG rule:
      If the AI predicted a close ABOVE the base price (bullish signal), the
      system simulates a full capital allocation at the open price.
        shares_deployed = floor(active_capital / base_price)
        leftover_cash   = active_capital % base_price   (undeployable remainder)
        proceeds        = shares_deployed * actual_close
        new_capital     = proceeds + leftover_cash
        pnl             = new_capital - active_capital

    SKIP rule:
      If the AI predicted flat or bearish, no position was taken.
      Capital is held in cash.  new_capital = active_capital.  pnl = 0.

    After execution:
      - error_variance = actual_close - predicted_close  (AI learning signal)
      - Both the ledger row and capital_profile are updated atomically via
        memory_vault.settle_trade() in a single WAL transaction.
    """
    section("PHASE 4 · PNL EXECUTION ENGINE")

    base_price      = record["base_price"]
    predicted_close = record["predicted_close"]
    active_capital  = memory_vault.get_active_capital()
    error_variance  = round(actual_close - predicted_close, 4)

    log_trade(f"Active capital in vault  : ₹{active_capital:>12,.2f}")
    log_trade(f"Base price (Open anchor) : ₹{base_price:>12,.2f}")
    log_trade(f"AI predicted close       : ₹{predicted_close:>12,.2f}")
    log_trade(f"Actual official close    : ₹{actual_close:>12,.2f}")
    log_trade(f"AI error variance        : {error_variance:>+12.4f} INR")

    ai_was_bullish = predicted_close > base_price

    if ai_was_bullish:
        # ── LONG execution ────────────────────────────────────────────────────
        shares_deployed = int(active_capital // base_price)
        leftover_cash   = active_capital % base_price
        proceeds        = shares_deployed * actual_close
        new_capital     = round(proceeds + leftover_cash, 2)
        pnl             = round(new_capital - active_capital, 2)

        log_trade(f"Position trigger         : 📈 LONG DEPLOYED")
        log_trade(f"Shares allocated         : {shares_deployed:>12,}")
        log_trade(f"Leftover cash            : ₹{leftover_cash:>12,.2f}")
        log_trade(f"Sale proceeds            : ₹{proceeds:>12,.2f}")

        if pnl >= 0:
            log_pnl(f"OUTCOME  ▸  🟢 PROFIT   : +₹{pnl:,.2f}")
        else:
            log_pnl(f"OUTCOME  ▸  🔴 LOSS     : -₹{abs(pnl):,.2f}")

    else:
        # ── SKIP — capital held in cash ───────────────────────────────────────
        new_capital = active_capital
        pnl         = 0.0

        log_trade(f"Position trigger         : ⏸️  TRADE SKIPPED")
        log_trade(f"Reason                   : AI signaled bearish/flat.")
        log_trade(f"Capital action           : Held 100% in cash.")
        log_pnl(  f"OUTCOME  ▸  ⚪ NEUTRAL  : ₹0.00 (capital safeguarded)")

    log_trade(f"New vault balance        : ₹{new_capital:>12,.2f}")

    # ── Atomic vault commit ───────────────────────────────────────────────────
    section("PHASE 5 · ATOMIC VAULT COMMIT")
    log_info("Writing settlement to ledger and capital_profile atomically...")

    t0 = time.time()
    memory_vault.settle_trade(
        actual_close=actual_close,
        new_capital=new_capital,
        pnl=pnl,
    )
    latency_ms = round((time.time() - t0) * 1000)

    log_ok(f"Vault commit complete ({latency_ms}ms).")
    log_ok(f"error_variance = {error_variance:+.4f} INR written to AI feedback loop.")
    log_ok(f"settled = 1 locked in reliance_ledger.")
    section_end()

    return new_capital, pnl


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    pipeline_start = time.time()
    banner()

    # ── Phase 1: Market close time gate ───────────────────────────────────────
    enforce_close_time_gate()

    # ── Phase 2: Vault initialisation safety check ────────────────────────────
    section("PHASE 2a · VAULT INITIALISATION SAFETY CHECK")
    memory_vault.initialize_vault()
    log_ok("WAL-enabled vault schema verified.")
    section_end()

    # ── Phase 3: Official close price ─────────────────────────────────────────
    actual_close = get_official_close_price()
    if actual_close is None:
        log_err("ABORTING: Could not acquire official close price from NSE.")
        sys.exit(1)

    # ── Phase 4: Vault record validation ──────────────────────────────────────
    record = get_and_validate_todays_record()
    if record is None:
        sys.exit(0)    # clean exit — already settled or no morning run

    # ── Phase 5: PnL execution and atomic settlement ──────────────────────────
    new_capital, pnl = execute_pnl_and_settle(record, actual_close)

    # ── Completion banner ──────────────────────────────────────────────────────
    total_elapsed = round(time.time() - pipeline_start, 2)
    pnl_label     = f"+₹{pnl:,.2f}" if pnl >= 0 else f"-₹{abs(pnl):,.2f}"
    pnl_icon      = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪")

    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  ✔  AFTERNOON SETTLEMENT COMPLETE                               ║")
    print(f"║     Runtime       : {total_elapsed:.2f}s" +
          " " * (44 - len(f"{total_elapsed:.2f}s")) + "║")
    print(f"║     Actual Close  : ₹{actual_close:.2f}" +
          " " * (45 - len(f"₹{actual_close:.2f}")) + "║")
    print(f"║     Session PnL   : {pnl_icon} {pnl_label}" +
          " " * (44 - len(f"{pnl_icon} {pnl_label}")) + "║")
    print(f"║     Vault Balance : ₹{new_capital:,.2f}" +
          " " * (45 - len(f"₹{new_capital:,.2f}")) + "║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    print("║  ✅  System resting. Resume tomorrow after 09:15 AM IST.        ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()