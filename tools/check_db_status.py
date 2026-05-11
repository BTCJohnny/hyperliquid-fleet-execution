import sqlite3
import pandas as pd

# Path to your database
DB_PATH = "/Users/johnny_main/Developer/data/signals/signals.db"

def inspect_recent_signals():
    try:
        conn = sqlite3.connect(DB_PATH)
        
        # Get last 5 signals
        query = """
        SELECT id, bot_name, symbol, signal_type, status, created_at, raw_message
        FROM signals
        ORDER BY id DESC
        LIMIT 5
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty:
            print("❌ Database is EMPTY.")
            return

        print("\n📊 LAST 5 SIGNALS IN DATABASE:")
        print("=" * 80)
        # Iterate nicely
        for index, row in df.iterrows():
            # Truncate raw message for display
            msg_snippet = (row['raw_message'][:30] + '...') if row['raw_message'] else 'None'
            
            print(f"🆔 ID: {row['id']}")
            print(f"🤖 Bot: {row['bot_name']}")
            print(f"🪙 Sym: {row['symbol']}")
            print(f"🚦 Type: {row['signal_type']}  <-- CRITICAL")
            print(f"📝 Stat: {row['status']}       <-- CRITICAL")
            print(f"⏰ Time: {row['created_at']}")
            print("-" * 80)

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    inspect_recent_signals()