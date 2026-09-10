import tkinter as tk
from tkinter import scrolledtext
import sqlite3
import yfinance as yf
import os

DB_NAME = "trading_firm_memory.db"

class TradingFirmDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        
        self.title("AI Quant Monitor V2.0")
        # Expanded geometry slightly from 340x270 to 340x310 to cleanly accommodate capital tracker
        self.geometry("340x310")
        self.attributes("-topmost", True)
        self.configure(bg="#0a0a0a") 
        self.resizable(False, False)
        
        self.create_widgets()
        self.refresh_metrics()

    def create_widgets(self):
        lbl_title = tk.Label(self, text="RELIANCE QUANT ENGINE", font=("Arial", 11, "bold"), fg="#00FFCC", bg="#0a0a0a")
        lbl_title.pack(pady=10)
        
        self.lbl_price = tk.Label(self, text="Live Price: ₹0.00", font=("Arial", 11), fg="#FFFFFF", bg="#0a0a0a")
        self.lbl_price.pack(pady=4)
        
        self.lbl_pred = tk.Label(self, text="AI Target: ₹0.00", font=("Arial", 14, "bold"), fg="#FFB300", bg="#0a0a0a")
        self.lbl_pred.pack(pady=2)

        self.lbl_delta = tk.Label(self, text="Expected Move: --", font=("Arial", 10, "italic"), fg="#888888", bg="#0a0a0a")
        self.lbl_delta.pack(pady=2)
        
        self.lbl_accuracy = tk.Label(self, text="System Accuracy: --/10", font=("Arial", 10), fg="#00E676", bg="#0a0a0a")
        self.lbl_accuracy.pack(pady=4)

        # NEW: The Capital Portfolio Tracker
        self.lbl_capital = tk.Label(self, text="Active Capital: ₹100,000.00", font=("Arial", 10, "bold"), fg="#00E5FF", bg="#0a0a0a")
        self.lbl_capital.pack(pady=6)
        
        btn_headlines = tk.Button(self, text="Access Intelligence Brief", font=("Arial", 9, "bold"), 
                                  command=self.show_headlines, fg="#0a0a0a", bg="#00FFCC", 
                                  activebackground="#00B38F", relief="flat", cursor="hand2")
        btn_headlines.pack(pady=10, ipadx=10)

    def fetch_latest_db_records(self):
        if not os.path.exists(DB_NAME):
            return None
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            
            # Fetch ledger record
            cursor.execute('''
                SELECT base_price, predicted_close, actual_close, headline, error_margin 
                FROM reliance_ledger 
                ORDER BY id DESC LIMIT 1
            ''')
            row = cursor.fetchone()
            
            # Fetch error margins for accuracy
            cursor.execute('SELECT error_margin FROM reliance_ledger WHERE error_margin IS NOT NULL')
            all_errors = cursor.fetchall()
            
            # NEW: Fetch latest firm capital balance
            cursor.execute('SELECT current_balance FROM firm_capital ORDER BY id DESC LIMIT 1')
            capital_row = cursor.fetchone()
            current_capital = capital_row[0] if capital_row else 100000.00
            
            conn.close()
            return {"latest": row, "all_errors": all_errors, "capital": current_capital}
        except Exception:
            return None

    def calculate_accuracy_score(self, all_errors):
        if not all_errors:
            return "N/A"
        valid_errors = [abs(x[0]) for x in all_errors if x[0] is not None]
        if not valid_errors:
            return "N/A"
        avg_error = sum(valid_errors) / len(valid_errors)
        score = 10 - (avg_error / 10.0)
        return f"{max(1.0, min(10.0, score)):.1f}"

    def refresh_metrics(self):
        try:
            ticker = yf.Ticker("RELIANCE.NS")
            live_df = ticker.history(period="1d")
            if not live_df.empty:
                current_price = round(float(live_df['Close'].iloc[-1]), 2)
                self.lbl_price.config(text=f"Live Price: ₹{current_price:,.2f}")
        except Exception:
            self.lbl_price.config(text="Live Price: Stream Offline")

        data = self.fetch_latest_db_records()
        if data:
            # Update capital tracker string dynamically
            self.lbl_capital.config(text=f"Active Capital: ₹{data['capital']:,.2f}")
            
            if data["latest"]:
                row = data["latest"]
                base_price = row[0]
                predicted_close = row[1]
                
                delta = predicted_close - base_price
                if delta > 0:
                    color = "#00FF33" 
                    sign = "+"
                else:
                    color = "#FF3333" 
                    sign = ""
                    
                self.lbl_pred.config(text=f"AI Target: ₹{predicted_close:,.2f}", fg=color)
                self.lbl_delta.config(text=f"Expected Move: {sign}₹{delta:.2f}", fg=color)
                
                score = self.calculate_accuracy_score(data["all_errors"])
                self.lbl_accuracy.config(text=f"System Accuracy: {score}/10")
                self.latest_headline_text = row[3]
            else:
                self.lbl_pred.config(text="AI Target: AWAITING DATA", fg="#FFB300")
                self.lbl_delta.config(text="Expected Move: AWAITING DATA")
                self.lbl_accuracy.config(text="System Accuracy: Booting...")
                self.latest_headline_text = "No active briefings logged in ledger memory yet."
        else:
            self.lbl_capital.config(text="Active Capital: ₹100,000.00")
            self.lbl_pred.config(text="AI Target: AWAITING DATA", fg="#FFB300")
            self.lbl_delta.config(text="Expected Move: AWAITING DATA")
            self.lbl_accuracy.config(text="System Accuracy: Booting...")
            self.latest_headline_text = "No active briefings logged in ledger memory yet."

        self.after(300000, self.refresh_metrics)

    def show_headlines(self):
        brief_window = tk.Toplevel(self)
        brief_window.title("Intelligence Brief Text Log")
        brief_window.geometry("500x350")
        brief_window.attributes("-topmost", True)
        brief_window.configure(bg="#111111")
        
        lbl = tk.Label(brief_window, text="V2.0 Aggregated Source Materials:", 
                       font=("Arial", 10, "bold"), fg="#00FFCC", bg="#111111")
        lbl.pack(pady=8)
        
        headlines_list = self.latest_headline_text.split(" || ")
        formatted_text = "\n\n".join([f"❖ {hl}" for hl in headlines_list])
        
        txt_area = scrolledtext.ScrolledText(brief_window, wrap=tk.WORD, font=("Consolas", 10), 
                                             bg="#0a0a0a", fg="#E0E0E0", insertbackground="white", relief="flat")
        txt_area.insert(tk.END, formatted_text)
        txt_area.config(state=tk.DISABLED)
        txt_area.pack(expand=True, fill=tk.BOTH, padx=12, pady=12)

if __name__ == "__main__":
    app = TradingFirmDashboard()
    app.mainloop()