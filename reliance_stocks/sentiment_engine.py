import console_setup  # noqa: F401  — must precede any print()
import json
import re
import sys
import time
import yfinance as yf
from datetime import datetime
from openai import OpenAI

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║       SENTIMENT ENGINE  ·  V5.0 ENTERPRISE  ·  INTELLIGENCE CORE           ║
# ║       Multi-Tier JSON Extraction  ·  Risk Clamping  ·  Retry Backoff        ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── LOCAL LM STUDIO CONNECTION ────────────────────────────────────────────────
# Bypasses all cloud routing. Points exclusively to the local inference server.
# api_key is a required positional arg by the openai SDK; value is irrelevant
# for a local endpoint but must be a non-empty string.
client = OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="local-airgapped",
)

# ── RISK BOUNDARY CONFIGURATION ───────────────────────────────────────────────
# Maximum realistic single-day movement for RELIANCE.NS under normal conditions.
# Any AI prediction outside this envelope is intercepted and hard-clamped.
MAX_DAILY_MOVE_PCT = 0.035   # 3.5 %

# ── RETRY CONFIGURATION ───────────────────────────────────────────────────────
LLM_RETRY_ATTEMPTS   = 3
LLM_RETRY_BASE_DELAY = 2.0   # seconds; doubled on each subsequent attempt


# ══════════════════════════════════════════════════════════════════════════════
#  TELEMETRY CONSOLE
# ══════════════════════════════════════════════════════════════════════════════

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]   # HH:MM:SS.mmm

def log_info(msg: str):
    print(f"  [{_ts()}] ▸  {msg}")

def log_ok(msg: str):
    print(f"  [{_ts()}] ✔  {msg}")

def log_warn(msg: str):
    print(f"  [{_ts()}] ⚠  {msg}")

def log_err(msg: str):
    print(f"  [{_ts()}] ✖  {msg}")

def log_signal(msg: str):
    print(f"  [{_ts()}] ⚡ SIGNAL  ▸  {msg}")

def log_clamp(msg: str):
    print(f"  [{_ts()}] 🛡️ RISK CLAMP ACTIVE  ▸  {msg}")

def section(title: str):
    bar = "─" * (64 - len(title) - 3)
    print(f"\n  ┌─ {title} {bar}")

def section_end():
    print("  └" + "─" * 65)


# ══════════════════════════════════════════════════════════════════════════════
#  NEWS FETCHER
# ══════════════════════════════════════════════════════════════════════════════

def _title_of(article: dict) -> str:
    """
    Extracts a headline from one yfinance news item across both payload schemas.

    yfinance changed this structure: older releases put the headline at the top
    level as article["title"], newer ones nest it under article["content"]["title"].
    The previous single-schema lookup returned "" against a newer payload, so
    every run silently fell through to the neutral baseline string — visible in
    the ledger as rows reading "Market conditions baseline." with a real
    alpha_sentiment score attached to no actual news.
    """
    title = (article.get("title") or "").strip()
    if title:
        return title

    content = article.get("content")
    if isinstance(content, dict):
        return (content.get("title") or "").strip()

    return ""


def fetch_top_headline() -> str:
    """
    Safely extracts the latest Reliance Industries headline via yfinance.
    Iterates all returned articles until it finds one with a non-empty title.
    Returns a neutral baseline string rather than None on any failure so that
    downstream callers always receive a valid string context for the AI prompt.
    """
    section("NEWS ACQUISITION")
    try:
        ticker = yf.Ticker("RELIANCE.NS")
        news   = ticker.news
        if news:
            for article in news:
                title = _title_of(article)
                if title:
                    log_ok(f"Headline acquired: {title[:90]}{'…' if len(title) > 90 else ''}")
                    section_end()
                    return title
            log_warn(f"{len(news)} article(s) returned but none exposed a usable title.")
            log_warn(f"Unrecognised schema — keys seen: {sorted(news[0].keys())}")
        else:
            log_warn("No articles returned from yfinance news feed.")
    except Exception as exc:
        log_err(f"yfinance news fetch error: {exc}")

    fallback = "Market conditions baseline. No significant immediate catalysts detected."
    log_warn(f"Using baseline headline: '{fallback}'")
    section_end()
    return fallback


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE A — DYNAMIC RISK-BOUNDING & CLAMPING MATRIX
# ══════════════════════════════════════════════════════════════════════════════

def _apply_risk_clamp(payload: dict, current_price: float) -> dict:
    """
    Enforces the ±3.5% hard-cap variance envelope on the AI's output.

    For each of the two numeric prediction fields:
      - calculated_price_delta : absolute value must not exceed 3.5% of current_price
      - ai_predicted_close     : must sit within [current_price × 0.965, current_price × 1.035]

    When a breach is detected the value is intercepted, the breach is logged
    with the original and clamped values, and the corrected payload is returned.
    The reasoning field is annotated to record the intervention for the
    historical feedback loop so the AI can learn from its own over-shooting.
    """
    max_move   = current_price * MAX_DAILY_MOVE_PCT
    upper_cap  = current_price + max_move
    lower_cap  = current_price - max_move
    clamped    = False

    # ── delta clamping ────────────────────────────────────────────────────────
    raw_delta = float(payload.get("calculated_price_delta", 0.0))
    if abs(raw_delta) > max_move:
        clamped_delta = max_move if raw_delta > 0 else -max_move
        log_clamp(
            f"calculated_price_delta  raw={raw_delta:+.4f}  "
            f"→  clamped={clamped_delta:+.4f}  "
            f"(envelope: ±₹{max_move:.2f})"
        )
        payload["calculated_price_delta"] = round(clamped_delta, 4)
        clamped = True

    # ── predicted close clamping ──────────────────────────────────────────────
    raw_close = float(payload.get("ai_predicted_close", current_price))
    if raw_close > upper_cap:
        log_clamp(
            f"ai_predicted_close  raw=₹{raw_close:.2f}  "
            f"→  clamped=₹{upper_cap:.2f}  "
            f"(upper ceiling: ₹{upper_cap:.2f})"
        )
        payload["ai_predicted_close"] = round(upper_cap, 2)
        clamped = True
    elif raw_close < lower_cap:
        log_clamp(
            f"ai_predicted_close  raw=₹{raw_close:.2f}  "
            f"→  clamped=₹{lower_cap:.2f}  "
            f"(lower floor: ₹{lower_cap:.2f})"
        )
        payload["ai_predicted_close"] = round(lower_cap, 2)
        clamped = True

    if clamped:
        # Annotate the reasoning field so the feedback loop records the breach
        original_reasoning = payload.get("financial_impact_reasoning", "")
        payload["financial_impact_reasoning"] = (
            f"[RISK CLAMP APPLIED — raw prediction exceeded ±{MAX_DAILY_MOVE_PCT*100:.1f}% "
            f"daily envelope. Output corrected before vault write.] {original_reasoning}"
        )

    return payload


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE B — MULTI-TIERED JSON EXTRACTION & STRUCTURAL REPAIR PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def _tier1_direct_parse(raw: str) -> dict | None:
    """
    Tier 1: Attempts json.loads on the raw string after stripping markdown
    fences. Fastest path — succeeds when the model outputs clean JSON with
    no surrounding prose.
    """
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict) and "ai_predicted_close" in result:
            log_ok("JSON extraction: Tier-1 (direct parse) succeeded.")
            return result
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _tier2_brace_regex(raw: str) -> dict | None:
    """
    Tier 2: Greedy brace-matching regex that walks character-by-character
    to find the first '{' and its matching '}', correctly handling nested
    braces. Unlike a naive greedy pattern r'{.*}' this cannot over-capture if
    the model appends text containing braces after the JSON block.
    """
    start = raw.find("{")
    if start == -1:
        return None

    depth   = 0
    end_idx = -1
    for i, ch in enumerate(raw[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_idx = i
                break

    if end_idx == -1:
        return None

    candidate = raw[start : end_idx + 1]
    try:
        result = json.loads(candidate)
        if isinstance(result, dict) and "ai_predicted_close" in result:
            log_ok("JSON extraction: Tier-2 (brace-walk regex) succeeded.")
            return result
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _tier3_sanitize_and_repair(raw: str) -> dict | None:
    """
    Tier 3: Character-level sanitation pass targeting common LLM formatting
    defects before re-attempting the parse:
      - Strips Python/JS-style single-line comments (// ... and # ...)
      - Removes trailing commas before closing braces/brackets
      - Replaces typographic "smart" quotes with ASCII equivalents
      - Strips any bare 'json' label prefix that some models emit
    """
    # Remove comment tokens the model sometimes injects
    s = re.sub(r"//[^\n]*",  "", raw)
    s = re.sub(r"#[^\n]*",   "", s)

    # Strip trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r"\1", s)

    # Normalise smart/curly quotes to ASCII
    for curly, straight in [("\u201c", '"'), ("\u201d", '"'),
                             ("\u2018", "'"), ("\u2019", "'")]:
        s = s.replace(curly, straight)

    # Remove a bare 'json' word that appears at the start of some outputs
    s = re.sub(r"^\s*json\s*", "", s, flags=re.IGNORECASE)

    # Now try brace-walk on the sanitised string
    start = s.find("{")
    if start == -1:
        return None

    depth, end_idx = 0, -1
    for i, ch in enumerate(s[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_idx = i
                break

    if end_idx == -1:
        return None

    candidate = s[start : end_idx + 1]
    try:
        result = json.loads(candidate)
        if isinstance(result, dict) and "ai_predicted_close" in result:
            log_ok("JSON extraction: Tier-3 (sanitise + repair) succeeded.")
            return result
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _tier4_field_slice_rescue(raw: str, current_price: float) -> dict | None:
    """
    Tier 4 — string-slicing backup layer.
    Abandons structural JSON parsing entirely. Uses anchored regex patterns
    to extract the numeric value after each known key anchor, then assembles
    a synthesized payload from the recovered fragments.

    Key anchors targeted:
      "alpha_sentiment_score":  <float>
      "calculated_price_delta": <float>
      "ai_predicted_close":     <float>
      "financial_impact_reasoning": "<string>"
    """
    def _extract_float(key: str) -> float | None:
        pattern = rf'"{key}"\s*:\s*(-?\d+(?:\.\d+)?)'
        m = re.search(pattern, raw)
        return float(m.group(1)) if m else None

    def _extract_string(key: str) -> str | None:
        pattern = rf'"{key}"\s*:\s*"([^"]+)"'
        m = re.search(pattern, raw)
        return m.group(1).strip() if m else None

    predicted_close = _extract_float("ai_predicted_close")
    if predicted_close is None:
        return None     # Cannot synthesize a meaningful payload without this

    payload = {
        "financial_impact_reasoning": (
            _extract_string("financial_impact_reasoning")
            or "Partial parse rescue. Structural JSON unavailable; key fields sliced."
        ),
        "alpha_sentiment_score":  _extract_float("alpha_sentiment_score")  or 0.0,
        "calculated_price_delta": _extract_float("calculated_price_delta") or 0.0,
        "ai_predicted_close":     predicted_close,
    }
    log_warn("JSON extraction: Tier-4 (field-slice rescue) — partial recovery.")
    return payload


def _extract_ai_payload(raw_content: str, current_price: float) -> dict | None:
    """
    Orchestrates the four-tier extraction cascade in strict priority order.
    Returns the first successfully parsed dict, or None if all tiers fail.
    """
    result = _tier1_direct_parse(raw_content)
    if result:
        return result

    log_warn("Tier-1 failed. Engaging brace-walk regex (Tier-2)...")
    result = _tier2_brace_regex(raw_content)
    if result:
        return result

    log_warn("Tier-2 failed. Engaging character-level sanitiser (Tier-3)...")
    result = _tier3_sanitize_and_repair(raw_content)
    if result:
        return result

    log_warn("Tier-3 failed. Engaging field-slice rescue layer (Tier-4)...")
    result = _tier4_field_slice_rescue(raw_content, current_price)
    if result:
        return result

    log_err("All four extraction tiers exhausted. Raw output unrecoverable.")
    log_err(f"Dump (first 400 chars): {raw_content[:400]}")
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE C — DYNAMIC FALLBACK MATRIX
# ══════════════════════════════════════════════════════════════════════════════

def _build_dynamic_fallback(current_price: float, historical_feedback: str) -> dict:
    """
    When all LLM retry attempts fail this function constructs a non-static
    defensive prediction by reading the directional drift trend from the
    historical_feedback string rather than hard-coding ₹0.00 delta.

    Logic:
      - Counts positive vs negative error variance mentions in the feedback string.
      - If recent errors have been systematically positive (AI over-predicted),
        applies a small negative bias to fight the chronic overshoot.
      - If recent errors have been systematically negative (AI under-predicted),
        applies a small positive bias.
      - In a mixed or empty signal, holds the current price flat.

    Bias magnitude is capped at 0.5% of current_price — conservative enough
    to be defensive without introducing its own directional risk.
    """
    MAX_BIAS_PCT = 0.005   # 0.5 %

    pos_count = len(re.findall(r"\+\d+\.\d+", historical_feedback))
    neg_count = len(re.findall(r"-\d+\.\d+",  historical_feedback))

    if pos_count > neg_count:
        # Prior AIs over-predicted — apply slight downward correction
        bias = -(current_price * MAX_BIAS_PCT)
        direction = "downward drift-correction (prior overshoot detected)"
    elif neg_count > pos_count:
        # Prior AIs under-predicted — apply slight upward correction
        bias = +(current_price * MAX_BIAS_PCT)
        direction = "upward drift-correction (prior undershoot detected)"
    else:
        bias      = 0.0
        direction = "neutral hold (balanced or empty error history)"

    predicted = round(current_price + bias, 2)
    log_warn(f"Dynamic fallback engaged: {direction}")
    log_warn(f"Defensive target: ₹{predicted:.2f}  (bias: {bias:+.4f})")

    return {
        "financial_impact_reasoning": (
            f"Dynamic defensive fallback: LLM cluster offline after all retry attempts. "
            f"Prediction derived from historical error trend analysis ({direction})."
        ),
        "alpha_sentiment_score":  0.0,
        "calculated_price_delta": round(bias, 4),
        "ai_predicted_close":     predicted,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE D — ADVANCED PROMPT CONTEXT ENGINEERING
# ══════════════════════════════════════════════════════════════════════════════

def _build_mega_prompt(headline: str, current_price: float,
                       historical_feedback: str) -> str:
    """
    Constructs the full system + user prompt payload delivered to the local LLM.

    Key prompt engineering decisions:
      - historical_feedback is positioned as the FIRST analytical input, not an
        appendix, to maximise its weight in the model's attention window.
      - Explicit anti-drift instruction: the model is commanded to measure its
        own trailing error vector and apply a corrective offset, not just
        acknowledge the data.
      - Hard output contract: JSON-only, specific keys, specific types.
        Violating the contract format is declared a critical system failure.
      - The example JSON in the prompt uses the current_price as the base so
        the model has a numerically coherent reference to anchor against.
    """
    example_delta = 0.0
    example_close = float(current_price)

    return f"""You are an autonomous, self-correcting quantitative trading AI embedded in an institutional risk management system.

═══════════════════════════════════════════════════════
STEP 1 — HISTORICAL ERROR CALIBRATION (MANDATORY FIRST)
═══════════════════════════════════════════════════════
{historical_feedback}

You MUST perform the following calculation before producing any output:
  a. Read each row above and extract the Error Margin values.
  b. Calculate the mean of those error margins to obtain your trailing drift vector.
  c. If your trailing drift vector is POSITIVE (you have been chronically over-predicting),
     you MUST apply a negative corrective offset to today's predicted delta to fight the overshoot.
  d. If your trailing drift vector is NEGATIVE (you have been chronically under-predicting),
     you MUST apply a positive corrective offset to fight the undershoot.
  e. Record this corrective logic in your financial_impact_reasoning field.

═══════════════════════════════════════════════════════
STEP 2 — TODAY'S MARKET STATE
═══════════════════════════════════════════════════════
  Base Price (9:00 AM capture): ₹{current_price}
  Top Fundamental Catalyst    : "{headline}"

═══════════════════════════════════════════════════════
STEP 3 — OUTPUT CONTRACT (STRICT — NO EXCEPTIONS)
═══════════════════════════════════════════════════════
Output ONLY the following JSON object. No markdown. No backticks.
No explanatory text before or after. Any deviation is a critical system failure.

{{
    "financial_impact_reasoning": "One precise sentence explaining your drift-corrected logic.",
    "alpha_sentiment_score": 0.0,
    "calculated_price_delta": {example_delta},
    "ai_predicted_close": {example_close}
}}

Types:
  financial_impact_reasoning → string
  alpha_sentiment_score      → float in range [-10.0, +10.0]
  calculated_price_delta     → float (positive = bullish, negative = bearish)
  ai_predicted_close         → float (must equal {current_price} + calculated_price_delta)
"""


# ══════════════════════════════════════════════════════════════════════════════
#  CORE INTELLIGENCE FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def analyze_market_intelligence(headline: str, current_price: float,
                                historical_feedback: str) -> dict:
    """
    Primary entry point called by 1_fire_morning.py.

    Execution sequence:
      1. Builds the drift-aware mega_prompt.
      2. Submits to LM Studio with a 3-attempt retry loop (exponential backoff).
      3. On each successful response, runs the four-tier JSON extraction cascade.
      4. On successful parse, applies the risk-clamping matrix.
      5. On full retry exhaustion, returns the dynamic fallback prediction.
    """
    section("INTELLIGENCE ENGINE  ·  MARKET ANALYSIS")
    log_info(f"Base price       : ₹{current_price}")
    log_info(f"Headline         : {headline[:80]}{'…' if len(headline) > 80 else ''}")
    log_info(f"Retry budget     : {LLM_RETRY_ATTEMPTS} attempts")
    log_info(f"Risk envelope    : ±{MAX_DAILY_MOVE_PCT * 100:.1f}%  "
             f"(±₹{current_price * MAX_DAILY_MOVE_PCT:.2f})")

    mega_prompt = _build_mega_prompt(headline, current_price, historical_feedback)

    for attempt in range(1, LLM_RETRY_ATTEMPTS + 1):
        log_info(f"LLM request attempt {attempt}/{LLM_RETRY_ATTEMPTS}...")
        t0 = time.time()

        try:
            response = client.chat.completions.create(
                model="local-model",
                messages=[{"role": "user", "content": mega_prompt}],
                temperature=0.05,    # Near-deterministic: suppresses creative formatting
                max_tokens=512,
            )
            latency_ms = round((time.time() - t0) * 1000)

            raw_content = response.choices[0].message.content
            if not raw_content or not raw_content.strip():
                log_warn(f"Empty response on attempt {attempt} ({latency_ms}ms). Retrying...")
                _backoff(attempt)
                continue

            log_ok(f"Response received in {latency_ms}ms")

            # Four-tier extraction cascade
            parsed = _extract_ai_payload(raw_content, current_price)
            if parsed is None:
                log_warn("Extraction cascade failed. Retrying with fresh LLM call...")
                _backoff(attempt)
                continue

            # Risk-clamping matrix — intercepts hallucinated extreme deltas
            clamped_result = _apply_risk_clamp(parsed, current_price)

            log_signal(
                f"Alpha Score: {clamped_result.get('alpha_sentiment_score', 0.0):+.2f}  |  "
                f"Predicted Close: ₹{clamped_result.get('ai_predicted_close', current_price):.2f}  |  "
                f"Delta: {clamped_result.get('calculated_price_delta', 0.0):+.4f}"
            )
            log_info(f"Reasoning: {clamped_result.get('financial_impact_reasoning', '')[:120]}")
            section_end()
            return clamped_result

        except Exception as exc:
            latency_ms = round((time.time() - t0) * 1000)
            log_err(f"Attempt {attempt} exception after {latency_ms}ms: {exc}")

            if attempt < LLM_RETRY_ATTEMPTS:
                _backoff(attempt)
            else:
                log_err("LM Studio cluster unresponsive after all retry attempts.")

    # All retries exhausted — return dynamic fallback
    log_warn("Engaging dynamic fallback matrix...")
    fallback = _build_dynamic_fallback(current_price, historical_feedback)
    section_end()
    return fallback


def _backoff(attempt: int):
    """Exponential backoff between retry attempts."""
    delay = LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
    log_warn(f"Backoff: waiting {delay:.1f}s before next attempt...")
    time.sleep(delay)
