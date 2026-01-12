"""
CONTEXT_FOR_LLM_INGESTION:
--------------------------------------------------------------------------------
SYSTEM ROLE:
Admin Control Terminal (CLI) for the Hyperliquid Fleet.

CAPABILITIES:
1. READ MODE: STATUS, POSITIONS, ORDERS (Live API Data)
2. WRITE MODE: PAUSE, RESUME, CLOSE_ALL (Database Injection)
3. FLEET MODE: Use "ALL" as the bot name to target the entire fleet.

USAGE:
python admin_controls.py "Apprentice" STATUS
python admin_controls.py ALL STATUS
python admin_controls.py ALL PAUSE
--------------------------------------------------------------------------------
"""

import sqlite3
import sys
import os
import time
from dotenv import load_dotenv, find_dotenv
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.utils import constants

# --- Load Environment ---
load_dotenv(find_dotenv())

# --- CONFIGURATION: MAP BOTS TO KEYS ---
# 1. PRIMARY BOTS (The actual unique bot identities)
PRIMARY_BOTS = [
    "Apprentice Alchemist", 
    "SentientGuard", 
    "AlphaCryptoSignal"
]

# 2. FLEET KEYS (Mapping names/aliases to Private Keys)
FLEET_KEYS = {
    "Apprentice Alchemist": os.getenv("PRIVATE_KEY_ALCHEMIST"),
    "SentientGuard":        os.getenv("PRIVATE_KEY_SENTIENT"),
    "AlphaCryptoSignal":    os.getenv("PRIVATE_KEY_ALPHA"),
    
    # Aliases for easier typing
    "Alpha":      os.getenv("PRIVATE_KEY_ALPHA"),
    "Apprentice": os.getenv("PRIVATE_KEY_ALCHEMIST"),
    "Sentient":   os.getenv("PRIVATE_KEY_SENTIENT")
}

# Database Path
DB_PATH = "/Users/johnny_main/Developer/data/signals/signals.db"
IS_MAINNET = os.getenv("IS_MAINNET") == "True"

class AdminViewer:
    def __init__(self, bot_name, private_key):
        self.bot_name = bot_name
        self.base_url = constants.MAINNET_API_URL if IS_MAINNET else constants.TESTNET_API_URL
        try:
            self.account = Account.from_key(private_key)
            self.address = self.account.address
            self.info = Info(self.base_url, skip_ws=True)
            # Suppress connection print to keep "ALL" output clean
            # print(f"📡 Connecting to {bot_name}...") 
        except Exception as e:
            print(f"❌ Error initializing wallet for {bot_name}: {e}")
            self.info = None

    def print_header(self, title):
        print("\n" + "="*60)
        print(f"  {title}  |  {self.bot_name}")
        print("="*60)

    def get_status(self):
        if not self.info: return
        try:
            state = self.info.user_state(self.address)
            margin = state["marginSummary"]
            equity = float(margin["accountValue"])
            margin_used = float(margin["totalMarginUsed"])
            self.print_header("ACCOUNT STATUS")
            print(f"💰 Equity Value:    ${equity:,.2f}")
            print(f"📉 Margin Used:     ${margin_used:,.2f}")
            print(f"🔑 Wallet:          {self.address[:8]}...")
        except Exception as e:
            print(f"❌ Failed to fetch status: {e}")

    def get_positions(self):
        if not self.info: return
        try:
            state = self.info.user_state(self.address)
            positions = state.get("assetPositions", [])
            self.print_header("OPEN POSITIONS")
            active = [p for p in positions if float(p["position"]["szi"]) != 0]
            
            if not active:
                print("✅ No open positions.")
                return

            print(f"{'TICKER':<10} {'SIDE':<6} {'SIZE':<10} {'ENTRY':<10} {'PnL ($)':<10}")
            print("-" * 60)

            all_mids = self.info.all_mids()
            for p in active:
                pos = p["position"]
                ticker = pos["coin"]
                size = float(pos["szi"])
                entry = float(pos["entryPx"])
                mark = float(all_mids.get(ticker, 0))
                side = "LONG" if size > 0 else "SHORT"
                
                if size > 0: pnl = (mark - entry) * size
                else: pnl = (entry - mark) * abs(size)
                
                print(f"{ticker:<10} {side:<6} {size:<10.4f} {entry:<10.2f} {pnl:+.2f}")

        except Exception as e:
            print(f"❌ Failed to fetch positions: {e}")

    def get_orders(self):
        if not self.info: return
        try:
            orders = self.info.frontend_open_orders(self.address)
            self.print_header("OPEN ORDERS")
            
            if not orders:
                print("✅ No active orders.")
                return

            print(f"{'TICKER':<10} {'TYPE':<15} {'PRICE':<10} {'SIZE':<10}")
            print("-" * 60)

            for o in orders:
                ticker = o.get("coin", "Unknown")
                o_type = o.get("orderType", "Limit")
                size = float(o.get("sz", 0))
                
                if o_type == "Limit":
                    price = float(o.get("limitPx", 0))
                else:
                    price = float(o.get("triggerPx", 0))
                
                print(f"{ticker:<10} {o_type:<15} {price:<10.2f} {size:<10.4f}")

        except Exception as e:
            print(f"❌ Failed to fetch orders: {e}")

def send_db_command(bot_name, command):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO bot_controls (bot_id, command) VALUES (?, ?)", (bot_name, command))
        conn.commit()
        conn.close()
        print(f"🚀 COMMAND SENT: [{command}] -> [{bot_name}]")
    except Exception as e:
        print(f"❌ Database Error for {bot_name}: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\nUsage: python admin_controls.py <BOT_NAME> <COMMAND>")
        print("Bots: 'Apprentice', 'Sentient', 'Alpha', or 'ALL'")
        print("Commands: STATUS, POSITIONS, ORDERS, PAUSE, RESUME, CLOSE_ALL")
        sys.exit(1)
        
    target_arg = sys.argv[1]
    action = sys.argv[2].upper()
    
    # 1. Determine Target List
    targets = []
    if target_arg.upper() == "ALL":
        targets = PRIMARY_BOTS
        print(f"\n🌍 EXECUTING '{action}' ON ENTIRE FLEET: {targets}")
    else:
        # Check if it's a valid alias or name
        if target_arg not in FLEET_KEYS:
            print(f"❌ Unknown Bot: '{target_arg}'")
            print(f"Available: {list(FLEET_KEYS.keys()) + ['ALL']}")
            sys.exit(1)
        # Convert Alias to Full Name if needed (not strictly necessary but cleaner)
        # Actually just use the arg to lookup the key
        targets = [target_arg]

    # 2. Execute Action on Targets
    for bot_name in targets:
        # Look up the key (handles aliases if single target, or full names if ALL)
        key = FLEET_KEYS.get(bot_name)
        
        if not key:
            print(f"⚠️  Skipping {bot_name}: No Key Found.")
            continue

        if action in ["STATUS", "POSITIONS", "ORDERS"]:
            # READ MODE
            viewer = AdminViewer(bot_name, key)
            if action == "STATUS": viewer.get_status()
            elif action == "POSITIONS": viewer.get_positions()
            elif action == "ORDERS": viewer.get_orders()
            
        elif action in ["PAUSE", "RESUME", "CLOSE_ALL"]:
            # WRITE MODE
            send_db_command(bot_name, action)
        else:
            print(f"❌ Unknown Command: {action}")