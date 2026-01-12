import sys
import os
import time
import sqlite3
import logging
import threading
from dotenv import load_dotenv, find_dotenv

# Add parent directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperliquid_top_gun import HyperLiquidTopGun

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- Configuration ---
load_dotenv(find_dotenv())
DB_PATH = "/Users/johnny_main/Developer/data/signals/signals.db"

# The Fleet to Test
TEST_FLEET = [
    {
        "name": "Apprentice Alchemist",
        "key": os.getenv("PRIVATE_KEY_ALCHEMIST")
    }
]

def inject_test_signal(bot_name):
    """Injects a pending ENTRY signal for a specific bot."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Injects a SAFE entry (ETH @ 1000) that won't fill immediately
        c.execute("""
            INSERT INTO signals 
            (bot_name, symbol, direction, entry_1, target_1, stop_loss, status, signal_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (bot_name, "ETH", "LONG", "1000", "1100", "900", "pending", "entry"))
        
        signal_id = c.lastrowid
        conn.commit()
        conn.close()
        return signal_id
    except Exception as e:
        print(f"❌ DB Error: {e}")
        return None

def verify_signal_status(signal_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT status, notes FROM signals WHERE id = ?", (signal_id,))
    row = c.fetchone()
    conn.close()
    return row

def run_single_test(bot_config):
    bot_name = bot_config["name"]
    private_key = bot_config["key"]
    
    print(f"\n🤖 TESTING BOT: {bot_name}")
    print("-" * 40)
    
    # 1. Inject Signal
    print("📝 Injecting test signal...")
    sig_id = inject_test_signal(bot_name)
    
    # 2. Start Bot Instance
    try:
        bot = HyperLiquidTopGun(bot_name, private_key, risk_per_trade=0.01)
        
        # Run in background thread
        t = threading.Thread(target=bot.run_loop, name=f"test_{bot_name}")
        t.daemon = True
        t.start()
        
        print(f"👀 Waiting for execution (Signal ID: {sig_id})...")
        
        # 3. Wait up to 10 seconds
        for i in range(10):
            status, notes = verify_signal_status(sig_id)
            if status == "filled":
                print(f"✅ SUCCESS: Signal Filled (Order Placed)!")
                return
            elif status == "failed":
                print(f"❌ FAILED: {notes}")
                return
            time.sleep(1)
            
        print("❌ TIMEOUT: Bot did not process the signal.")

    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")

if __name__ == "__main__":
    for bot in TEST_FLEET:
        run_single_test(bot)
        time.sleep(2)