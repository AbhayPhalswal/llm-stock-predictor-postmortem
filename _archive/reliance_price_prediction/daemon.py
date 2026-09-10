import schedule
import time
import yfinance as yf
from datetime import datetime
import sentiment_engine
import memory_vault

def is_market_day():
    today = datetime.now().weekday()
    return today < 5  # True if Monday through Friday

def get_live_price():
    try:
        ticker = yf.Ticker("RELIANCE.NS")
        live_data = ticker.history(period="3d", interval="1d")
        if not live_data.empty:
            return round(float(live_data['Close'].iloc[-1]), 2)
    except Exception as e:
        print(f"⚠️ Telemetry Error: Price extraction failed ({str(e)})")
    return None

def morning_routine():
    if not is_market_day():
        print(f"\n[☀️ {datetime.now().strftime('%Y-%m-%d %H:%M')}] Non-trading day detected. Pausing collection pipelines.")
        return

    print(f"\n[☀️ 9:00 AM] Triggering autonomous pre-market routine...")
    
    # 1. Grab raw numerical reality
    current_price = get_live_price()
    if current_price is None:
        print("❌ Pipeline Execution Aborted: Live price feed unreachable.")
        return
        
    # 2. Grab raw narrative reality (Multi-Source Aggregator)
    headline = sentiment_engine.fetch_top_headline()
    
    # 3. NEW: Pull the AI's historical report card from the memory vault
    historical_feedback = memory_vault.get_recent_performance_feedback()
    
    # 4. Hand EVERYTHING (including the history) to the AI to compute the target natively
    ai_matrix = sentiment_engine.analyze_market_intelligence(headline, current_price, historical_feedback)
    
    # 5. Extract the AI's native mathematical calculations
    alpha_score = ai_matrix.get("alpha_sentiment_score", 0.0)
    predicted_close = ai_matrix.get("ai_predicted_close", current_price)
    
    # 6. Log the AI's calculation directly into the database vault
    try:
        memory_vault.log_morning_prediction(headline, alpha_score, current_price, predicted_close)
        print("\n🔒 SYSTEM MATRIX PREDICTION DEPLOYED BY AI:")
        print(f" |— Reason: {ai_matrix.get('financial_impact_reasoning')}")
        print(f" |— Predicted Delta: {ai_matrix.get('calculated_price_delta'):+.2f} INR")
        print(f" |— Predicted Target Close: ₹{predicted_close:.2f}")
    except Exception as e:
        print(f"❌ Storage Exception: Couldn't write AI metrics ({str(e)})")

def afternoon_routine():
    if not is_market_day():
        return
    print(f"\n[📉 3:30 PM] Executing afternoon market synchronization...")
    actual_close = get_live_price()
    if actual_close is not None:
        memory_vault.log_afternoon_reality(actual_close)

def midnight_training():
    if not is_market_day():
        return
    print(f"\n[🧠 11:59 PM] Ledger archives sealed for morning operations.")

# --- INITIALIZATION AND BOOT SECTOR ---
try:
    memory_vault.initialize_vault()
except Exception as e:
    print(f"⚠️ Vault Initialization Error: {str(e)}")

schedule.every().day.at("09:00").do(morning_routine)
schedule.every().day.at("15:30").do(afternoon_routine)
schedule.every().day.at("23:59").do(midnight_training)

if __name__ == "__main__":
    print("\n" + "="*65)
    print("🟢 FULLY AUTONOMOUS V2 QUANT ENGINE RUNNING (AFTERNOON MODE)")
    print("System is monitoring real-time feeds and actively tracking historical drift.")
    print("="*65 + "\n")
    
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"🚨 Background Loop Exception: {str(e)}")
        time.sleep(30)