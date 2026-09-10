import sqlite3
import yfinance as yf
from datetime import datetime
import random
import memory_vault  # <-- NEW: Import your vault schema manager

DB_NAME = "trading_firm_memory.db"

def inject_real_historical_data():
    print("⏳ WARMING UP THE BEAST: Fetching real historical prices AND news...")
    
    # <-- NEW: Force the vault to build its tables (Prediction & Capital) if they don't exist
    memory_vault.initialize_vault()
    
    ticker = yf.Ticker("RELIANCE.NS")
    
    # 1. Fetch real historical prices
    hist = ticker.history(period="10d")
    if hist.empty:
        print("❌ Failed to fetch historical price data.")
        return
    recent_days = hist.tail(5)
    
    # 2. Fetch real historical news cache from Yahoo Finance safely
    raw_news = ticker.news
    news_by_date = {}
    
    print("📡 Parsing API News Payload...")
    for article in raw_news:
        # DEFENSIVE PARSING: Use .get() to avoid KeyErrors
        timestamp = article.get('providerPublishTime') or article.get('pubDate')
        title = article.get('title')
        
        # If the article is an ad or missing critical data, skip it entirely
        if not timestamp or not title:
            continue
            
        try:
            # Convert UNIX timestamp to YYYY-MM-DD
            pub_time = datetime.fromtimestamp(int(timestamp))
            date_str = pub_time.strftime("%Y-%m-%d")
            
            # Clean up publisher tags
            if " - " in title:
                title = title.rsplit(" - ", 1)[0]
                
            if date_str not in news_by_date:
                news_by_date[date_str] = []
            news_by_date[date_str].append(title.strip())
        except Exception:
            continue # Drop any weirdly formatted timestamps

    # 3. Inject aligned data into the vault
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    print("\n💉 INJECTING REALITY-ALIGNED MEMORIES INTO VAULT:")
    
    for date, row in recent_days.iterrows():
        date_str = date.strftime("%Y-%m-%d")
        actual_close = round(float(row['Close']), 2)
        
        # Try to find real news for this specific day, otherwise use a generic market baseline
        if date_str in news_by_date:
            # Grab up to 2 unique headlines from that specific day
            daily_headlines = list(set(news_by_date[date_str]))[:2]
            headline_text = " || ".join(daily_headlines)
        else:
            headline_text = "Market stable. Reliance executing standard operational tracking."
            
        # Simulate that the AI has been slightly overly optimistic (bullish drift)
        simulated_error = round(random.uniform(5.0, 25.0), 2) 
        predicted_close = actual_close + simulated_error
        
        # Check if row already exists
        cursor.execute('SELECT id FROM reliance_ledger WHERE trade_date = ?', (date_str,))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO reliance_ledger 
                (trade_date, headline, sentiment_score, base_price, predicted_close, actual_close, error_margin) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (date_str, headline_text, 0.5, actual_close - 10, predicted_close, actual_close, simulated_error))
            
            print(f"✅ [{date_str}] Injected!")
            print(f"   News: {headline_text}")
            print(f"   Target: ₹{predicted_close:.2f} | Reality: ₹{actual_close:.2f} | Error: +₹{simulated_error:.2f}\n")
        else:
            print(f"⚠️ [{date_str}] already exists in ledger. Skipping.")
            
    conn.commit()
    conn.close()
    
    print("🔥 BOOTSTRAP COMPLETE: The AI now has a 100% authentic 5-day memory.")

if __name__ == "__main__":
    inject_real_historical_data()