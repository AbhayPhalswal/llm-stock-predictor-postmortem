import urllib.request
import xml.etree.ElementTree as ET
import json
import re
from openai import OpenAI

# Initialize the local inference client
client = OpenAI(base_url="http://127.0.0.1:1234/v1", api_key="lm-studio")

def fetch_top_headline():
    """
    THE AGGREGATOR: Scrapes multiple strategic search vectors across Google News.
    Deduplicates news entries and returns a unified multi-source intelligence brief.
    """
    search_queries = [
        "Reliance+Industries+Stock+NSE",
        "Reliance+Jio+Retail",
        "Mukesh+Ambani+Finance"
    ]
    unique_headlines = []
    
    for query in search_queries:
        url = f"https://news.google.com/rss/search?q={query}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        try:
            with urllib.request.urlopen(req, timeout=4) as response:
                raw_data = response.read()
                xml_text = raw_data.decode('utf-8', errors='ignore')
                root = ET.fromstring(xml_text)
                
                items = root.findall('.//item')[:2]
                for item in items:
                    headline = item.find('title').text
                    if " - " in headline:
                        headline = headline.rsplit(" - ", 1)[0]
                    
                    clean_hl = headline.strip()
                    if clean_hl not in unique_headlines:
                        unique_headlines.append(clean_hl)
        except Exception:
            continue
            
    if not unique_headlines:
        return "Market stable. Reliance executing standard operational tracking across multi-sector industries."
        
    return " || ".join(unique_headlines)

def extract_structured_json(raw_text):
    """
    Slices through verbose or conversational LLM outputs to isolate 
    the structural boundaries of the valid JSON block.
    """
    try:
        fence_match = re.search(r'```json\s*(\{.*?\})\s*```', raw_text, re.DOTALL | re.IGNORECASE)
        if fence_match:
            return json.loads(fence_match.group(1))
        
        start_idx = raw_text.find('{')
        end_idx = raw_text.rfind('}') + 1
        if start_idx != -1 and end_idx != -1:
            return json.loads(raw_text[start_idx:end_idx])
            
        return json.loads(raw_text)
    except Exception:
        return None

def verify_and_clean_matrix(matrix, current_price):
    """
    PRODUCTION SANITY CHECK: Forces type compliance and re-calculates 
    the final mathematical target close to eliminate LLM arithmetic hallucinations.
    """
    try:
        alpha = float(matrix.get("alpha_sentiment_score", 0.0))
        delta = float(matrix.get("calculated_price_delta", 0.0))
        
        alpha = max(-1.0, min(1.0, alpha))
        corrected_close = round(float(current_price + delta), 2)
        
        verified_payload = {
            "financial_impact_reasoning": str(matrix.get("financial_impact_reasoning", "Multi-source synthesis completed successfully.")),
            "sector_classification": str(matrix.get("sector_classification", "Mixed/Aggregated")),
            "alpha_sentiment_score": round(alpha, 2),
            "calculated_price_delta": round(delta, 2),
            "ai_predicted_close": corrected_close
        }
        return verified_payload
    except (ValueError, TypeError):
        print("⚠️ Data Type Audit Failed: Corrupted values received from LLM tokens.")
        return None

def analyze_market_intelligence(aggregated_headlines, current_price, historical_feedback):
    """
    Passes narrative, numeric, AND historical error parameters to the LLM. 
    This creates the neural feedback loop required for True Learning.
    """
    print(f"\n📰 MULTI-SOURCE INTELLIGENCE BRIEF:\n{aggregated_headlines}")
    print(f"\n💰 CURRENT BENCHMARK PRICE: ₹{current_price}")
    print("🧠 Forcing AI to review its past mistakes before predicting...")
    
    mega_prompt = f"""
    [ROLE]
    You are an elite, multi-billion-dollar AI Quantitative Ingestion Engine running automated trading strategies.
    You possess strict self-awareness of your past mathematical errors and MUST adjust your internal computational biases today to compensate for historical drift.
    
    [CONTEXT]
    Asset: Reliance Industries Ltd. (RELIANCE.NS)
    Current Benchmark Price: ₹{current_price}
    Live Market Intelligence Brief (Aggregated Headlines): "{aggregated_headlines}"
    
    [YOUR PAST ACCURACY REPORT CARD]
    {historical_feedback}
    
    [CRITICAL DIRECTIVE ON LEARNING]
    Analyze your past accuracy. If your recent track record shows you consistently overestimating or underestimating the actual close, you MUST mathematically invert that bias today. Do not repeat the same mistake. Use the financial_impact_reasoning to explain exactly how you adjusted your delta based on your past errors.
    
    [TASK]
    Perform an institutional-grade assessment of how the combined weight of these headlines will correlate with today's closing price, strictly adjusting for your past errors. Calculate the expected absolute price movement (price_delta) and final target close.
    
    [CRITICAL OUTPUT CONSTRAINT]
    Output EXACTLY one valid JSON object. Do not include any introductory text, conversational explanation, or markdown wrap text outside the JSON block.
    
    [REQUIRED JSON SCHEMA]
    {{
        "financial_impact_reasoning": "Detailed rationale combining the news signals AND explaining exactly how you mathematically adjusted for your past errors",
        "sector_classification": "Energy / Telecom / Retail / Macro / Mixed",
        "alpha_sentiment_score": A float between -1.00 (extreme panic) and 1.00 (extreme breakout),
        "calculated_price_delta": A float representing the exact native rupee change expected (positive or negative),
        "ai_predicted_close": A float representing the exact final target closing price (Current Price + calculated_price_delta)
    }}
    """

    try:
        response = client.chat.completions.create(
            model="local-model",
            messages=[
                {"role": "system", "content": "You are a self-correcting, deterministic quantitative engine. You output purely valid JSON structured data and mathematically adapt to your historical prediction errors."},
                {"role": "user", "content": mega_prompt}
            ],
            temperature=0.01, # Absolute lowest temperature to force mathematical rigidity
            max_tokens=450 
        )
        
        raw_output = response.choices[0].message.content.strip()
        raw_matrix = extract_structured_json(raw_output)
        
        if raw_matrix is not None:
            clean_matrix = verify_and_clean_matrix(raw_matrix, current_price)
            if clean_matrix is not None:
                return clean_matrix
                
    except Exception as e:
        print(f"❌ Ingestion Pipeline Failure: ({str(e)})")
        
    return {
        "financial_impact_reasoning": "System fallback normalization applied due to runtime script exception.",
        "sector_classification": "Macro",
        "alpha_sentiment_score": 0.00,
        "calculated_price_delta": 0.00,
        "ai_predicted_close": float(current_price)
    }

if __name__ == "__main__":
    # Test script isolated run
    test_price = 1360.00
    aggregated_brief = fetch_top_headline()
    test_feedback = "Date: 2026-06-03 | You Predicted: ₹1375.00 | Actual Reality: ₹1350.00 | You were off by: -₹25.00"
    final_matrix = analyze_market_intelligence(aggregated_brief, test_price, test_feedback)
    print("\n📊 PERFECTED SELF-LEARNING DATA MATRIX DEPLOYED:")
    print(json.dumps(final_matrix, indent=4))