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

def extract_telegram_pnl(row):
    """
    Extract PnL from Telegram message (pnl_percent column or notes).
    This represents the signal provider's reported PnL.
    """
    # Check pnl_percent column first
    val = row['pnl_percent']
    try:
        if isinstance(val, (int, float)) and abs(val) > 0.001:
            return float(val)
    except:
        pass

    # Regex fallback from notes
    match = re.search(r'Return:\s*([-\d.]+)%', str(row['notes']))
    if match:
        try:
            return float(match.group(1))
        except:
            return 0.0

    return 0.0

def extract_actual_pnl(row):
    """
    Extract actual PnL from Hyperliquid execution (pnl_percent_actual column).
    This represents the bot's actual realized PnL.
    """
    val = row.get('pnl_percent_actual')
    try:
        if pd.notna(val) and isinstance(val, (int, float)):
            return float(val)
    except:
        pass
    return None  # Return None if not available

def get_pnl_report():
    conn = sqlite3.connect(DB_PATH)

    # 1. FETCH DATA
    query = """
        SELECT id, bot_name, symbol, signal_type, status,
               entry_1, position_size_actual, pnl_percent, pnl_percent_actual, created_at, notes
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

    # 3. Calculate PnL from both sources
    df['telegram_pnl'] = df.apply(extract_telegram_pnl, axis=1)
    df['actual_pnl'] = df.apply(extract_actual_pnl, axis=1)

    # 4. Separate Dataframes
    # Open entries (still active - 'filled' = confirmed, 'sent' = order placed awaiting fill)
    entries = df[(df['signal_type'] == 'entry') & (df['status'].isin(['filled', 'sent']))].copy()

    # Closed entries (auto-closed by reconciliation, TP/SL, etc.)
    closed_entries = df[(df['signal_type'] == 'entry') & (df['status'] == 'closed')].copy()

    # Exit signals (manual exits via exit signal)
    all_exits = df[(df['signal_type'] == 'exit') & (df['status'] == 'executed')].copy()

    # 5. COMBINE CLOSED TRADES: Include both exit signals and auto-closed entries
    # A. Filter exit signals to only include those with matching entries
    exits = []
    for idx, exit_row in all_exits.iterrows():
        bot = exit_row['bot_name']
        symbol = exit_row['symbol']
        exit_time = pd.to_datetime(exit_row['created_at'])

        # Find entries for this bot+symbol that occurred BEFORE this exit
        matching_entries = entries[
            (entries['bot_name'] == bot) &
            (entries['symbol'] == symbol) &
            (pd.to_datetime(entries['created_at']) < exit_time)
        ]

        # Only include exit if there's at least one matching entry
        if len(matching_entries) > 0:
            exits.append(exit_row)

    # B. Add closed entries as "exits" (they represent completed trades)
    # Use actual_pnl from closed entries for stats
    for idx, closed_row in closed_entries.iterrows():
        exits.append(closed_row)

    # Convert back to DataFrame
    exits = pd.DataFrame(exits) if exits else pd.DataFrame(columns=df.columns)

    # --- SECTION A: PERFORMANCE TABLE ---
    print(f"\n{Style.BRIGHT}{Fore.CYAN}📊 HYPERLIQUID FLEET REPORT (Bot-Executed Trades Only)")
    print("=" * 100)

    bots = df['bot_name'].unique()

    total_wins = 0
    total_trades = 0

    print(f"{Style.BRIGHT}{'BOT NAME':<25} | {'TRADES':<6} | {'WIN RATE':<9} | {'AVG PNL (TG)':<13} | {'AVG PNL (HL)':<13}")
    print("-" * 100)

    for bot in bots:
        # Filter exits for this bot
        bot_exits = exits[exits['bot_name'] == bot]
        count = len(bot_exits)

        if count > 0:
            # Stats Calculation (using Telegram PnL for win rate)
            wins = bot_exits[bot_exits['telegram_pnl'] > 0]
            win_rate = (len(wins) / count) * 100

            # Calculate average PnL from both sources
            avg_telegram_pnl = bot_exits['telegram_pnl'].mean()
            if pd.isna(avg_telegram_pnl): avg_telegram_pnl = 0.0

            # Actual PnL (may be None if not available)
            actual_values = bot_exits['actual_pnl'].dropna()
            if len(actual_values) > 0:
                avg_actual_pnl = actual_values.mean()
                actual_pnl_str = f"{avg_actual_pnl:>6.2f}%"
                actual_color = Fore.GREEN if avg_actual_pnl > 0 else Fore.RED
            else:
                actual_pnl_str = "N/A"
                actual_color = Fore.YELLOW

            # Formatting Colors
            wr_color = Fore.GREEN if win_rate >= 50 else Fore.RED
            tg_pnl_color = Fore.GREEN if avg_telegram_pnl > 0 else Fore.RED

            print(f"{Fore.WHITE}{bot:<25} | {count:<6} | {wr_color}{win_rate:>6.1f}%{Fore.RESET}  | "
                  f"{tg_pnl_color}{avg_telegram_pnl:>6.2f}%{Fore.RESET}      | "
                  f"{actual_color}{actual_pnl_str:<13}")

            total_wins += len(wins)
            total_trades += count
        else:
            # Empty row
            print(f"{Fore.WHITE}{bot:<25} | {0:<6} | {'N/A':<9} | {'N/A':<13} | {'N/A':<13}")

    print("=" * 100)

    if total_trades > 0:
        global_wr = (total_wins / total_trades) * 100
        print(f"{Style.BRIGHT}🏆 FLEET TOTAL: {total_trades} Bot-Executed Trades | Win Rate: {global_wr:.1f}%")
    else:
        print(f"{Fore.YELLOW}No closed trades yet. All exit signals were phantom trades (no matching entries).")
    print(f"{Style.DIM}* TG = Telegram (signal provider PnL), HL = Hyperliquid (actual bot execution PnL){Style.RESET_ALL}")
    print("=" * 100)

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
            # TIME-ORDERED NETTING: Chronologically process entries and exits
            sym_entries = bot_entries[bot_entries['symbol'] == sym].copy()
            sym_exits = bot_exits[bot_exits['symbol'] == sym].copy()

            # Combine all events and sort by timestamp
            all_events = []
            for _, row in sym_entries.iterrows():
                all_events.append(('entry', pd.to_datetime(row['created_at']), row))
            for _, row in sym_exits.iterrows():
                all_events.append(('exit', pd.to_datetime(row['created_at']), row))

            # Sort by timestamp
            all_events.sort(key=lambda x: x[1])

            # Track open positions chronologically
            open_positions = []
            for event_type, timestamp, row in all_events:
                if event_type == 'entry':
                    open_positions.append(row)
                elif event_type == 'exit' and open_positions:
                    # Close the oldest position (FIFO)
                    open_positions.pop(0)

            open_count = len(open_positions)

            if open_count > 0:
                active_found = True
                # Display the currently open positions
                specific_entries = pd.DataFrame(open_positions)
                
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