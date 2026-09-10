import daemon
from datetime import datetime

def fire_settlement():
    print("\n" + "📉 "*25)
    print(f"🔔 INITIATING MANUAL AFTERNOON SETTLEMENT FOR {datetime.now().strftime('%Y-%m-%d')}")
    print("📉 "*25 + "\n")
    
    try:
        # Reaches into your daemon and triggers the official afternoon sync
        daemon.afternoon_routine()
        print("\n✅ TRADE SETTLED. The ledger is updated and your capital is locked in.")
    except Exception as e:
        print(f"\n❌ Settlement Sequence Failed: {str(e)}")

if __name__ == "__main__":
    fire_settlement()