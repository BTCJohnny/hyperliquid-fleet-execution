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
# Per-Wallet Risk Management Configuration
# Each bot MUST have ALL 4 risk parameters explicitly defined.
# Missing parameters will fall back to .env (see validation warnings below).
#
# Required Parameters:
# - bot_id: Matches the 'bot_name' in your SQLite database (from Telegram)
# - private_key: The specific wallet for this strategy
# - risk_per_trade: % of equity to risk per trade (0.01 = 1%)
# - max_leverage: Maximum allowed leverage (1.0 = no leverage)
# - default_sl_dist: Default stop loss distance if signal doesn't provide one (0.10 = 10% max)
# - max_concurrent_positions: Maximum open positions per wallet (safety limit)
# - allowed_directions: Trade direction filter ("both", "long", or "short")

FLEET_CONFIG = [
    {
        "bot_id": "AITA Hyperliquid",
        "private_key": os.getenv("PRIVATE_KEY_ALCHEMIST"),
        "enabled": True,                   # On/off toggle
        # Conservative mainnet settings - risk controlled by signal Size (1/5 = 1%, 5/5 = 5%)
        "risk_per_trade": 0.01,           # Fallback if signal has no Size
        "max_leverage": 1.0,               # No leverage
        "default_sl_dist": 0.10,           # 10% stop loss (max allowed)
        "max_concurrent_positions": 20,    # Max 20 positions
        "allowed_directions": "both"       # "both", "long", or "short"
    },
    {
        "bot_id": "SentientGuard",
        "private_key": os.getenv("PRIVATE_KEY_SENTIENT"),
        "enabled": False,                   # On/off toggle
        # Conservative mainnet settings
        "risk_per_trade": 0.01,
        "max_leverage": 1.0,
        "default_sl_dist": 0.10,
        "max_concurrent_positions": 20,
        "allowed_directions": "both"       # "both", "long", or "short"
    },
    {
        "bot_id": "AlphaCryptoSignal",
        "private_key": os.getenv("PRIVATE_KEY_ALPHA"),
        "enabled": False,                  # Disabled - positions closed
        # Conservative mainnet settings (reduced from 20x to 1x for safety)
        "risk_per_trade": 0.01,
        "max_leverage": 1.0,               # Reduced from 20.0
        "default_sl_dist": 0.10,           # 10% stop loss (max allowed)
        "max_concurrent_positions": 20,
        "allowed_directions": "both"       # "both", "long", or "short"
    },
    {
        "bot_id": "Manual Trader",
        "private_key": os.getenv("PRIVATE_KEY_MANUAL"),
        "enabled": False,                  # Disabled (no key configured)
        # Conservative mainnet settings
        "risk_per_trade": 0.01,
        "max_leverage": 1.0,
        "default_sl_dist": 0.10,
        "max_concurrent_positions": 20,
        "allowed_directions": "both"       # "both", "long", or "short"
    }
]

def validate_fleet_config():
    """
    Validate FLEET_CONFIG to ensure all bots have complete risk settings.
    Warns if any parameters are missing (will fall back to .env).
    """
    required_params = ['bot_id', 'private_key', 'enabled', 'risk_per_trade', 'max_leverage',
                       'default_sl_dist', 'max_concurrent_positions', 'allowed_directions']

    for i, config in enumerate(FLEET_CONFIG):
        bot_id = config.get('bot_id', f'Bot #{i+1}')
        enabled = config.get('enabled', True)
        missing = [param for param in required_params if param not in config]

        if missing:
            print(f"⚠️  WARNING: {bot_id} missing parameters: {', '.join(missing)}")
            print(f"   These will fall back to .env defaults.")
        else:
            status = "✅ Enabled" if enabled else "⏭️  Disabled"
            print(f"{status}: {bot_id} - Complete risk configuration")

def launch_fleet():
    print("------------------------------------------------")
    print("🚀  INITIALIZING HYPERLIQUID FLEET")
    print("------------------------------------------------")

    # Validate configuration first
    print("\n📋 Validating Fleet Configuration:")
    validate_fleet_config()
    print()
    
    threads = []
    
    for config in FLEET_CONFIG:
        bot_id = config["bot_id"]

        # Check if bot is enabled
        if not config.get("enabled", True):  # Default to True if not specified
            print(f"⏭️  SKIPPED: {bot_id:<20} | Reason: Disabled in config")
            continue

        key = config["private_key"]

        # Extract ALL risk parameters (defaults to None if missing, handled by class)
        risk = config.get("risk_per_trade")
        lev = config.get("max_leverage")
        sl_dist = config.get("default_sl_dist")
        max_pos = config.get("max_concurrent_positions")
        allowed_dirs = config.get("allowed_directions")

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
                default_sl_dist=sl_dist,
                max_concurrent_positions=max_pos,
                allowed_directions=allowed_dirs
            )
            
            # Create signal processing thread
            signal_thread = threading.Thread(target=bot.run_loop, name=f"{bot_id}-signal", daemon=True)
            signal_thread.start()
            threads.append(signal_thread)

            # Create fill monitoring thread
            monitor_thread = threading.Thread(target=bot.run_fill_monitor, name=f"{bot_id}-monitor", daemon=True)
            monitor_thread.start()
            threads.append(monitor_thread)

            # Create position reconciliation thread
            reconcile_thread = threading.Thread(target=bot.run_position_reconciliation, name=f"{bot_id}-reconcile", daemon=True)
            reconcile_thread.start()
            threads.append(reconcile_thread)

            # Formatting log for clarity
            lev_display = f"{lev}x" if lev else "Default"
            max_pos_display = f"{max_pos}" if max_pos else "Default"
            dirs_display = allowed_dirs if allowed_dirs else "both"
            print(f"✅  LAUNCHED: {bot_id:<20} | Risk: {risk*100 if risk else 'Default'}% | Max Lev: {lev_display} | Max Pos: {max_pos_display} | Dirs: {dirs_display} | Threads: 3")
            
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