"""
CONTEXT_FOR_LLM_INGESTION:
--------------------------------------------------------------------------------
SYSTEM ROLE:
Emergency Kill Switch (Direct API Connection).
This script bypasses the database and the bot loop to directly:
1. Fetch ALL open orders (Limit, Stop, TP/SL).
2. Cancel them one by one using their specific Order ID (oid).
3. Market Close ALL open positions.

USAGE:
python nuke_account.py "Apprentice Alchemist"  -> Nuke specific bot
python nuke_account.py ALL                     -> Nuke ALL bots (Emergency)
--------------------------------------------------------------------------------
"""

import sys
import os
import time
from dotenv import load_dotenv, find_dotenv
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# --- Load Environment ---
load_dotenv(find_dotenv())

# Pull the live wallet map from fleet_runner so the kill switch can NEVER drift
# away from what's actually trading. A stale local copy of this dict caused a
# pre-launch finding where AlphaCryptoSignal pointed at the wrong wallet.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fleet_runner import FLEET_CONFIG  # noqa: E402

FLEET_KEYS = {bot["bot_id"]: bot["private_key"] for bot in FLEET_CONFIG}

IS_MAINNET = os.getenv("IS_MAINNET") == "True"
BASE_URL = constants.MAINNET_API_URL if IS_MAINNET else constants.TESTNET_API_URL

def nuke_wallet(bot_name, private_key):
    print(f"\n☢️  INITIATING NUKE PROTOCOL FOR: {bot_name}")
    
    if not private_key:
        print(f"   ❌ Error: No private key found for {bot_name}")
        return

    try:
        # 1. Connect
        account = Account.from_key(private_key)
        info = Info(BASE_URL, skip_ws=True)
        exchange = Exchange(account, BASE_URL)
        print(f"   🔑 Wallet: {account.address}")

        # 2. Cancel All Orders
        print("   🗑  Scanning for open orders...")
        try:
            open_orders = info.frontend_open_orders(account.address)
            
            if not open_orders:
                print("      ✅ No open orders found.")
            else:
                print(f"      👀 Found {len(open_orders)} active orders. Cancelling now...")
                for order in open_orders:
                    ticker = order["coin"]
                    oid = order["oid"]
                    type_str = order.get("orderType", "Order")
                    
                    try:
                        # The Hyperliquid SDK cancel method requires coin and oid
                        result = exchange.cancel(ticker, oid)
                        print(f"      ❌ Cancelled {ticker} {type_str} (ID: {oid})")
                    except Exception as e:
                        print(f"      ⚠️ Failed to cancel {ticker} (ID: {oid}): {e}")
                        
        except Exception as e:
            print(f"      ❌ Error fetching/cancelling orders: {e}")

        # 3. Close All Positions
        print("   📉 Closing all positions...")
        try:
            user_state = info.user_state(account.address)
            positions = user_state.get("assetPositions", [])
            
            active_positions = [p for p in positions if float(p["position"]["szi"]) != 0]
            
            if not active_positions:
                print("      ✅ No positions to close.")
            else:
                for p in active_positions:
                    coin = p["position"]["coin"]
                    sz = float(p["position"]["szi"])
                    print(f"      💥 Closing {coin} (Size: {sz})...")
                    
                    try:
                        # Market Close
                        exchange.market_close(coin)
                        print(f"         ✅ Closed {coin}.")
                    except Exception as e:
                        print(f"         ❌ Failed to close {coin}: {e}")
        except Exception as e:
            print(f"      ❌ Error fetching positions: {e}")

    except Exception as e:
        print(f"   ❌ CRITICAL ERROR: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\n⚠️  USAGE ERROR")
        print("Usage: python nuke_account.py <BOT_NAME> or 'ALL'")
        print(f"Available Bots: {list(FLEET_KEYS.keys())}")
        sys.exit(1)

    target = sys.argv[1]

    if target.upper() == "ALL":
        print("\n🚨🚨🚨 WARNING: NUKING ENTIRE FLEET 🚨🚨🚨")
        print("You have 5 seconds to cancel (Ctrl+C)...")
        time.sleep(5)
        
        for name, key in FLEET_KEYS.items():
            nuke_wallet(name, key)
            
    else:
        # Check if name exists
        key = FLEET_KEYS.get(target)
        if not key:
            print(f"❌ Unknown Bot: '{target}'")
            sys.exit(1)
            
        nuke_wallet(target, key)
        
    print("\n✅ NUKE PROTOCOL COMPLETE.")