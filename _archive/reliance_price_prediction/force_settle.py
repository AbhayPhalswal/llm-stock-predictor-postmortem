import memory_vault
from datetime import datetime

print(f"🔧 FORCING REALITY OVERRIDE FOR: {datetime.now().strftime('%Y-%m-%d')}")
print("Injecting actual closing price of ₹1308.00...")

# This calls the exact same function the daemon uses at 3:30 PM
memory_vault.log_afternoon_reality(1308.00)

print("✅ Override complete. The AI has been mathematically penalized for the day.")