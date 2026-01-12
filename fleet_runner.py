"""
CONTEXT_FOR_LLM_INGESTION:
--------------------------------------------------------------------------------
SYSTEM ROLE:
Fleet Commander (Multi-Threaded Runner).
This script launches and monitors multiple instances of the HyperLiquidTopGun engine,
each assigned to a specific bot identity and wallet.

CAPABILITIES:
1. Parallel Execution: Runs each bot in its own daemon thread.
2. Signal Routing: Routes DB signals to the correct wallet based on 'bot_id'.
3. Custom Risk Profiles: Allows specific bots (like Alpha) to override global 
   safety defaults (e.g., higher leverage).

CONFIGURATION:
- Define bots in FLEET_CONFIG.
- Keys must be loaded from .env.
- 'bot_id' must match the 'bot_name' column in your signals.db.
--------------------------------------------------------------------------------
"""

import time
import os
import threading
import logging
from dotenv import load_dotenv, find_dotenv
from hyperliquid_top_gun import HyperLiquidTopGun

# --- Load Environment ---
load_dotenv(find_dotenv())

# --- FLEET CONFIGURATION ---
# Format:
# - bot_id: Matches the 'bot_name' in your SQLite database (from Telegram).
# - private_key: The specific wallet for this strategy.
# - risk_per_trade: % of equity to risk (0.02 = 2%).
# - max_leverage: (Optional) Override the global .env limit.
# - default_sl_dist: (Optional) Override the global .env safety stop distance.

FLEET_CONFIG = [
    {
        "bot_id": "Apprentice Alchemist", 
        "private_key": os.getenv("PRIVATE_KEY_ALCHEMIST"), 
        "risk_per_trade": 0.02,
        # Uses .env defaults for leverage (5x) and safety stop (5%)
    },
    {
        "bot_id": "SentientGuard", 
        "private_key": os.getenv("PRIVATE_KEY_SENTIENT"), 
        "risk_per_trade": 0.02,
        # Uses .env defaults for leverage (5x) and safety stop (5%)
    },
    {
        "bot_id": "AlphaCryptoSignal", 
        "private_key": os.getenv("PRIVATE_KEY_ALPHA"), 
        "risk_per_trade": 0.02, 
        # OVERRIDES: Needs room to move fast
        "max_leverage": 20.0,    
        "default_sl_dist": 0.02  # 2% default stop if none provided
    }
]

def launch_fleet():
    print("------------------------------------------------")
    print("🚀  INITIALIZING HYPERLIQUID FLEET")
    print("------------------------------------------------")
    
    threads = []
    
    for config in FLEET_CONFIG:
        bot_id = config["bot_id"]
        key = config["private_key"]
        
        # Safely extract config (defaults to None if missing, handled by class)
        risk = config.get("risk_per_trade")
        lev = config.get("max_leverage")
        sl_dist = config.get("default_sl_dist")
        
        if not key:
            logging.warning(f"⚠️  Skipping {bot_id}: No Private Key found in .env")
            continue
            
        try:
            # Initialize the Agent
            # Note: We pass the overrides here. If they are None, the Class uses .env defaults.
            bot = HyperLiquidTopGun(
                bot_id=bot_id, 
                private_key=key, 
                risk_per_trade=risk,
                max_leverage=lev,
                default_sl_dist=sl_dist
            )
            
            # Create signal processing thread
            signal_thread = threading.Thread(target=bot.run_loop, name=f"{bot_id}-signal", daemon=True)
            signal_thread.start()
            threads.append(signal_thread)

            # Create fill monitoring thread
            monitor_thread = threading.Thread(target=bot.run_fill_monitor, name=f"{bot_id}-monitor", daemon=True)
            monitor_thread.start()
            threads.append(monitor_thread)

            # Formatting log for clarity
            lev_display = f"{lev}x" if lev else "Default"
            print(f"✅  LAUNCHED: {bot_id:<20} | Risk: {risk*100}% | Max Lev: {lev_display} | Threads: 2 (signal+monitor)")
            
        except Exception as e:
            logging.error(f"❌  FAILED to launch {bot_id}: {e}")

    print("------------------------------------------------")
    print(f"👀  Fleet is live. Monitoring {len(threads)} bots...")
    print("    Press Ctrl+C to stop.")
    print("------------------------------------------------")

    try:
        while True:
            # Keep main thread alive so daemon threads keep running
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑  Stopping Fleet...")

if __name__ == "__main__":
    # Setup basic logging for the runner itself
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s'
    )
    launch_fleet()