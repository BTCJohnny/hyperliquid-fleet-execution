import sys
import os
import sqlite3
import time
from dotenv import load_dotenv, find_dotenv

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperliquid_top_gun import HyperLiquidTopGun

load_dotenv(find_dotenv())
DB_PATH = "/Users/johnny_main/Developer/data/signals/signals.db"

# List of all bots to check
TEST_FLEET = [
    {"name": "Apprentice Alchemist", "key": os.getenv("PRIVATE_KEY_ALCHEMIST")},
    {"name": "SentientGuard",        "key": os.getenv("PRIVATE_KEY_SENTIENT")},
    {"name": "AlphaCryptoSignal",    "key": os.getenv("PRIVATE_KEY_ALPHA")}
]

def send_command(bot_name, command):
    print(f"   👉 Sending command: {command}")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO bot_controls (bot_id, command) VALUES (?, ?)", (bot_name, command))
    conn.commit()
    conn.close()

def run_test_for_bot(bot_config):
    name = bot_config["name"]
    key = bot_config["key"]
    
    print(f"\n🤖 TESTING CONTROLS: {name}")
    print("-" * 40)
    
    if not key:
        print("   ❌ SKIPPING: Missing Private Key in .env")
        return

    try:
        # Initialize bot (with dummy risk args to satisfy init)
        bot = HyperLiquidTopGun(name, key, risk_per_trade=0.01)
        conn = sqlite3.connect(DB_PATH)
        
        # TEST 1: PAUSE
        send_command(name, "PAUSE")
        # Simulate the bot checking the DB
        bot.check_controls(conn)
        
        if bot.paused:
            print("   ✅ PAUSE SUCCESS")
        else:
            print("   ❌ PAUSE FAILED")

        # TEST 2: RESUME
        send_command(name, "RESUME")
        bot.check_controls(conn)
        
        if not bot.paused:
            print("   ✅ RESUME SUCCESS")
        else:
            print("   ❌ RESUME FAILED")
            
        conn.close()

    except Exception as e:
        print(f"   ❌ CRITICAL ERROR: {e}")

if __name__ == "__main__":
    print("========================================")
    print("      FLEET CONTROL SYSTEM CHECK        ")
    print("========================================")
    
    for bot in TEST_FLEET:
        run_test_for_bot(bot)
        
    print("\n✅ All Control Tests Completed.")