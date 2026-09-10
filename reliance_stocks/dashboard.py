"""
RELIANCE QUANTITATIVE ENGINE  ·  V10.0
Apple-minimal Flet dark UI  ·  GPU canvas chart  ·  WAL-DB ready

flet 0.85+ guardrails applied:
  cv.Text   →  value="str", style=ft.TextStyle(...)   [NO ft.Text widgets in canvas]
  Buttons   →  ft.Button only                         [NO ElevatedButton]
  Anims     →  ft.Animation(...)                      [NO ft.animation.Animation]
  Entry     →  ft.run(main)                           [NO ft.app]
"""

import console_setup  # noqa: F401  — must precede any print()

import flet as ft
import flet.canvas as cv
import threading
import time
import random
import math
from datetime import datetime

import memory_vault

# ══ PALETTE ═══════════════════════════════════════════════════════════════════
BLACK  = "#000000"    # void-black page / chart bg
CARD   = "#0A0A0C"    # card surfaces — just barely not black
TILE   = "#111113"    # alpha matrix tile bg
CYAN   = "#00F0FF"    # predictions / accents
GREEN  = "#00FF66"    # gains / buy
RED    = "#FF2A55"    # losses / liquidation
WHITE  = "#FFFFFF"    # primary text
DIM    = "#888899"    # secondary labels
GHOST  = "#1E1E2E"    # grid lines / very subtle separators
G_BUY  = "#0D1A0D"   # green-tinted button bg
G_SELL = "#1A0D0D"   # red-tinted button bg

# ══ SYSTEM MANUAL SOP ════════════════════════════════════════════════════════
MANUAL_SOP = """
RELIANCE QUANTITATIVE ENGINE  ·  V10.0
STANDARD OPERATING PROCEDURE

STEP 1  ·  BOOT LM STUDIO  (before 09:15 IST)
  Start local inference server — http://localhost:1234/v1
  LM Studio must stay running ALL DAY.
  Morning ignition, midday scraper, and this dashboard
  all route intelligence requests through it.

STEP 2  ·  MORNING IGNITION  (after 09:15 IST)
  python 1_fire_morning.py
  · Enforces IST time gate (will abort if pre-open)
  · Fetches true NSE Open price from daily candle
  · Pulls last-5-day settled trades for AI calibration
  · Submits headline + history to LM Studio
  · Applies ±3.5% risk clamp to hallucinated deltas
  · Writes prediction to SQLite WAL vault

STEP 3  ·  ALPHA SCRAPER  (11:00 – 14:00 IST)
  python alpha_scraper.py
  · 4-source Google News RSS aggregation
  · Fingerprint deduplication & signal ranking
  · Re-scores top-3 headlines via LM Studio
  · Injects alpha sentiment score to vault row

STEP 4  ·  MONITOR DASHBOARD  (all day)
  python dashboard_flet.py
  · 2-second heartbeat: live tick + order book + PnL
  · 10-second gate: vault DB + ledger + chart refresh
  · MARKET BUY  →  deploys full capital at live price
  · LIQUIDATE   →  closes position, logs PnL receipt
  · Alpha Matrix → 14-Day RSI, EMA Δ, Vol Surge, ATR
  · Full canvas chart with GPU-rasterised path drawing

STEP 5  ·  AFTERNOON SETTLEMENT  (after 15:30 IST)
  python 2_fire_afternoon.py
  · Enforces 15:30 IST gate
  · Fetches official NSE closing price
  · Calculates & commits realised PnL to vault
  · Writes error_variance for tomorrow's AI calibration

DATABASE
  File: trading_firm_memory.db  (same directory)
  PRAGMA journal_mode=WAL  — concurrent reads/writes
  PRAGMA synchronous=NORMAL — safe fast commits

TROUBLESHOOTING
  AI offline        →  start LM Studio server
  No prediction     →  run morning ignition first
  Stale capital     →  click SYNC or wait 10-s gate
  Empty chart       →  no settled trades yet
  Pre-open warning  →  before 09:15 IST; re-run after gate
"""


# ══════════════════════════════════════════════════════════════════════════════
class QuantEngine:
    """
    Single-class architecture for V10.0.
    State → build() → background worker → UI mutations → page.update().
    """

    # ── INIT ──────────────────────────────────────────────────────────────────
    def __init__(self):
        # live market state
        self.live_price     : float = 1295.40
        self.entry_price    : float = 0.0
        self.active_shares  : int   = 0
        self.cash_remainder : float = 0.0
        self.is_long        : bool  = False
        self.stop_loss_pct  : float = 2.0
        self.active_capital : float = 100_000.0
        self.target_price   : float = 1312.00
        self.latency_ms     : int   = 12

        # True once the live price has been anchored to a real vault base price.
        # Until then live_price is the placeholder constant above.
        self._price_anchored : bool = False

        # alpha matrix — populated by pandas-ta [BACKEND HOOK]
        self.rsi14     : float = 62.4
        self.ema_delta : float = 0.72    # % change
        self.vol_surge : float = 2.3     # multiple of 20-day avg
        self.atr14     : float = 18.5

        # chart history — (date_str, predicted, actual, error_var)
        # [BACKEND HOOK] memory_vault.get_all_settled_trades()
        self.chart_history : list = self._seed_history()

        # order book
        self.ob_bids : list = []
        self.ob_asks : list = []

        # ledger pagination
        self.ledger_page : int = 0
        self.page_size   : int = 15

        # event log
        self.log_lines : list = []

        # Flet page ref
        self.page     : ft.Page = None
        self._running : bool    = False

        # chart canvas dimensions (updated on resize)
        self.chart_w : float = 700.0
        self.chart_h : float = 290.0

        # ── control references (set in build) ─────────────────────────────
        self.lbl_capital     : ft.Text         = None
        self.lbl_capital_sub : ft.Text         = None
        self.lbl_tick        : ft.Text         = None
        self.lbl_target      : ft.Text         = None
        self.lbl_pnl         : ft.Text         = None
        self.lbl_pnl_sub     : ft.Text         = None
        self.lbl_latency     : ft.Text         = None
        self.lbl_session     : ft.Text         = None
        self.lbl_sl          : ft.Text         = None
        self.exp_bar         : ft.ProgressBar  = None

        # alpha matrix
        self.lbl_rsi : ft.Text = None
        self.lbl_ema : ft.Text = None
        self.lbl_vol : ft.Text = None
        self.lbl_atr : ft.Text = None

        # chart
        self.chart_canvas : cv.Canvas = None

        # order book
        self.ob_col : ft.Column = None

        # ledger
        self.ledger_tbl : ft.DataTable = None
        self.lbl_page   : ft.Text      = None
        self.btn_prev   : ft.Button    = None
        self.btn_next   : ft.Button    = None

        # event log column
        self.log_col : ft.Column = None

    # ══ DATA SEEDING ══════════════════════════════════════════════════════════

    def _seed_history(self) -> list:
        """
        Loads real settled trades from the vault.

        Returns: list of (date_str, predicted_close, actual_close, error_var)

        Previously this synthesised 40 rows of random walk, so the chart and the
        ledger below it showed invented numbers that had no relationship to the
        capital figure displayed beside them. Returns an empty list when the
        vault has no settled trades yet — the chart renders its own empty state.
        """
        try:
            memory_vault.initialize_vault()
            return memory_vault.get_all_settled_trades()
        except Exception as exc:
            print(f"[dashboard] vault read failed: {exc}")
            return []

    def _simulate_tick(self) -> float:
        """
        SIMULATED price tick — a random walk, NOT live market data.

        The walk is anchored to today's real base price by _refresh_from_vault()
        on the first sync, but every tick after that is invented. Anything the
        dashboard derives from live_price — unrealised PnL, the order book, the
        stop-loss trigger, MARKET BUY fills — is therefore simulated too.

        To make this real, replace the body with:
            ticker = yf.Ticker("RELIANCE.NS")
            data   = ticker.history(period="1d", interval="1m")
            return float(data["Close"].iloc[-1]) if not data.empty else self.live_price
        and throttle the 2-second heartbeat — yfinance will rate-limit at that
        frequency.
        """
        return round(max(1150.0, self.live_price + random.gauss(0, 0.28)), 2)

    def _refresh_alpha(self):
        """
        [BACKEND HOOK] Replace with pandas-ta calculations:
            self.rsi14     = float(df.ta.rsi(length=14).iloc[-1])
            ema5           = df.ta.ema(length=5)
            self.ema_delta = float((ema5.iloc[-1] / ema5.iloc[-6] - 1) * 100)
            self.vol_surge = float(df["Volume"].iloc[-1] /
                                   df["Volume"].rolling(20).mean().iloc[-1])
            self.atr14     = float(df.ta.atr(length=14).iloc[-1])
        """
        self.rsi14     = max(10.0, min(90.0, self.rsi14 + random.gauss(0, 0.5)))
        self.ema_delta = self.ema_delta + random.gauss(0, 0.04)
        self.vol_surge = max(0.3, self.vol_surge + random.gauss(0, 0.03))
        self.atr14     = max(3.0, self.atr14 + random.gauss(0, 0.12))

    # ══ BACKGROUND WORKER ═════════════════════════════════════════════════════

    def _start_worker(self):
        self._running = True
        self.page.run_thread(self._worker_loop)

    def _worker_loop(self):
        """
        2-second heartbeat  — live tick, order book, PnL, alpha matrix.
        10-second gate (×5) — vault DB refresh, chart, ledger.
        All UI mutations pass through _push_state() → page.update().
        """
        beat = 0
        while self._running:
            try:
                # ── 2 s: live market state ─────────────────────────────────
                self.live_price = self._simulate_tick()
                self._rebuild_ob()
                self._refresh_alpha()

                # auto stop-loss
                if self.is_long and self.entry_price > 0:
                    bail = self.entry_price * (1 - self.stop_loss_pct / 100.0)
                    if self.live_price <= bail:
                        self._execute_liquidation(auto=True)

                self._push_live_state()

                # ── 10 s: vault + chart + ledger ───────────────────────────
                beat += 1
                if beat % 5 == 0:
                    self._refresh_from_vault()
                    self._rebuild_chart()
                    self._rebuild_ledger()

                self.latency_ms = random.randint(7, 29)
                time.sleep(2)

            except Exception as exc:
                self._log(f"WORKER ERROR: {exc}")
                time.sleep(5)

    def _refresh_from_vault(self):
        """
        Pulls authoritative state out of the SQLite vault.

        Called on the dashboard's 10-second gate and by the SYNC button. This is
        the only path by which capital and the AI target reach the UI — they are
        owned by 1_fire_morning.py and 2_fire_afternoon.py, never by this
        process.
        """
        try:
            self.active_capital = memory_vault.get_active_capital()
            self.chart_history  = memory_vault.get_all_settled_trades()

            row = memory_vault.get_todays_open_prediction()
            if row:
                base_price, predicted_close, _settled = row
                if predicted_close is not None:
                    self.target_price = predicted_close
                # Anchor the simulated tick to today's real base price on the
                # first sync so the display does not start from a stale constant.
                if not self._price_anchored and base_price:
                    self.live_price      = float(base_price)
                    self._price_anchored = True

            if not self.is_long and self.lbl_capital:
                self.lbl_capital.value = f"{self.active_capital:,.2f}"
        except Exception as exc:
            self._log(f"VAULT READ FAILED: {exc}")

    # ── LIVE STATE PUSH ───────────────────────────────────────────────────────

    def _push_live_state(self):
        """Mutate all live-tick labels then call page.update() once."""
        if not self.page:
            return
        try:
            self.lbl_tick.value    = f"{self.live_price:,.2f}"
            self.lbl_latency.value = f"🟢 {self.latency_ms}ms"
            self.lbl_target.value  = f"AI TARGET  {self.target_price:,.2f}"

            # session countdown
            now    = datetime.now()
            close  = now.replace(hour=15, minute=30, second=0, microsecond=0)
            if now < close:
                diff      = close - now
                h, rem    = divmod(int(diff.total_seconds()), 3600)
                m, s      = divmod(rem, 60)
                self.lbl_session.value = f"SESSION  {h:02d}:{m:02d}:{s:02d}"
            else:
                self.lbl_session.value = "SESSION CLOSED"

            # PnL
            self._push_pnl()

            # alpha matrix
            self._push_alpha()

            # order book bars
            self._push_ob_ui()

            self.page.update()
        except Exception:
            pass

    # ══ ALPHA MATRIX ══════════════════════════════════════════════════════════

    def _push_alpha(self):
        if self.lbl_rsi is None:
            return
        self.lbl_rsi.value = f"{self.rsi14:.1f}"
        self.lbl_rsi.color = GREEN if self.rsi14 > 50 else RED

        self.lbl_ema.value = f"{self.ema_delta:+.2f}%"
        self.lbl_ema.color = GREEN if self.ema_delta >= 0 else RED

        self.lbl_vol.value = f"{self.vol_surge:.1f}×"
        self.lbl_vol.color = CYAN if self.vol_surge > 1.5 else WHITE

        self.lbl_atr.value = f"{self.atr14:.1f}"
        self.lbl_atr.color = DIM

    # ══ GPU CANVAS CHART ══════════════════════════════════════════════════════

    def _on_chart_resize(self, e: cv.CanvasResizeEvent):
        self.chart_w = max(200.0, e.width)
        self.chart_h = max(80.0,  e.height)
        self._rebuild_chart()
        if self.page:
            self.page.update()

    def _build_chart_shapes(self) -> list:
        """
        GPU-rasterised line chart drawn entirely via flet.canvas primitives.

        Guardrails strictly observed:
          cv.Text(value="str", style=ft.TextStyle(...))  — NO ft.Text widgets
          X-axis labels are sparse (≤ 8) — no overlap at any data depth
          Y-axis labels use 3 evenly-spaced price ticks
        """
        shapes = []
        data   = self.chart_history
        W, H   = self.chart_w, self.chart_h

        if not data:
            shapes.append(cv.Text(
                x=W / 2, y=H / 2,
                value="No historical data available.",
                style=ft.TextStyle(size=12, color=DIM),
                alignment=ft.Alignment(x=0, y=0),
            ))
            return shapes

        n       = len(data)
        actuals = [r[2] for r in data]
        preds   = [r[1] for r in data]
        all_v   = actuals + preds
        y_min   = min(all_v)
        y_max   = max(all_v)
        y_rng   = (y_max - y_min) or 1.0

        # layout margins
        PAD_L = 54.0
        PAD_R = 10.0
        PAD_T = 18.0
        PAD_B = 34.0
        cw     = W - PAD_L - PAD_R
        ch     = H - PAD_T - PAD_B

        # coordinate transforms
        def px(i: int) -> float:
            return PAD_L + (i / max(n - 1, 1)) * cw

        def py(v: float) -> float:
            margin = y_rng * 0.07
            lo = y_min - margin
            hi = y_max + margin
            return PAD_T + ch - ((v - lo) / (hi - lo)) * ch

        # ── subtle grid lines ─────────────────────────────────────────────
        grid_paint = ft.Paint(
            color=GHOST, stroke_width=0.7, style=ft.PaintingStyle.STROKE
        )
        for q in [0.0, 0.33, 0.67, 1.0]:
            y = PAD_T + q * ch
            shapes.append(cv.Line(PAD_L, y, PAD_L + cw, y, paint=grid_paint))

        # ── Y-axis price labels (3 ticks) ────────────────────────────────
        # GUARDRAIL: cv.Text with value= string and style=ft.TextStyle(...)
        for q in [0.0, 0.5, 1.0]:
            price = y_min + q * y_rng
            y     = py(price)
            shapes.append(cv.Text(
                x=PAD_L - 6,
                y=y,
                value=f"{price:.0f}",
                style=ft.TextStyle(size=9, color=DIM, font_family="Consolas"),
                alignment=ft.Alignment(x=1, y=0),
            ))

        # ── fill between lines ────────────────────────────────────────────
        fill_elems = [cv.Path.MoveTo(px(0), py(actuals[0]))]
        for i in range(1, n):
            fill_elems.append(cv.Path.LineTo(px(i), py(actuals[i])))
        for i in range(n - 1, -1, -1):
            fill_elems.append(cv.Path.LineTo(px(i), py(preds[i])))
        fill_elems.append(cv.Path.Close())
        shapes.append(cv.Path(
            elements=fill_elems,
            paint=ft.Paint(color="#071C2E", style=ft.PaintingStyle.FILL),
        ))

        # ── AI Prediction line — muted dashed ────────────────────────────
        pred_elems = [cv.Path.MoveTo(px(0), py(preds[0]))]
        for i in range(1, n):
            pred_elems.append(cv.Path.LineTo(px(i), py(preds[i])))
        shapes.append(cv.Path(
            elements=pred_elems,
            paint=ft.Paint(
                color="#445566",
                stroke_width=1.6,
                stroke_dash_pattern=[6, 4],
                stroke_cap=ft.StrokeCap.ROUND,
                style=ft.PaintingStyle.STROKE,
            ),
        ))

        # ── Actual Reality line — cyan solid ──────────────────────────────
        act_elems = [cv.Path.MoveTo(px(0), py(actuals[0]))]
        for i in range(1, n):
            act_elems.append(cv.Path.LineTo(px(i), py(actuals[i])))
        shapes.append(cv.Path(
            elements=act_elems,
            paint=ft.Paint(
                color=CYAN,
                stroke_width=2.3,
                stroke_cap=ft.StrokeCap.ROUND,
                stroke_join=ft.StrokeJoin.ROUND,
                style=ft.PaintingStyle.STROKE,
            ),
        ))

        # ── dots on actual series ─────────────────────────────────────────
        dot_paint = ft.Paint(color=CYAN, style=ft.PaintingStyle.FILL)
        for i in range(n):
            shapes.append(cv.Circle(px(i), py(actuals[i]), 2.8, paint=dot_paint))

        # ── X-axis sparse date labels (≤ 8) ──────────────────────────────
        # GUARDRAIL: cv.Text with value= string and style=ft.TextStyle(...)
        step    = max(1, n // 8)
        indices = list(range(0, n, step))
        if (n - 1) not in indices:
            indices.append(n - 1)
        for i in indices:
            shapes.append(cv.Text(
                x=px(i),
                y=H - 2,
                value=data[i][0][-5:],
                style=ft.TextStyle(size=9, color=DIM, font_family="Consolas"),
                alignment=ft.Alignment(x=0, y=1),
            ))

        # ── legend swatches ───────────────────────────────────────────────
        shapes.append(cv.Rect(
            x=PAD_L, y=2, width=14, height=4,
            paint=ft.Paint(color=CYAN, style=ft.PaintingStyle.FILL),
        ))
        shapes.append(cv.Text(
            x=PAD_L + 18, y=4,
            value="Actual Reality",
            style=ft.TextStyle(size=9, color=DIM, font_family="Consolas"),
            alignment=ft.Alignment(x=-1, y=0),
        ))
        shapes.append(cv.Rect(
            x=PAD_L + 114, y=2, width=14, height=4,
            paint=ft.Paint(color="#445566", style=ft.PaintingStyle.FILL),
        ))
        shapes.append(cv.Text(
            x=PAD_L + 132, y=4,
            value="AI Prediction",
            style=ft.TextStyle(size=9, color=DIM, font_family="Consolas"),
            alignment=ft.Alignment(x=-1, y=0),
        ))

        return shapes

    def _rebuild_chart(self):
        if self.chart_canvas:
            self.chart_canvas.shapes = self._build_chart_shapes()

    # ══ ORDER BOOK ════════════════════════════════════════════════════════════

    def _rebuild_ob(self):
        """Simulate bid/ask depth around live_price."""
        ref  = self.live_price
        half = ref * random.uniform(0.0003, 0.0011) / 2
        tick = ref * 0.00014
        base = random.randint(400, 1800)
        self.ob_bids, self.ob_asks = [], []
        for i in range(8):
            vol = int(base * math.exp(-i * 0.42) * random.uniform(0.65, 1.35))
            self.ob_bids.append((round(ref - half - i * tick, 2), vol))
            self.ob_asks.append((round(ref + half + i * tick, 2), vol))

    def _push_ob_ui(self):
        """Rebuild order-book rows inside ob_col."""
        if not self.ob_col:
            return
        max_vol = max((v for _, v in self.ob_bids + self.ob_asks), default=1)
        BAR_MAX = 100   # px

        rows = []
        for i in range(min(7, len(self.ob_bids))):
            bp, bv = self.ob_bids[i]
            ap, av = self.ob_asks[i]
            bw = max(3, int(BAR_MAX * bv / max_vol))
            aw = max(3, int(BAR_MAX * av / max_vol))

            rows.append(ft.Row(
                controls=[
                    # bid price
                    ft.Text(f"{bp:,.2f}", size=10, color=CYAN,
                            font_family="Consolas", width=70,
                            text_align=ft.TextAlign.RIGHT),
                    ft.Container(width=6),
                    # bid bar (right-aligned within fixed container)
                    ft.Container(
                        width=BAR_MAX,
                        content=ft.Row(
                            controls=[
                                ft.Container(expand=True),
                                ft.Container(
                                    bgcolor=CYAN, height=5,
                                    border_radius=3, width=bw,
                                ),
                            ],
                            spacing=0, tight=True,
                        ),
                    ),
                    # mid gap
                    ft.Container(
                        width=14,
                        content=ft.Container(
                            width=5, height=5, bgcolor=GHOST,
                            border_radius=3,
                        ),
                        alignment=ft.Alignment(x=0, y=0),
                    ),
                    # ask bar (left-aligned)
                    ft.Container(
                        width=BAR_MAX,
                        content=ft.Container(
                            bgcolor=RED, height=5,
                            border_radius=3, width=aw,
                        ),
                    ),
                    ft.Container(width=6),
                    # ask price
                    ft.Text(f"{ap:,.2f}", size=10, color=RED,
                            font_family="Consolas", width=70),
                ],
                spacing=0,
            ))

        self.ob_col.controls = rows

    # ══ LEDGER ════════════════════════════════════════════════════════════════

    def _rebuild_ledger(self):
        if not self.ledger_tbl:
            return
        display     = list(reversed(self.chart_history))   # newest first
        total       = len(display)
        pages       = max(1, (total + self.page_size - 1) // self.page_size)
        self.ledger_page = max(0, min(self.ledger_page, pages - 1))

        start = self.ledger_page * self.page_size
        chunk = display[start : start + self.page_size]

        self.ledger_tbl.rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(r[0], size=11, color=DIM,
                                     font_family="Consolas")),
                ft.DataCell(ft.Text(f"{r[1]:,.2f}", size=11, color=CYAN,
                                     font_family="Consolas")),
                ft.DataCell(ft.Text(f"{r[2]:,.2f}", size=11, color=WHITE,
                                     font_family="Consolas")),
                ft.DataCell(ft.Text(
                    f"{r[3]:+.4f}",
                    size=11,
                    weight=ft.FontWeight.W_600,
                    font_family="Consolas",
                    color=GREEN if r[3] > 0 else (RED if r[3] < 0 else DIM),
                )),
            ])
            for r in chunk
        ]
        self.lbl_page.value    = f"PAGE  {self.ledger_page + 1}  /  {pages}"
        self.btn_prev.disabled = self.ledger_page <= 0
        self.btn_next.disabled = self.ledger_page >= pages - 1

    def _on_prev_page(self, e):
        if self.ledger_page > 0:
            self.ledger_page -= 1
            self._rebuild_ledger()
            self.page.update()

    def _on_next_page(self, e):
        total = len(self.chart_history)
        pages = max(1, (total + self.page_size - 1) // self.page_size)
        if self.ledger_page < pages - 1:
            self.ledger_page += 1
            self._rebuild_ledger()
            self.page.update()

    # ══ PNL ═══════════════════════════════════════════════════════════════════

    def _push_pnl(self):
        if not self.is_long or self.active_shares <= 0:
            return
        pnl   = (self.live_price - self.entry_price) * self.active_shares
        color = GREEN if pnl >= 0 else RED
        tag   = "▲" if pnl >= 0 else "▼"
        self.lbl_pnl.value     = f"{tag}  {abs(pnl):,.2f}"
        self.lbl_pnl.color     = color
        self.lbl_pnl_sub.value = (
            f"{self.active_shares:,} shs  ·  "
            f"entry {self.entry_price:,.2f}  ·  "
            f"live {self.live_price:,.2f}"
        )

    def _clear_pnl(self):
        self.lbl_pnl.value     = "—"
        self.lbl_pnl.color     = DIM
        self.lbl_pnl_sub.value = "No active position"

    # ══ EXECUTION ════════════════════════════════════════════════════════════

    def _on_buy(self, e):
        """
        Deploys the vault's real capital at the current live price.

        Capital is re-read from the vault immediately before sizing so the order
        cannot be sized against a stale in-memory figure that a settlement run
        has since superseded.
        """
        try:
            self.active_capital = memory_vault.get_active_capital()
        except Exception as exc:
            self._log(f"BUY ABORTED: vault unreadable ({exc})"); return

        price = self.live_price
        if price <= 0:
            self._log("BUY ABORTED: price unavailable"); return
        shares = int(self.active_capital // price)
        if shares <= 0:
            self._log("BUY ABORTED: insufficient capital"); return

        self.active_shares  = shares
        self.cash_remainder = self.active_capital - shares * price
        self.entry_price    = price
        self.is_long        = True

        stop_p = price * (1 - self.stop_loss_pct / 100)
        self._log(f"BUY  {shares:,} × {price:,.2f}  =  {shares*price:,.2f}")
        self._log(f"STOP-LOSS ARMED @ {stop_p:,.2f}")

        if self.lbl_capital_sub:
            self.lbl_capital_sub.value = (
                f"95% deployed  ·  {shares:,} shares @ {price:,.2f}"
            )
        if self.exp_bar:
            self.exp_bar.value = 0.95
        self.page.update()

    def _on_liquidate(self, e):
        self._execute_liquidation(auto=False)

    def _execute_liquidation(self, auto: bool):
        if not self.is_long or self.active_shares <= 0:
            return
        exit_p   = self.live_price
        pnl      = (exit_p - self.entry_price) * self.active_shares
        proceeds = self.active_shares * exit_p
        new_cap  = round(proceeds + self.cash_remainder, 2)

        try:
            memory_vault.update_capital(new_cap)
        except Exception as exc:
            self._log(f"WARNING: capital NOT persisted to vault ({exc})")
        self.active_capital = new_cap

        tag = "AUTO-LIQ" if auto else "LIQUIDATE"
        pl  = "PROFIT" if pnl >= 0 else "LOSS"
        self._log(f"{tag}  {self.active_shares:,} × {exit_p:,.2f}")
        self._log(f"{pl}  {pnl:+,.2f}  →  CAPITAL  {new_cap:,.2f}")

        self.is_long        = False
        self.active_shares  = 0
        self.cash_remainder = 0.0
        self.entry_price    = 0.0

        if self.lbl_capital:
            self.lbl_capital.value     = f"{new_cap:,.2f}"
        if self.lbl_capital_sub:
            self.lbl_capital_sub.value = "100% cash"
        if self.exp_bar:
            self.exp_bar.value = 0.0
        self._clear_pnl()
        if self.page:
            self.page.update()

    def _on_sl_change(self, e):
        self.stop_loss_pct = round(e.control.value, 1)
        risk = "SAFE" if self.stop_loss_pct < 2.5 else "HIGH RISK"
        if self.lbl_sl:
            self.lbl_sl.value = f"{self.stop_loss_pct}%  stop-loss  ·  {risk}"
            self.page.update()

    def _on_sync(self, e):
        """Force an immediate vault re-read rather than waiting for the 10s gate."""
        self._log("FORCE SYNC triggered")
        self._refresh_from_vault()
        if self.lbl_capital:
            self.lbl_capital.value = f"{self.active_capital:,.2f}"
        self._rebuild_chart()
        self._rebuild_ledger()
        self.page.update()

    # ══ EVENT LOG ════════════════════════════════════════════════════════════

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_lines.insert(0, f"[{ts}]  {msg}")
        if len(self.log_lines) > 100:
            self.log_lines = self.log_lines[:100]
        if self.log_col:
            self.log_col.controls = [
                ft.Text(line, size=10, color=DIM, font_family="Consolas")
                for line in self.log_lines[:10]
            ]

    # ══ SYSTEM MANUAL ═════════════════════════════════════════════════════════

    def _on_manual(self, e):
        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=CARD,
            title=ft.Text(
                "V10.0  ·  SYSTEM MANUAL",
                size=15, color=WHITE,
                weight=ft.FontWeight.W_300,
                font_family="Consolas",
            ),
            content=ft.Container(
                width=660,
                content=ft.Column(
                    controls=[
                        ft.Text(
                            MANUAL_SOP,
                            size=11, color=DIM,
                            font_family="Consolas",
                            selectable=True,
                        )
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    height=500,
                ),
            ),
            actions=[
                ft.Button(
                    "CLOSE",
                    on_click=lambda _: self.page.pop_dialog(),
                    color=DIM,
                    bgcolor="transparent",
                )
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.show_dialog(dlg)

    # ══ PANEL FACTORIES ═══════════════════════════════════════════════════════

    def _card(self, content, pad: int = 24, height=None) -> ft.Container:
        """Apple-minimal card: near-black surface, no border, generous radius."""
        return ft.Container(
            content=content,
            bgcolor=CARD,
            border_radius=16,
            padding=ft.Padding(left=pad, right=pad, top=pad, bottom=pad),
            height=height,
        )

    def _micro_label(self, text: str) -> ft.Text:
        return ft.Text(
            value=text, size=10, color=DIM,
            weight=ft.FontWeight.W_500,
            font_family="Consolas",
        )

    # ── A. HEADER ─────────────────────────────────────────────────────────────

    def _build_header(self) -> ft.Container:
        self.lbl_latency = ft.Text(
            f"🟢 {self.latency_ms}ms",
            size=12, color=GREEN, font_family="Consolas",
        )
        self.lbl_session = ft.Text(
            "SESSION  --:--:--",
            size=12, color=DIM, font_family="Consolas",
        )
        return ft.Container(
            bgcolor=CARD,
            padding=ft.Padding(left=32, right=32, top=18, bottom=18),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Column(
                        spacing=4,
                        expand=True,
                        controls=[
                            ft.Text(
                                "RELIANCE  QUANTITATIVE  ENGINE",
                                size=19, color=WHITE,
                                weight=ft.FontWeight.W_200,
                                font_family="Consolas",
                            ),
                            ft.Row(
                                spacing=0,
                                controls=[
                                    self.lbl_session,
                                    ft.Container(width=24),
                                    self.lbl_latency,
                                ],
                            ),
                        ],
                    ),
                    ft.Row(
                        spacing=12,
                        controls=[
                            ft.Button(
                                "SYNC",
                                icon=ft.Icons.SYNC,
                                on_click=self._on_sync,
                                color=DIM, bgcolor="transparent",
                            ),
                            ft.Button(
                                "[?] MANUAL",
                                on_click=self._on_manual,
                                color=DIM, bgcolor="transparent",
                            ),
                        ],
                    ),
                ],
            ),
        )

    # ── B. VAULT & EXECUTION ──────────────────────────────────────────────────

    def _build_vault_card(self) -> ft.Container:
        self.lbl_capital = ft.Text(
            f"{self.active_capital:,.2f}",
            size=48, color=WHITE,
            weight=ft.FontWeight.W_100,
            font_family="Consolas",
        )
        self.lbl_capital_sub = ft.Text(
            "100% cash", size=11, color=DIM, font_family="Consolas",
        )
        self.lbl_tick = ft.Text(
            f"{self.live_price:,.2f}",
            size=28, color=CYAN,
            weight=ft.FontWeight.W_200,
            font_family="Consolas",
        )
        self.lbl_target = ft.Text(
            f"AI TARGET  {self.target_price:,.2f}",
            size=12, color=DIM, font_family="Consolas",
        )
        self.lbl_pnl = ft.Text(
            "—", size=30, color=DIM,
            weight=ft.FontWeight.W_200,
            font_family="Consolas",
        )
        self.lbl_pnl_sub = ft.Text(
            "No active position",
            size=11, color=DIM, font_family="Consolas",
        )
        self.exp_bar = ft.ProgressBar(
            value=0.0, bar_height=2,
            color=CYAN, bgcolor=GHOST, border_radius=1,
        )
        self.lbl_sl = ft.Text(
            f"{self.stop_loss_pct}%  stop-loss  ·  SAFE",
            size=11, color=DIM, font_family="Consolas",
        )

        return self._card(
            ft.Column(
                spacing=0,
                controls=[
                    # Capital block
                    self._micro_label("ACTIVE  CAPITAL"),
                    ft.Container(height=4),
                    self.lbl_capital,
                    ft.Container(height=2),
                    self.lbl_capital_sub,
                    ft.Container(height=6),
                    self.exp_bar,
                    ft.Container(height=22),

                    # Tick block
                    self._micro_label("LIVE  TICK"),
                    ft.Container(height=4),
                    self.lbl_tick,
                    ft.Container(height=2),
                    self.lbl_target,
                    ft.Container(height=22),

                    # PnL block
                    self._micro_label("UNREALISED  M2M"),
                    ft.Container(height=4),
                    self.lbl_pnl,
                    ft.Container(height=2),
                    self.lbl_pnl_sub,
                    ft.Container(height=26),

                    # Execution buttons
                    ft.Row(
                        spacing=10,
                        controls=[
                            ft.Button(
                                "MARKET  BUY",
                                on_click=self._on_buy,
                                color=GREEN,
                                bgcolor=G_BUY,
                                expand=True,
                                style=ft.ButtonStyle(
                                    shape=ft.RoundedRectangleBorder(radius=10),
                                ),
                                height=50,
                            ),
                            ft.Button(
                                "LIQUIDATE",
                                on_click=self._on_liquidate,
                                color=RED,
                                bgcolor=G_SELL,
                                style=ft.ButtonStyle(
                                    shape=ft.RoundedRectangleBorder(radius=10),
                                ),
                                height=50,
                            ),
                        ],
                    ),
                    ft.Container(height=18),

                    # Stop-loss slider
                    self.lbl_sl,
                    ft.Slider(
                        value=self.stop_loss_pct,
                        min=0.5, max=5.0, divisions=45,
                        active_color=CYAN, thumb_color=CYAN,
                        on_change=self._on_sl_change,
                    ),
                ],
            ),
        )

    # ── C. ALPHA MATRIX ───────────────────────────────────────────────────────

    def _build_alpha_card(self) -> ft.Container:
        """
        [BACKEND HOOK] Values populated from pandas-ta calculations.
        Wire in _refresh_alpha() method.
        """
        rsi_c = GREEN if self.rsi14 >= 50 else RED
        ema_c = GREEN if self.ema_delta >= 0 else RED
        vol_c = CYAN  if self.vol_surge > 1.5 else WHITE

        self.lbl_rsi = ft.Text(
            f"{self.rsi14:.1f}", size=30, color=rsi_c,
            weight=ft.FontWeight.W_100, font_family="Consolas",
        )
        self.lbl_ema = ft.Text(
            f"{self.ema_delta:+.2f}%", size=30, color=ema_c,
            weight=ft.FontWeight.W_100, font_family="Consolas",
        )
        self.lbl_vol = ft.Text(
            f"{self.vol_surge:.1f}×", size=30, color=vol_c,
            weight=ft.FontWeight.W_100, font_family="Consolas",
        )
        self.lbl_atr = ft.Text(
            f"{self.atr14:.1f}", size=30, color=DIM,
            weight=ft.FontWeight.W_100, font_family="Consolas",
        )

        def tile(label: str, value_ctrl: ft.Text) -> ft.Container:
            return ft.Container(
                expand=True,
                bgcolor=TILE,
                border_radius=12,
                padding=ft.Padding(left=16, right=16, top=14, bottom=14),
                content=ft.Column(
                    spacing=0,
                    controls=[
                        ft.Text(
                            label, size=9, color=GHOST,
                            weight=ft.FontWeight.W_700,
                            font_family="Consolas",
                        ),
                        ft.Container(height=6),
                        value_ctrl,
                    ],
                ),
            )

        return self._card(
            ft.Column(
                spacing=0,
                controls=[
                    self._micro_label("ALPHA  MATRIX"),
                    ft.Container(height=14),
                    ft.Row(
                        spacing=10,
                        controls=[
                            tile("14-DAY  RSI",      self.lbl_rsi),
                            tile("5-DAY  EMA  Δ",    self.lbl_ema),
                        ],
                    ),
                    ft.Container(height=10),
                    ft.Row(
                        spacing=10,
                        controls=[
                            tile("VOLUME  SURGE",    self.lbl_vol),
                            tile("ATR  14",          self.lbl_atr),
                        ],
                    ),
                ],
            ),
            pad=20,
        )

    # ── D. GPU CANVAS CHART ───────────────────────────────────────────────────

    def _build_chart_card(self) -> ft.Container:
        self.chart_canvas = cv.Canvas(
            shapes=self._build_chart_shapes(),
            expand=True,
            on_resize=self._on_chart_resize,
        )
        return self._card(
            ft.Column(
                spacing=0,
                expand=True,
                controls=[
                    self._micro_label("ACTUAL  VS  PREDICTED"),
                    ft.Container(height=10),
                    ft.Container(
                        content=self.chart_canvas,
                        bgcolor=BLACK,
                        border_radius=12,
                        expand=True,
                        height=310,
                        padding=ft.Padding(left=4, right=4, top=4, bottom=4),
                    ),
                ],
            ),
            pad=20,
        )

    # ── E. LEVEL II DEPTH ─────────────────────────────────────────────────────

    def _build_ob_card(self) -> ft.Container:
        self.ob_col = ft.Column(spacing=7)
        self._rebuild_ob()
        self._push_ob_ui()

        ob_header = ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=0,
            controls=[
                ft.Text("BID", size=9, color=CYAN,
                         font_family="Consolas", width=70,
                         text_align=ft.TextAlign.RIGHT),
                ft.Container(width=6),
                ft.Container(width=100, content=ft.Text(
                    "VOLUME", size=9, color=DIM, font_family="Consolas",
                    text_align=ft.TextAlign.CENTER,
                )),
                ft.Container(width=14),
                ft.Container(width=100),
                ft.Container(width=6),
                ft.Text("ASK", size=9, color=RED,
                         font_family="Consolas", width=70),
            ],
        )

        return self._card(
            ft.Column(
                spacing=0,
                controls=[
                    self._micro_label("LEVEL  II  DEPTH"),
                    ft.Container(height=12),
                    ob_header,
                    ft.Container(height=8),
                    self.ob_col,
                ],
            ),
            pad=20,
        )

    # ── EVENT LOG ─────────────────────────────────────────────────────────────

    def _build_log_card(self) -> ft.Container:
        self.log_col = ft.Column(spacing=2)
        self._log("V10.0 INITIALISED")
        self._log("[BACKEND HOOK] Awaiting vault DB connection")
        return self._card(
            ft.Column(
                spacing=0,
                controls=[
                    self._micro_label("EVENT  LOG"),
                    ft.Container(height=8),
                    ft.Container(
                        content=self.log_col,
                        bgcolor=BLACK,
                        border_radius=10,
                        padding=ft.Padding(left=10, right=10, top=8, bottom=8),
                        height=120,
                    ),
                ],
            ),
            pad=16,
        )

    # ── F. PAGINATED LEDGER ────────────────────────────────────────────────────

    def _build_ledger_section(self) -> ft.Container:
        self.ledger_tbl = ft.DataTable(
            columns=[
                ft.DataColumn(
                    ft.Text("DATE", size=10, color=DIM, font_family="Consolas")
                ),
                ft.DataColumn(
                    ft.Text("AI TARGET", size=10, color=DIM, font_family="Consolas"),
                    numeric=True,
                ),
                ft.DataColumn(
                    ft.Text("ACTUAL CLOSE", size=10, color=DIM, font_family="Consolas"),
                    numeric=True,
                ),
                ft.DataColumn(
                    ft.Text("ERROR VAR.", size=10, color=DIM, font_family="Consolas"),
                    numeric=True,
                ),
            ],
            rows=[],
            bgcolor=CARD,
            border_radius=12,
            column_spacing=30,
            data_row_min_height=30,
            data_row_max_height=36,
            divider_thickness=0.4,
            horizontal_lines=ft.BorderSide(width=0.4, color=GHOST),
        )

        self.lbl_page = ft.Text(
            "PAGE  1  /  1",
            size=11, color=DIM, font_family="Consolas",
        )
        self.btn_prev = ft.Button(
            "< PREV", on_click=self._on_prev_page,
            color=DIM, bgcolor="transparent",
        )
        self.btn_next = ft.Button(
            "NEXT >", on_click=self._on_next_page,
            color=DIM, bgcolor="transparent",
        )
        self._rebuild_ledger()

        return ft.Container(
            bgcolor=CARD,
            border_radius=16,
            padding=ft.Padding(left=28, right=28, top=24, bottom=28),
            content=ft.Column(
                spacing=0,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=12,
                        controls=[
                            ft.Text(
                                "TRADE  LEDGER",
                                size=10, color=DIM,
                                weight=ft.FontWeight.W_500,
                                font_family="Consolas",
                                expand=True,
                            ),
                            self.btn_prev,
                            self.lbl_page,
                            self.btn_next,
                        ],
                    ),
                    ft.Container(height=14),
                    ft.ListView(
                        controls=[self.ledger_tbl],
                        height=480,
                    ),
                ],
            ),
        )

    # ══ BUILD ENTRY ═══════════════════════════════════════════════════════════

    def build(self, page: ft.Page):
        self.page = page

        # ── page configuration ─────────────────────────────────────────────
        page.title            = "RELIANCE QUANTITATIVE ENGINE  ·  V10.0"
        page.theme_mode       = ft.ThemeMode.DARK
        page.bgcolor          = BLACK
        page.padding          = 0
        page.window.maximized = True

        # ── build all panels ───────────────────────────────────────────────
        header          = self._build_header()
        vault_card      = self._build_vault_card()
        alpha_card      = self._build_alpha_card()
        chart_card      = self._build_chart_card()
        ob_card         = self._build_ob_card()
        log_card        = self._build_log_card()
        ledger_section  = self._build_ledger_section()

        # ── 12-col responsive layout ───────────────────────────────────────
        # Left  col 4/12: vault + alpha matrix
        # Centre col 5/12: chart
        # Right  col 3/12: order book + event log
        body = ft.ResponsiveRow(
            columns=12,
            spacing=0,
            run_spacing=0,
            controls=[
                # ── LEFT ───────────────────────────────────────────────────
                ft.Container(
                    col={"xs": 12, "md": 4},
                    padding=ft.Padding(left=14, right=7, top=14, bottom=0),
                    content=ft.Column(
                        spacing=14,
                        controls=[vault_card, alpha_card],
                    ),
                ),
                # ── CENTRE ─────────────────────────────────────────────────
                ft.Container(
                    col={"xs": 12, "md": 5},
                    padding=ft.Padding(left=7, right=7, top=14, bottom=0),
                    content=chart_card,
                ),
                # ── RIGHT ──────────────────────────────────────────────────
                ft.Container(
                    col={"xs": 12, "md": 3},
                    padding=ft.Padding(left=7, right=14, top=14, bottom=0),
                    content=ft.Column(
                        spacing=14,
                        controls=[ob_card, log_card],
                    ),
                ),
            ],
        )

        bottom = ft.Container(
            content=ledger_section,
            padding=ft.Padding(left=14, right=14, top=14, bottom=20),
        )

        page.add(
            ft.Column(
                spacing=0,
                expand=True,
                controls=[header, body, bottom],
            )
        )

        # ── start background worker ────────────────────────────────────────
        self._log("BACKGROUND WORKER STARTING...")
        self._start_worker()


# ══ ENTRY POINT ══════════════════════════════════════════════════════════════

def main(page: ft.Page):
    engine = QuantEngine()
    engine.build(page)


ft.run(main)