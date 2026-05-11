"""
CONTEXT_FOR_LLM_INGESTION:
--------------------------------------------------------------------------------
SYSTEM ROLE:
Database Reset Utility ("The Nuke").
DANGER: This script permanently deletes all records from 'signals.db'.

UPDATES (Fix for VACUUM Error):
- Added explicit `conn.commit()` after DELETE operations.
- Sets `conn.isolation_level = None` (Auto-Commit) before running VACUUM.
--------------------------------------------------------------------------------
"""

import sqlite3
import os
import glob
from colorama import Fore, Style, init

init(autoreset=True)

# CONFIGURATION
DB_PATH = "/Users/johnny_main/Developer/data/signals/signals.db"
LOG_DIR = "/Users/johnny_main/Developer/data/logs/"

def nuke_system():
    print(f"\n{Style.BRIGHT}{Fore.RED}☢️  WARNING: SYSTEM NUKE INITIATED ☢️")
    print(f"{Fore.RED}This will PERMANENTLY DELETE all trade history, signals, and performance metrics.")
    print(f"{Fore.YELLOW}Target Database: {DB_PATH}")
    
    confirm = input(f"\n{Style.BRIGHT}Type 'NUKE' to confirm execution: ").strip()
    
    if confirm != 'NUKE':
        print(f"{Fore.GREEN}❌ Aborted. No changes made.")
        return

    # 1. CLEAN DATABASE
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Count rows before death
        try:
            c.execute("SELECT Count(*) FROM signals")
            count = c.fetchone()[0]
        except:
            count = 0
        
        # Execute Order 66
        print(f"{Fore.YELLOW}   ... Deleting records...")
        c.execute("DELETE FROM signals")
        c.execute("DELETE FROM bot_controls")
        
        # CRITICAL FIX: Commit the deletions to end the transaction
        conn.commit()
        
        # CRITICAL FIX: Set isolation_level to None (Auto-Commit) to run VACUUM
        conn.isolation_level = None
        print(f"{Fore.YELLOW}   ... Vacuuming database (Reclaiming space)...")
        conn.execute("VACUUM")
        
        conn.close()
        print(f"\n{Fore.GREEN}✅ Database vaporized. ({count} rows deleted)")
        
    except Exception as e:
        print(f"{Fore.RED}❌ Database Error: {e}")
        return

    # 2. CLEAN LOGS (OPTIONAL)
    print(f"\n{Fore.CYAN}❓ Do you want to delete all log files? (Start with empty terminal)")
    log_choice = input("   Type 'YES' to delete logs: ").strip()
    
    if log_choice == 'YES':
        try:
            files = glob.glob(os.path.join(LOG_DIR, "*.log"))
            for f in files:
                os.remove(f)
                print(f"   🗑️  Deleted: {os.path.basename(f)}")
            print(f"{Fore.GREEN}✅ Log directory cleaned.")
        except Exception as e:
            print(f"{Fore.RED}❌ Log Delete Error: {e}")
    else:
        print(f"{Fore.YELLOW}⚠️  Logs preserved.")

    print(f"\n{Style.BRIGHT}{Fore.WHITE}🚀 SYSTEM RESET COMPLETE. READY FOR FRESH LAUNCH.")

if __name__ == "__main__":
    nuke_system()