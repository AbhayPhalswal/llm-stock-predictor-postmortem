import daemon
from datetime import datetime

def fire_ignition():
    print("\n" + "☀️ "*25)
    print(f"🚀 INITIATING MANUAL MORNING IGNITION FOR {datetime.now().strftime('%Y-%m-%d')}")
    print("☀️ "*25 + "\n")
    
    try:
        # Reaches into your daemon and quietly triggers just the morning sequence
        daemon.morning_routine()
        print("\n✅ PREDICTION LOCKED. You may now shut down the AI and close this terminal.")
    except Exception as e:
        print(f"\n❌ Ignition Sequence Failed: {str(e)}")
        print("Make sure LM Studio is running before firing the ignition!")

if __name__ == "__main__":
    fire_ignition()