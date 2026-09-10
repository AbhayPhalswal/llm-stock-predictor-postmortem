import sqlite3
import os
from contextlib import contextmanager
from datetime import date, datetime

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║        MEMORY VAULT  ·  V5.0 ENTERPRISE  ·  WAL-ENABLED DATABASE CORE      ║
# ║        Write-Ahead Logging  ·  Concurrent Read/Write  ·  Fail-Safe Schema   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── PATH CONFIGURATION ────────────────────────────────────────────────────────
# Locks the database file to the exact directory containing this script.
# Every importing module resolves to the same physical file regardless of the
# working directory from which it is launched.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "trading_firm_memory.db")

# ── CONNECTION CONFIGURATION ──────────────────────────────────────────────────
DB_TIMEOUT = 30.0   # seconds — patient wait for any competing lock to release


# ══════════════════════════════════════════════════════════════════════════════
#  CONNECTION FACTORY
# ══════════════════════════════════════════════════════════════════════════════

def get_connection() -> sqlite3.Connection:
    """
    Returns a SQLite connection with two critical PRAGMAs applied immediately:

    WAL (Write-Ahead Logging):
      Decouples readers from writers at the OS level.  The dashboard can read
      every 10 seconds while alpha_scraper.py commits a write without either
      process blocking the other.  Under the default DELETE journal mode, any
      active reader causes a writer to receive SQLITE_BUSY instantly; WAL
      eliminates this entire class of collision.

    synchronous=NORMAL:
      Reduces fsync calls versus the default FULL mode while still guaranteeing
      data integrity after an OS crash.  Application-level crashes cannot
      corrupt the database.  Provides a measurable throughput improvement for
      the dashboard's high-frequency read loop without sacrificing durability.

    timeout=30.0:
      Forces every connection to wait up to 30 seconds for any residual lock
      before raising OperationalError.  This is the last line of defence for
      edge cases where WAL alone cannot eliminate contention (e.g. EXCLUSIVE
      lock during schema migration or VACUUM operations).
    """
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


@contextmanager
def vault():
    """
    Context manager that commits (or rolls back) AND closes the connection.

    sqlite3's own `with conn:` block only wraps the transaction — it never
    closes the handle.  Every `with vault() as conn:` in the previous
    version therefore leaked a file descriptor and a WAL reader slot on each
    call.  The dashboard's 10-second refresh loop made that leak unbounded.
    """
    conn = get_connection()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEMA INITIALISATION
# ══════════════════════════════════════════════════════════════════════════════

def initialize_vault() -> None:
    """
    Idempotent schema bootstrap.  Safe to call on every script startup —
    CREATE TABLE IF NOT EXISTS guarantees no data is overwritten on
    subsequent runs.

    Tables:
      reliance_ledger   — one row per trading day; stores morning prediction,
                          afternoon reality, and the error variance that feeds
                          tomorrow's AI calibration prompt.
      capital_profile   — append-only P&L log; each settled trade inserts a
                          new row so the full capital history is preserved and
                          auditable.

    Seeds capital_profile with ₹100,000 if the table is empty so the vault
    has a valid starting balance on first launch without requiring manual setup.
    """
    with vault() as conn:
        cursor = conn.cursor()

        # ── reliance_ledger ───────────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reliance_ledger (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date       TEXT    UNIQUE,
                headline         TEXT,
                alpha_sentiment  REAL,
                base_price       REAL,
                predicted_close  REAL,
                actual_close     REAL,
                error_variance   REAL,
                settled          INTEGER DEFAULT 0
            )
        """)

        # ── capital_profile ───────────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS capital_profile (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                active_capital REAL,
                last_updated   TEXT
            )
        """)

        # ── Seed initial capital if vault is empty ────────────────────────────
        cursor.execute("SELECT COUNT(*) FROM capital_profile")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO capital_profile (active_capital, last_updated) "
                "VALUES (?, ?)",
                (100_000.00, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )

        # ── Migration 1: realised PnL column ──────────────────────────────────
        # settle_trade() previously accepted a `pnl` argument and discarded it,
        # so per-trade P&L existed nowhere in the database and could only be
        # reconstructed by differencing consecutive capital_profile rows.
        cols = {row[1] for row in cursor.execute("PRAGMA table_info(reliance_ledger)")}
        if "realised_pnl" not in cols:
            cursor.execute("ALTER TABLE reliance_ledger ADD COLUMN realised_pnl REAL")

        # ── Migration 2: normalise legacy DD-MM-YYYY trade_date values ─────────
        # The V1 prototype wrote dates as DD-MM-YYYY.  SQLite's date() returns
        # NULL for that format, so those rows silently dropped out of every
        # "ORDER BY date(trade_date)" query — including the AI feedback window.
        cursor.execute("""
            SELECT id, trade_date FROM reliance_ledger
            WHERE date(trade_date) IS NULL AND trade_date IS NOT NULL
        """)
        for row_id, raw in cursor.fetchall():
            parts = raw.split("-")
            if len(parts) == 3 and len(parts[2]) == 4:
                iso = f"{parts[2]}-{parts[1]}-{parts[0]}"
                # Only rewrite if the ISO date is not already taken by another row
                cursor.execute(
                    "SELECT id FROM reliance_ledger WHERE trade_date = ?", (iso,)
                )
                clash = cursor.fetchone()
                if clash:
                    cursor.execute("DELETE FROM reliance_ledger WHERE id = ?", (row_id,))
                else:
                    cursor.execute(
                        "UPDATE reliance_ledger SET trade_date = ? WHERE id = ?",
                        (iso, row_id),
                    )

        # ── Migration 3: purge unsettled non-trading-day rows ─────────────────
        # Before the market-day gate existed, running ignition on a Saturday or
        # Sunday created a phantom ledger row anchored to the previous session's
        # candle.  Those rows can never settle; drop them.
        cursor.execute("SELECT id, trade_date FROM reliance_ledger WHERE settled = 0")
        for row_id, raw in cursor.fetchall():
            try:
                if date.fromisoformat(raw).weekday() >= 5:
                    cursor.execute("DELETE FROM reliance_ledger WHERE id = ?", (row_id,))
            except (ValueError, TypeError):
                continue

        conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  CAPITAL QUERIES
# ══════════════════════════════════════════════════════════════════════════════

def get_active_capital() -> float:
    """
    Returns the most recently written active capital balance.
    Falls back to the seed value of ₹100,000 if the table is somehow empty.
    """
    with vault() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT active_capital FROM capital_profile "
            "ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
    return row[0] if row else 100_000.00


def update_capital(new_capital: float) -> None:
    """
    Appends a new capital balance row.  The append-only design preserves the
    full equity curve for charting and audit purposes.
    """
    with vault() as conn:
        conn.execute(
            "INSERT INTO capital_profile (active_capital, last_updated) "
            "VALUES (?, ?)",
            (round(new_capital, 2), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  MORNING PREDICTION WRITE
# ══════════════════════════════════════════════════════════════════════════════

def log_morning_prediction(headline:       str,
                           alpha_score:    float,
                           base_price:     float,
                           predicted_close: float) -> None:
    """
    Upserts the morning AI prediction into today's ledger row.

    Uses INSERT … ON CONFLICT DO UPDATE so that if the morning ignition script
    is re-run on the same day (e.g. after a price feed hiccup) the row is
    refreshed rather than duplicated or rejected.

    settled is explicitly set to 0 on upsert to prevent accidentally marking
    an in-progress trade as closed if the script is re-run after 15:30.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    with vault() as conn:
        conn.execute("""
            INSERT INTO reliance_ledger
                (trade_date, headline, alpha_sentiment, base_price, predicted_close, settled)
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT(trade_date) DO UPDATE SET
                headline        = excluded.headline,
                alpha_sentiment = excluded.alpha_sentiment,
                base_price      = excluded.base_price,
                predicted_close = excluded.predicted_close
        """, (today, headline, alpha_score, base_price, predicted_close))
        conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  AFTERNOON SETTLEMENT WRITE
# ══════════════════════════════════════════════════════════════════════════════

def get_todays_prediction() -> dict | None:
    """
    Returns today's open (unsettled) prediction row as a dict, or None if no
    row exists for today or the trade has already been settled.

    The afternoon settlement script uses this to determine whether a position
    needs to be closed out.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    with vault() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, base_price, predicted_close, settled
            FROM   reliance_ledger
            WHERE  trade_date = ?
            ORDER BY id DESC LIMIT 1
        """, (today,))
        row = cursor.fetchone()

    if not row:
        return None

    return {
        "id":              row[0],
        "base_price":      row[1],
        "predicted_close": row[2],
        "settled":         row[3],
    }


def settle_trade(actual_close: float,
                 new_capital:  float,
                 pnl:          float) -> None:
    """
    Atomically finalises the day's trading record.

    In a single transaction:
      1. Writes actual_close, error_variance, realised_pnl and settled=1 to
         reliance_ledger.
      2. Appends the post-trade capital balance to capital_profile.

    The atomic transaction ensures the dashboard never reads a partially-settled
    state (e.g. capital updated but ledger not yet marked settled).
    """
    today = datetime.now().strftime("%Y-%m-%d")

    with vault() as conn:
        cursor = conn.cursor()

        # Fetch predicted_close to calculate error_variance inside the transaction
        cursor.execute("""
            SELECT predicted_close FROM reliance_ledger
            WHERE  trade_date = ?
            ORDER BY id DESC LIMIT 1
        """, (today,))
        row = cursor.fetchone()
        predicted_close = row[0] if row else actual_close
        error_variance  = round(actual_close - predicted_close, 4)

        cursor.execute("""
            UPDATE reliance_ledger
               SET actual_close    = ?,
                   error_variance  = ?,
                   realised_pnl    = ?,
                   settled         = 1
             WHERE trade_date      = ?
        """, (actual_close, error_variance, round(pnl, 2), today))

        cursor.execute("""
            INSERT INTO capital_profile (active_capital, last_updated)
            VALUES (?, ?)
        """, (round(new_capital, 2), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  HISTORICAL PERFORMANCE FEEDBACK  (AI CALIBRATION FEED)
# ══════════════════════════════════════════════════════════════════════════════

def get_recent_performance_feedback() -> str:
    """
    Builds the Historical Performance Report Card string consumed by the
    morning ignition AI prompt.

    Query logic:
      ORDER BY date(trade_date) DESC LIMIT 5 — fetches the 5 most recent
      settled records efficiently via the index.

      rows.reverse() — flips the list in Python so the feedback string is
      written OLDEST → NEWEST.  This is the Chronological Amnesia Patch:
      without the reverse, the AI reads yesterday's result as the oldest
      data point and 5-days-ago as the most recent, inverting the error
      trend vector it needs to correct against.

    Returns a neutral baseline string rather than an empty string when the
    vault has no history, so the AI prompt is always structurally valid.
    """
    with vault() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT trade_date, predicted_close, actual_close, error_variance
            FROM   reliance_ledger
            WHERE  settled = 1
              AND  predicted_close IS NOT NULL
              AND  actual_close    IS NOT NULL
              AND  error_variance  IS NOT NULL
            ORDER BY date(trade_date) DESC
            LIMIT 5
        """)
        rows = cursor.fetchall()

    if not rows:
        return (
            "No historical prediction error logs found. "
            "This is your baseline initial run."
        )

    # ── Chronological Amnesia Patch ───────────────────────────────────────────
    # DESC query returns newest-first; reverse to oldest-first before building
    # the string so the AI reads the timeline in correct chronological order.
    rows.reverse()

    lines = [
        "HISTORICAL PERFORMANCE REPORT CARD "
        "(Use this to calibrate today's risk parameters):"
    ]
    for row in rows:
        lines.append(
            f"  · Date: {row[0]}  |  "
            f"Predicted: ₹{row[1]:.2f}  |  "
            f"Actual: ₹{row[2]:.2f}  |  "
            f"Error Margin: {row[3]:+.4f} INR"
        )

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD READ HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_all_settled_trades() -> list[tuple]:
    """
    Returns all settled trade rows in strict ascending date order for the
    dashboard's chart and ledger renderers.

    Columns returned: (trade_date, predicted_close, actual_close, error_variance)
    """
    with vault() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT trade_date, predicted_close, actual_close, error_variance
            FROM   reliance_ledger
            WHERE  settled = 1
              AND  predicted_close IS NOT NULL
              AND  actual_close    IS NOT NULL
              AND  error_variance  IS NOT NULL
            ORDER BY date(trade_date) ASC
        """)
        return cursor.fetchall()


def get_todays_open_prediction() -> tuple | None:
    """
    Returns (base_price, predicted_close, settled) for today's active row,
    or None if no row exists for today.

    Used by the dashboard's refresh loop to set the AI target label and
    determine whether to display an active position.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    with vault() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT base_price, predicted_close, settled
            FROM   reliance_ledger
            WHERE  trade_date = ?
            ORDER BY id DESC LIMIT 1
        """, (today,))
        return cursor.fetchone()


def get_alpha_news_archive(limit: int = 15) -> list[tuple]:
    """
    Returns the most recent headlines from the ledger for the Alpha News
    Matrix popup window, newest first.

    Columns returned: (trade_date, headline)
    """
    with vault() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT trade_date, headline
            FROM   reliance_ledger
            WHERE  headline IS NOT NULL
              AND  headline != 'No headline captured.'
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        return cursor.fetchall()