import re

def test_parsing():
    # The exact text you pasted
    text = """
⚡️ Apprentice Alchemist
Direction: Bullish 🟢
❌ Today's Bullish Exits:
🔴 ETH: Closed @ 3010.00 (Entry: 3000.00), Return: 0.0%
    """
    
    print(f"📝 Testing Text:\n{text}")
    print("-" * 40)

    # 1. Check Bot Name
    bot_match = re.search(r'(SentientGuard|Apprentice Alchemist)', text, re.IGNORECASE)
    print(f"🤖 Bot Match: {bot_match.group(1) if bot_match else 'None'}")

    # 2. Check Exits (The logic from your file)
    exit_pattern = r'🔴\s+([A-Z]+):\s+Closed\s+@\s+\$?([\d.]+)\s+\(Entry:\s+\$?([\d.]+)\),\s+Return:\s+([-\d.]+)%'
    exits = re.findall(exit_pattern, text)
    
    print(f"📉 Exits Found: {len(exits)}")
    
    for symbol, exit_px, entry_px, pnl in exits:
        print(f"   > Symbol: {symbol}")
        print(f"   > Exit Price: {exit_px}")
        print(f"   > PnL: {pnl}%")

if __name__ == "__main__":
    test_parsing()