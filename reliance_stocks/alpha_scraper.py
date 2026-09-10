import console_setup  # noqa: F401  — must precede any print()
import os
import re
import sys
import json
import time
import sqlite3
import hashlib
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║          RELIANCE ALPHA INGESTION ENGINE  ·  V5.0 ENTERPRISE GRADE          ║
# ║          Multi-Source RSS  ·  Fault-Tolerant DB  ·  Regex Fallback           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── PATHS & ENDPOINTS ─────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DB_FILE       = os.path.join(BASE_DIR, "trading_firm_memory.db")
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"

# ── MULTI-SOURCE RSS FEED MANIFEST ────────────────────────────────────────────
# Each entry is an independent search string variant routed through Google News RSS.
# If one endpoint is throttled or returns zero results, the remaining sources
# continue to supply the pipeline. Results are merged and deduplicated downstream.
RSS_SOURCES = [
    "https://news.google.com/rss/search?q=Reliance+Industries+stock&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=RIL+share+price&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Mukesh+Ambani+business&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Reliance+Industries+NSE&hl=en-IN&gl=IN&ceid=IN:en",
]

# ── BOT-MASKING REQUEST HEADERS ───────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept":          "application/rss+xml, application/xml, text/xml, */*",
}

# ── DB WRITE CONFIGURATION ────────────────────────────────────────────────────
DB_CONNECT_TIMEOUT  = 30.0   # seconds — patient wait for dashboard read locks
DB_RETRY_ATTEMPTS   = 3
DB_RETRY_BASE_DELAY = 1.5    # seconds; doubled on each retry (exponential backoff)


# ── RSS PARSER SELECTION ──────────────────────────────────────────────────────
# BeautifulSoup's "xml" mode requires lxml, which is an optional dependency and
# is NOT installed by default. Requesting it without lxml present raises
# FeatureNotFound and takes down the whole scrape before a single source is
# read. Resolve the parser once at import time and degrade to the stdlib
# html.parser, which handles Google News RSS adequately for title extraction.

def _select_rss_parser() -> str:
    try:
        BeautifulSoup("<rss><item><title>t</title></item></rss>", "xml")
        return "xml"
    except Exception:
        return "html.parser"


_RSS_PARSER = _select_rss_parser()


# ══════════════════════════════════════════════════════════════════════════════
#  TELEMETRY CONSOLE
# ══════════════════════════════════════════════════════════════════════════════

def _ts() -> str:
    """Returns a formatted HH:MM:SS timestamp for log prefixing."""
    return datetime.now().strftime("%H:%M:%S")

def banner():
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║   ⚡  ALPHA INGESTION ENGINE  ·  V5.0  ·  ENTERPRISE PIPELINE   ║")
    print(f"║   INIT: {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}                               ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

def log_info(msg: str):
    print(f"  [{_ts()}] ▸  {msg}")

def log_ok(msg: str):
    print(f"  [{_ts()}] ✔  {msg}")

def log_warn(msg: str):
    print(f"  [{_ts()}] ⚠  {msg}")

def log_err(msg: str):
    print(f"  [{_ts()}] ✖  {msg}")

def section(title: str):
    bar = "─" * (64 - len(title) - 3)
    print(f"\n  ┌─ {title} {bar}")

def section_end():
    print("  └" + "─" * 65)


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE A — MULTI-SOURCE RSS AGGREGATION & DEDUPLICATION
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_one_source(url: str) -> list[str]:
    """
    Fetches a single Google News RSS endpoint and returns a list of raw
    headline strings. Returns an empty list on any network or parse failure
    so the caller can continue to the next source without crashing.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup  = BeautifulSoup(resp.text, _RSS_PARSER)
        items = soup.find_all("item")
        return [item.title.text.strip() for item in items if item.title]
    except Exception as exc:
        log_warn(f"Source fetch failed: {exc}")
        return []


def _fingerprint(headline: str) -> str:
    """
    Produces a collision-resistant fuzzy fingerprint for a headline by:
      1. Lowercasing and stripping punctuation / whitespace.
      2. Splitting into tokens and discarding stop-words.
      3. Sorting tokens (order-invariant) and hashing the result.

    Headlines that carry the same core information but differ in source
    attribution (e.g. "— The Economic Times" vs "| Reuters") collapse to
    the same fingerprint and are treated as duplicates.
    """
    STOP = {
        "a", "an", "the", "is", "in", "on", "at", "of", "to", "and",
        "for", "with", "as", "by", "from", "its", "it", "this", "that",
        "says", "said", "after", "amid", "over", "than", "was", "are",
        "be", "been", "has", "have", "had", "will", "may", "could",
        "would", "also", "but", "or", "not", "up", "down",
    }
    clean  = re.sub(r"[^\w\s]", " ", headline.lower())
    tokens = [t for t in clean.split() if t not in STOP and len(t) > 2]
    key    = " ".join(sorted(tokens))
    return hashlib.md5(key.encode()).hexdigest()


def _score_headline(headline: str) -> int:
    """
    Heuristic relevance scorer. Higher score = higher priority for inclusion.
    Rewards mentions of direct financial catalysts; penalises generic filler.
    Used to select the 3 best headlines from the deduplicated pool.
    """
    HIGH_SIGNAL = [
        "earnings", "profit", "revenue", "results", "quarterly", "fy",
        "jio", "reliance retail", "ipo", "acquisition", "merger", "deal",
        "stake", "investment", "capex", "guidance", "dividend", "buyback",
        "sebi", "rbi", "regulation", "penalty", "fine", "nse", "bse",
        "target", "rating", "upgrade", "downgrade", "forecast",
    ]
    LOW_SIGNAL = [
        "launches", "campaign", "brand", "csr", "sports", "cricket",
        "celebrity", "ad", "advertisement",
    ]
    h = headline.lower()
    score = sum(2 for kw in HIGH_SIGNAL if kw in h)
    score -= sum(1 for kw in LOW_SIGNAL if kw in h)
    return score


def scrape_financial_news() -> list[str] | None:
    """
    Queries all RSS_SOURCES in sequence, merges results, deduplicates via
    fingerprinting, ranks by relevance score, and returns the top 3 headlines.
    Returns None only if every source fails entirely.
    """
    section("PHASE 1 · MULTI-SOURCE RSS AGGREGATION")

    raw_pool: list[str] = []

    for idx, url in enumerate(RSS_SOURCES, start=1):
        variant = url.split("q=")[1].split("&")[0].replace("+", " ")
        log_info(f"[{idx}/{len(RSS_SOURCES)}] Querying variant: '{variant}'")
        t0      = time.time()
        results = _fetch_one_source(url)
        elapsed = round(time.time() - t0, 2)

        if results:
            log_ok(f"  {len(results)} headlines received in {elapsed}s")
            raw_pool.extend(results)
        else:
            log_warn(f"  Source returned 0 results ({elapsed}s)")

    section_end()

    if not raw_pool:
        log_err("ALL RSS SOURCES FAILED. Alpha stream dry. Aborting pipeline.")
        return None

    # ── Deduplication via fingerprinting ──────────────────────────────────────
    section("PHASE 2 · DEDUPLICATION & RELEVANCE RANKING")

    seen_fps: set[str] = set()
    unique: list[str]  = []

    for h in raw_pool:
        fp = _fingerprint(h)
        if fp not in seen_fps:
            seen_fps.add(fp)
            unique.append(h)

    log_info(f"Raw pool   : {len(raw_pool)} headlines")
    log_info(f"After dedup: {len(unique)} unique headlines")

    # ── Rank and select top 3 ─────────────────────────────────────────────────
    ranked  = sorted(unique, key=_score_headline, reverse=True)
    top3    = ranked[:3]

    log_ok(f"Top 3 selected for AI processing:")
    for i, h in enumerate(top3, start=1):
        log_info(f"  {i}. {h[:80]}{'…' if len(h) > 80 else ''}")

    section_end()
    return top3


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE B — HYPER-ROBUST JSON EXTRACTION & REGEX FALLBACK MATRIX
# ══════════════════════════════════════════════════════════════════════════════

def _extract_json_object(raw: str) -> dict | None:
    """
    Tier-1 extractor: uses a regex to isolate the outermost { ... } block
    in the model's raw output, then attempts json.loads on that substring.
    Handles cases where the model wraps its answer in prose, markdown fences,
    or chain-of-thought text before/after the JSON payload.
    """
    match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _extract_via_field_regex(raw: str) -> dict | None:
    """
    Tier-2 fallback: abandons JSON parsing entirely.
    Uses field-level regex to pull the score float and summary string
    directly from the raw text, then reconstructs the data dict manually.
    Handles malformed JSON where brackets or quotes are missing/unmatched.
    """
    score_match   = re.search(r'"?score"?\s*:\s*(-?\d+(?:\.\d+)?)', raw)
    summary_match = re.search(r'"?summary"?\s*:\s*"([^"]+)"', raw)

    if score_match and summary_match:
        return {
            "score":   float(score_match.group(1)),
            "summary": summary_match.group(1).strip(),
        }

    # Last resort: if only a bare float exists anywhere in the output, use it.
    any_float = re.search(r'\b(-?\d{1,2}(?:\.\d)?)\b', raw)
    if any_float:
        score_val = float(any_float.group(1))
        if -10.0 <= score_val <= 10.0:
            log_warn("Tier-3 rescue: bare float extracted as score.")
            return {
                "score":   score_val,
                "summary": "Partial AI parse. Score extracted via rescue layer.",
            }

    return None


def _parse_ai_response(raw_content: str) -> dict | None:
    """
    Orchestrates the three-tier extraction cascade:
      Tier 1 → regex-isolated JSON object + json.loads
      Tier 2 → field-level regex reconstruction
      Tier 3 → bare float rescue (inside Tier-2 function)
    Returns None only if all three tiers fail.
    """
    # Strip markdown fences first — they confuse both tiers
    cleaned = raw_content.replace("```json", "").replace("```", "").strip()

    result = _extract_json_object(cleaned)
    if result and "score" in result and "summary" in result:
        log_ok("JSON extraction: Tier-1 (regex + json.loads) succeeded.")
        return result

    log_warn("Tier-1 failed. Activating field-level regex fallback...")
    result = _extract_via_field_regex(cleaned)
    if result:
        log_ok("JSON extraction: Tier-2 (field regex) succeeded.")
        return result

    log_err("All extraction tiers exhausted. AI output is unrecoverable.")
    log_err(f"Raw dump (first 300 chars): {cleaned[:300]}")
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE D — ENHANCED QUANTITATIVE PROMPTING
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are a quantitative risk manager at a tier-1 institutional trading desk 
specialising in Indian large-cap equities. Your task is to evaluate a set of news headlines 
about Reliance Industries Limited (NSE: RELIANCE) and produce a structured alpha signal.

SCORING RUBRIC — Alpha Score range: -10.0 (Extremely Bearish) to +10.0 (Extremely Bullish):
  +8.0 to +10.0 : Major positive catalyst — earnings beat, transformative acquisition,
                  large government contract, or significant regulatory win.
  +4.0 to +7.9  : Positive operational update — strong guidance, new partnership,
                  product launch with material revenue implications.
  +1.0 to +3.9  : Mildly constructive news — routine marketing, minor expansion,
                  positive analyst commentary without new price targets.
   0.0          : Neutral or mixed signals with no clear directional bias.
  -1.0 to -3.9  : Minor headwind — regulatory inquiry, minor litigation, sector softness.
  -4.0 to -7.9  : Significant negative — earnings miss, major capex write-off,
                  key executive departure, or competitive threat from a major player.
  -8.0 to -10.0 : Severe risk event — regulatory sanctions, criminal investigation,
                  catastrophic operational failure, or systemic market risk event.

OUTPUT RULES:
  1. You MUST output ONLY valid JSON. No preamble, no explanation, no markdown.
  2. The "summary" field must be one precise, institutional-grade sentence in this format:
     "[Signal direction]: [specific catalyst] implies [expected market impact] for RELIANCE."
     Example: "Bullish: Record JIO subscriber growth implies sustained ARPU expansion 
     and margin improvement for RELIANCE in the next two quarters."
  3. The "score" field must be a single float between -10.0 and +10.0.

Output format: {"summary": "your sentence here", "score": 4.5}"""


def analyze_sentiment(headlines: list[str]) -> tuple[str, float]:
    """
    Submits the top headlines to the LM Studio local server using the
    enhanced quantitative system prompt. Applies the three-tier extraction
    cascade to the raw model output. Returns a safe neutral tuple on total failure.
    """
    section("PHASE 3 · QUANTITATIVE AI SENTIMENT ANALYSIS")

    news_block = "\n".join(f"  - {h}" for h in headlines)
    log_info("Transmitting to local AI cluster at LM Studio...")
    log_info(f"Endpoint : {LM_STUDIO_URL}")

    payload = {
        "model":       "local-model",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role":    "user",
                "content": (
                    f"Analyze the following live news headlines for Reliance Industries "
                    f"and produce your alpha signal JSON:\n\n{news_block}"
                ),
            },
        ],
        "temperature": 0.05,   # Near-zero: we want deterministic scoring, not creativity
        "max_tokens":  256,
    }

    try:
        t0       = time.time()
        response = requests.post(LM_STUDIO_URL, json=payload, timeout=60)
        response.raise_for_status()
        latency  = round(time.time() - t0, 3)

        ai_data     = response.json()
        raw_content = ai_data["choices"][0]["message"]["content"]

        log_ok(f"AI response received in {latency}s")
        log_info(f"Token usage: "
                 f"prompt={ai_data.get('usage', {}).get('prompt_tokens', '?')}  "
                 f"completion={ai_data.get('usage', {}).get('completion_tokens', '?')}")

        parsed = _parse_ai_response(raw_content)

        if parsed:
            score   = float(parsed["score"])
            summary = str(parsed["summary"])

            # Clamp score to valid range — guard against model drift
            score = max(-10.0, min(10.0, score))

            sentiment_label = (
                "🟢 BULLISH" if score > 1.0
                else "🔴 BEARISH" if score < -1.0
                else "⚪ NEUTRAL"
            )
            log_ok(f"Alpha Score : {score:+.1f}  {sentiment_label}")
            log_ok(f"Summary     : {summary}")
            section_end()
            return summary, score

    except requests.exceptions.ConnectionError:
        log_err("CONNECTION REFUSED — LM Studio server is not running.")
        log_err("Start the local server in LM Studio before running this script.")
    except requests.exceptions.Timeout:
        log_err("REQUEST TIMED OUT — model may be overloaded (60s limit exceeded).")
    except Exception as exc:
        log_err(f"Unexpected AI pipeline error: {exc}")

    section_end()
    log_warn("Falling back to neutral signal. No alpha injected.")
    return "AI cluster offline. No fundamental signal processed.", 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE C — THREAD-SAFE SQLITE WRITE WITH EXPONENTIAL BACKOFF
# ══════════════════════════════════════════════════════════════════════════════

def _get_db_connection() -> sqlite3.Connection:
    """
    Returns a connection with an explicit 30-second timeout so the write
    operation waits patiently for the dashboard's read loops to release
    their shared lock rather than immediately raising OperationalError.
    """
    return sqlite3.connect(DB_FILE, timeout=DB_CONNECT_TIMEOUT)


def inject_alpha_to_vault(summary: str, score: float) -> None:
    """
    Writes the AI sentiment signal into today's reliance_ledger row using
    an explicit retry loop with exponential backoff to survive database lock
    contention from the dashboard's 10-second auto-refresh cycle.

    Retry schedule (DB_RETRY_ATTEMPTS = 3, DB_RETRY_BASE_DELAY = 1.5s):
      Attempt 1 — immediate
      Attempt 2 — wait 1.5s
      Attempt 3 — wait 3.0s
    """
    section("PHASE 4 · FAULT-TOLERANT VAULT INJECTION")

    today = datetime.now().strftime("%Y-%m-%d")
    log_info(f"Target date  : {today}")
    log_info(f"Alpha Score  : {score:+.1f}")
    log_info(f"Payload size : {len(summary)} chars")

    headline_payload = f"[AI SCORE: {score:+.1f}] {summary}"

    for attempt in range(1, DB_RETRY_ATTEMPTS + 1):
        try:
            log_info(f"DB write attempt {attempt}/{DB_RETRY_ATTEMPTS}...")

            with _get_db_connection() as conn:
                cursor = conn.cursor()

                # Verify a morning row exists before attempting the UPDATE.
                # An UPDATE against a non-existent row silently succeeds in
                # SQLite — this explicit check surfaces the real error.
                cursor.execute(
                    "SELECT id FROM reliance_ledger WHERE trade_date = ?",
                    (today,),
                )
                row = cursor.fetchone()

                if not row:
                    log_err(f"No trading record found for {today}.")
                    log_err("Run '1_fire_morning.py' first to seed today's base price row.")
                    section_end()
                    return

                cursor.execute(
                    """
                    UPDATE reliance_ledger
                       SET headline        = ?,
                           alpha_sentiment = ?
                     WHERE trade_date      = ?
                    """,
                    (headline_payload, score, today),
                )
                conn.commit()

            log_ok(f"Alpha signal committed to vault on attempt {attempt}.")
            log_ok("Dashboard will pull updated fundamental data on next 10s refresh.")
            section_end()
            return  # ← success: exit retry loop

        except sqlite3.OperationalError as db_err:
            if "locked" in str(db_err).lower() and attempt < DB_RETRY_ATTEMPTS:
                delay = DB_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log_warn(f"Database locked (dashboard collision). "
                         f"Backoff {delay:.1f}s before retry {attempt + 1}...")
                time.sleep(delay)
            else:
                log_err(f"DB write failed after {attempt} attempt(s): {db_err}")
                section_end()
                return

        except Exception as exc:
            log_err(f"Unexpected vault error: {exc}")
            section_end()
            return

    log_err(f"Vault injection aborted after {DB_RETRY_ATTEMPTS} failed attempts.")
    section_end()


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    banner()

    pipeline_start = time.time()

    # Phase 1+2: Multi-source scrape, dedup, rank
    headlines = scrape_financial_news()

    if not headlines:
        log_err("Pipeline aborted at Phase 1. No usable headlines recovered.")
        sys.exit(1)

    # Phase 3: AI sentiment scoring with robust JSON extraction
    ai_summary, ai_score = analyze_sentiment(headlines)

    # Phase 4: Thread-safe vault write with exponential backoff
    inject_alpha_to_vault(ai_summary, ai_score)

    # ── Pipeline completion telemetry ─────────────────────────────────────────
    total_elapsed = round(time.time() - pipeline_start, 2)
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print(f"║  ✔  PIPELINE COMPLETE  ·  Total runtime: {total_elapsed:>6.2f}s" + " " * (22 - len(str(total_elapsed))) + "║")
    print(f"║     Alpha Score: {ai_score:>+.1f}   ·   LM Studio: KEEP RUNNING       ║")
    print("║     alpha_scraper may be re-run at any time before 3:30 PM.     ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()