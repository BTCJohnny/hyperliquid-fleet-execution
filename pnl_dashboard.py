"""
CONTEXT_FOR_LLM_INGESTION:
--------------------------------------------------------------------------------
SYSTEM ROLE:
Analytics Dashboard (CLI).
This script queries the 'signals.db' to generate a terminal-based PnL report.

UPDATES (Fix for NoneType Error):
- Added strict `pd.to_numeric` coercion to prevent string/NoneType issues.
- Improved `extract_pnl_from_notes` to handle float comparison safely.
- Added '.fillna(0.0)' to mean calculations to prevent formatting crashes.
--------------------------------------------------------------------------------
"""

import sqlite3
import pandas as pd
import re
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

DB_PATH = "/Users/johnny_main/Developer/data/signals/signals.db"

# Suppress pandas future warnings
pd.set_option('future.no_silent_downcasting', True)

def extract_pnl_from_notes(row):
    """
    Fallback Logic:
    1. Use the explicit 'pnl_percent' column if valid (not 0.0).
    2. Else, scan 'notes' for "Return: -2.5%" text pattern.
    3. Else, return 0.0.
    """
    # Robust check: Ensure value is a float and not effectively zero
    val = row['pnl_percent']
    try:
        if isinstance(val, (int, float)) and abs(val) > 0.001:
            return float(val)
    except:
        pass

    # Regex fallback
    match = re.search(r'Return:\s*([-\d.]+)%', str(row['notes']))
    if match:
        try:
            return float(match.group(1))
        except:
            return 0.0
            
    return 0.0

def get_pnl_report():
    conn = sqlite3.connect(DB_PATH)

    # 1. FETCH DATA
    query = """
        SELECT id, bot_name, symbol, signal_type, status, 
               entry_1, position_size_actual, pnl_percent, created_at, notes 
        FROM signals 
        ORDER BY created_at ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        print(f"{Fore.RED}❌ Database is empty.")
        return

    # --- DATA HYGIENE (CRITICAL FIX) ---
    # 1. Force PnL to numeric (coerces strings/None to NaN, then fills with 0.0)
    df['pnl_percent'] = pd.to_numeric(df['pnl_percent'], errors='coerce').fillna(0.0)
    
    # 2. Force Bot Name to string (handles NULLs)
    df['bot_name'] = df['bot_name'].fillna("Unknown Bot")

    # 3. Calculate Real PnL using the helper
    df['real_pnl'] = df.apply(extract_pnl_from_notes, axis=1)

    # 4. Separate Dataframes
    entries = df[(df['signal_type'] == 'entry') & (df['status'] == 'filled')].copy()
    exits = df[(df['signal_type'] == 'exit') & (df['status'] == 'executed')].copy()

    # --- SECTION A: PERFORMANCE TABLE ---
    print(f"\n{Style.BRIGHT}{Fore.CYAN}📊 HYPERLIQUID FLEET REPORT")
    print("=" * 70)
    
    bots = df['bot_name'].unique()
    
    total_wins = 0
    total_trades = 0
    
    print(f"{Style.BRIGHT}{'BOT NAME':<25} | {'TRADES':<6} | {'WIN RATE':<9} | {'AVG PNL':<9}")
    print("-" * 70)

    for bot in bots:
        # Filter exits for this bot
        bot_exits = exits[exits['bot_name'] == bot]
        count = len(bot_exits)
        
        if count > 0:
            # Stats Calculation
            wins = bot_exits[bot_exits['real_pnl'] > 0]
            win_rate = (len(wins) / count) * 100
            
            # fillna(0.0) ensures we never format a NoneType
            avg_pnl = bot_exits['real_pnl'].mean()
            if pd.isna(avg_pnl): avg_pnl = 0.0
            
            # Formatting Colors
            wr_color = Fore.GREEN if win_rate >= 50 else Fore.RED
            pnl_color = Fore.GREEN if avg_pnl > 0 else Fore.RED
            
            print(f"{Fore.WHITE}{bot:<25} | {count:<6} | {wr_color}{win_rate:>6.1f}%{Fore.RESET}  | {pnl_color}{avg_pnl:>6.2f}%")
            
            total_wins += len(wins)
            total_trades += count
        else:
            # Empty row
            print(f"{Fore.WHITE}{bot:<25} | {0:<6} | {'N/A':<9} | {'N/A':<9}")

    print("=" * 70)
    
    if total_trades > 0:
        global_wr = (total_wins / total_trades) * 100
        print(f"{Style.BRIGHT}🏆 FLEET TOTAL: {total_trades} Trades | Win Rate: {global_wr:.1f}%")
    else:
        print("No closed trades yet.")
    print("=" * 70)

    # --- SECTION B: ACTIVE POSITIONS (Netting Logic) ---
    print(f"\n{Style.BRIGHT}{Fore.MAGENTA}🔥 ACTIVE POSITIONS (Open Exposure)")
    print(f"{'BOT':<20} | {'SYMBOL':<8} | {'ENTRY':<10} | {'SIZE':<10} | {'TIME (UTC)'}")
    print("-" * 70)
    
    active_found = False
    
    for bot in bots:
        bot_entries = entries[entries['bot_name'] == bot]
        bot_exits = exits[exits['bot_name'] == bot]
        
        symbols = bot_entries['symbol'].unique()
        
        for sym in symbols:
            # Netting: Buys - Sells = Open Positions
            n_buys = len(bot_entries[bot_entries['symbol'] == sym])
            n_sells = len(bot_exits[bot_exits['symbol'] == sym])
            open_count = n_buys - n_sells
            
            if open_count > 0:
                active_found = True
                # Get the N most recent entries
                specific_entries = bot_entries[bot_entries['symbol'] == sym].tail(open_count)
                
                for _, row in specific_entries.iterrows():
                    # Clean Timestamp
                    time_str = str(row['created_at'])[5:16].replace("T", " ")
                    
                    print(f"{Fore.WHITE}{bot[:20]:<20} | {Fore.CYAN}{sym:<8}{Fore.RESET} | ${row['entry_1']:<9} | {row['position_size_actual']:<10} | {time_str}")

    if not active_found:
        print(f"{Fore.YELLOW}💤 No active positions.")

    print("=" * 70 + "\n")

if __name__ == "__main__":
    try:
        get_pnl_report()
    except Exception as e:
        print(f"❌ Error: {e}")