import sqlite3

# Point to your exact DB path
DB_PATH = "/Users/johnny_main/Developer/data/signals/signals.db"

try:
    conn = sqlite3.connect(DB_PATH)
    # Enable Write-Ahead Logging
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.commit()
    
    # Check if it worked
    cursor = conn.execute("PRAGMA journal_mode;")
    mode = cursor.fetchone()[0]
    
    print(f"✅ Database Journal Mode is now: {mode.upper()}")
    if mode.upper() == "WAL":
        print("🚀 Concurrency enabled! Your scripts can now read/write simultaneously safely.")
    
    conn.close()
except Exception as e:
    print(f"❌ Error: {e}")