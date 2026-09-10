import sqlite3
from datetime import datetime
import os

DB_NAME = "trading_firm_memory.db"

def initialize_vault():
    """Builds the prediction ledger and capital table if they don't exist yet."""
    # ADDED: check_same_thread=False
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    
    # 1. Prediction Ledger
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reliance_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT,
            headline TEXT,
            sentiment_score REAL,
            base_price REAL,
            predicted_close REAL,
            actual_close REAL,
            error_margin REAL
        )
    ''')
    
    # 2. Capital Portfolio Ledger
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS firm_capital (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            current_balance REAL
        )
    ''')
    
    # Seed the account with ₹1,00,000 if it is brand new
    cursor.execute('SELECT COUNT(*) FROM firm_capital')
    if cursor.fetchone()[0] == 0:
        cursor.execute('INSERT INTO firm_capital (current_balance) VALUES (100000.00)')
        
    conn.commit()
    conn.close()

def log_morning_prediction(headline, sentiment, base_price, predicted_close):
    """At 9:00 AM: The AI saves its guess before the market opens."""
    # ADDED: check_same_thread=False
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    
    cursor.execute('''
        INSERT INTO reliance_ledger 
        (trade_date, headline, sentiment_score, base_price, predicted_close) 
        VALUES (?, ?, ?, ?, ?)
    ''', (today, headline, sentiment, base_price, predicted_close))
    
    conn.commit()
    conn.close()

def log_afternoon_reality(actual_close):
    """
    At 3:30 PM: Processes the closing price, updates error metrics, 
    and hooks directly into the capital execution layer for trade settlement.
    """
    # ADDED: check_same_thread=False
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    
    cursor.execute('SELECT base_price, predicted_close FROM reliance_ledger WHERE trade_date = ?', (today,))
    result = cursor.fetchone()
    
    if result:
        base_price, predicted_close = result
        error_margin = actual_close - predicted_close
        
        # Update the prediction ledger metrics
        cursor.execute('''
            UPDATE reliance_ledger 
            SET actual_close = ?, error_margin = ? 
            WHERE trade_date = ?
        ''', (actual_close, error_margin, today))
        conn.commit()
        
        # Trigger Capital Engine Settlement
        execute_afternoon_trade_settlement(cursor, predicted_close, base_price, actual_close)
        
    conn.close()

def execute_afternoon_trade_settlement(cursor, predicted_close, base_price, actual_close):
    """Simulates trading positions based on the direction of the AI's prediction."""
    cursor.execute('SELECT current_balance FROM firm_capital ORDER BY id DESC LIMIT 1')
    current_capital = cursor.fetchone()[0]
    
    # Strategy Vector: If the AI predicted an increase, execute a simulated buy order at market open
    if predicted_close > base_price:
        shares_bought = current_capital // base_price
        capital_spent = shares_bought * base_price
        remaining_cash = current_capital - capital_spent
        
        # Liquidation sequence at 3:30 PM actual closing price
        revenue_from_sale = shares_bought * actual_close
        new_capital = round(remaining_cash + revenue_from_sale, 2)
        trade_result = new_capital - current_capital
        
        cursor.execute('INSERT INTO firm_capital (current_balance) VALUES (?)', (new_capital,))
        print(f"💸 TRADE SETTLED: Long Position Closed. Delta: ₹{trade_result:+.2f}")
        print(f"🏦 ACTIVE FIRM CAPITAL: ₹{new_capital:,.2f}")
    else:
        # Market Protection Vector: Stay in liquid fiat currency when market drop is foreseen
        print("⏸️ TRADE SKIPPED: AI signaled a downside move. Capital safeguarded in cash.")

def get_recent_performance_feedback(limit=3):
    """THE FEEDBACK EXTRACTOR: Grabs recent historical errors for prompt reinforcement."""
    if not os.path.exists(DB_NAME):
        return "No historical accuracy data available yet."
    try:
        # ADDED: check_same_thread=False
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT trade_date, predicted_close, actual_close, error_margin 
            FROM reliance_ledger 
            WHERE error_margin IS NOT NULL 
            ORDER BY id DESC LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "No historical accuracy data available yet."
            
        feedback = "YOUR RECENT PERFORMANCE TRACK RECORD (LEARN FROM THIS):\n"
        for row in reversed(rows):
            date, pred, actual, error = row
            feedback += f"-> Date: {date} | You Predicted: ₹{pred:,.2f} | Actual Close: ₹{actual:,.2f} | Error Variance: {error:+.2f} INR\n"
        
        return feedback
    except Exception:
        return "Historical context tracking unavailable due to database lock."

def get_current_capital():
    """Fetches the latest ledger state balance."""
    try:
        # ADDED: check_same_thread=False
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT current_balance FROM firm_capital ORDER BY id DESC LIMIT 1')
        balance = cursor.fetchone()[0]
        conn.close()
        return round(balance, 2)
    except Exception:
        return 100000.00