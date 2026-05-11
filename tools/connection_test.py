"""
CONTEXT_FOR_LLM_INGESTION:
--------------------------------------------------------------------------------
SYSTEM ROLE:
Fleet Connectivity & Health Check Script.
This script verifies the API connection for ALL defined fleet wallets.

CAPABILITIES:
1. Multi-Wallet Support: Loops through all keys defined in .env (ALCHEMIST, SENTIENT, ALPHA).
2. Deep Health Check: For each wallet, it reads:
   - Equity & Margin
   - Open Positions
   - Active Orders (using frontend_open_orders for safety)

USAGE:
python test/connection_test.py
--------------------------------------------------------------------------------
"""

import os
import sys
from dotenv import load_dotenv, find_dotenv
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.utils import constants

# --- 1. Load Environment ---
load_dotenv(find_dotenv())
IS_MAINNET = os.getenv("IS_MAINNET") == "True"

# --- 2. Define Fleet Keys to Test ---
# We map the display name to the .env variable name for clarity
FLEET_CHECKLIST = {
    "Apprentice Alchemist": os.getenv("PRIVATE_KEY_ALCHEMIST"),
    "SentientGuard":        os.getenv("PRIVATE_KEY_SENTIENT"),
    "AlphaCryptoSignal":    os.getenv("PRIVATE_KEY_ALPHA"),
}

print("------------------------------------------------")
print("📡  INITIATING FLEET HEALTH CHECK")
print(f"🌍  Network: {'MAINNET (Real Money)' if IS_MAINNET else 'TESTNET (Fake Money)'}")
print("------------------------------------------------")

base_url = constants.MAINNET_API_URL if IS_MAINNET else constants.TESTNET_API_URL
info = Info(base_url, skip_ws=True)

# --- 3. Iterate Through Each Bot ---
for bot_name, private_key in FLEET_CHECKLIST.items():
    print(f"\n🤖  TESTING: {bot_name}")
    
    if not private_key:
        print(f"   ⚠️  Skipping: No Private Key found in .env")
        continue

    try:
        # Connect
        account = Account.from_key(private_key)
        address = account.address
        print(f"   🔑  Wallet: {address}")

        # [Check 1] Account Status
        user_state = info.user_state(address)
        margin = user_state.get("marginSummary", {})
        equity = float(margin.get("accountValue", 0))
        margin_used = float(margin.get("totalMarginUsed", 0))
        
        print(f"   ✅  Connection Successful")
        print(f"       💰 Equity:      ${equity:,.2f}")
        print(f"       📉 Margin Used: ${margin_used:,.2f}")

        # [Check 2] Active Positions
        raw_positions = user_state.get("assetPositions", [])
        active_positions = [p for p in raw_positions if float(p["position"]["szi"]) != 0]
        
        if active_positions:
            print(f"       📊  {len(active_positions)} Active Position(s):")
            for p in active_positions:
                pos = p["position"]
                print(f"           - {pos['coin']} ({pos['szi']} sz)")
        else:
            print("       ℹ️  No active positions.")

        # [Check 3] Open Orders
        open_orders = info.frontend_open_orders(address)
        if open_orders:
            print(f"       📝  {len(open_orders)} Open Order(s)")
        else:
            print("       ℹ️  No open orders.")

    except Exception as e:
        print(f"   ❌  CONNECTION FAILED: {e}")

print("\n------------------------------------------------")
print("✅  FLEET DIAGNOSTIC COMPLETE")
print("------------------------------------------------")