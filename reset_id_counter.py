"""
UTILITY: ID Reset
Clears the 'signals' table AND resets the auto-increment ID back to 1.
"""
import sqlite3
from colorama import Fore, Style, init

init(autoreset=True)
DB_PATH = "/Users/johnny_main/Developer/data/signals/signals.db"

def reset_ids():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        # 1. Clear the data (Again, in case new signals arrived)
        c.execute("DELETE FROM signals")
        
        # 2. THE SECRET SAUCE: Reset the internal sequence counter
        c.execute("DELETE FROM sqlite_sequence WHERE name='signals'")
        
        conn.commit()
        print(f"\n{Fore.GREEN}✅ SUCCESS: Database cleared & ID counter reset to 0.")
        print(f"{Fore.CYAN}   The next signal received will be ID: 1")

    except Exception as e:
        print(f"{Fore.RED}❌ Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    reset_ids()