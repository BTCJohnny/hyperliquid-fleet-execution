import os
from dotenv import load_dotenv, find_dotenv
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

load_dotenv(find_dotenv())

# Use Apprentice Alchemist key
key = os.getenv("PRIVATE_KEY_ALCHEMIST")
account = Account.from_key(key)
exchange = Exchange(account, constants.TESTNET_API_URL)

print(f"🧪 Sending INVALID Order (Price: $0.01)...")

# Send a ridiculous order
result = exchange.order(
    name="ETH",
    is_buy=True,
    sz=0.01,
    limit_px=0.01, # <--- This will be rejected
    order_type={"limit": {"tif": "Gtc"}},
    reduce_only=False
)

print("\n--- API RESPONSE ---")
print(result)
print("--------------------")

if result['status'] == 'err':
    print(f"✅ CONFIRMED: Order was REJECTED.")
    print(f"❌ Reason: {result['response']}")
else:
    print("⚠️  Wait... it actually accepted it?")