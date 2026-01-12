"""
Signal Flow Tracer

Traces a signal through the entire pipeline:
Telegram → Parser → Database → Fleet → Hyperliquid

Shows timing, status changes, and identifies where issues occurred.

Usage:
    python test/trace_signal.py --symbol POL
    python test/trace_signal.py --signal-id 7
    python test/trace_signal.py --bot Alpha --recent 5
    python test/trace_signal.py --all  # Show all recent signals
"""

import os
import sys
import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from colorama import Fore, Style, init

init(autoreset=True)


class SignalTracer:
    def __init__(self):
        self.db_path = "/Users/johnny_main/Developer/data/signals/signals.db"
        self.fleet_log = "/Users/johnny_main/Developer/data/logs/fleet_launchd.err"
        self.parser_log = "/Users/johnny_main/Developer/data/logs/telegram_signals_sqlite.log"

    def get_signal_from_db(self, signal_id=None, symbol=None, bot_name=None, limit=5):
        """Retrieve signal(s) from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if signal_id:
                query = "SELECT * FROM signals WHERE id = ?"
                cursor.execute(query, (signal_id,))
                result = cursor.fetchone()
                conn.close()
                return [dict(result)] if result else []

            elif symbol:
                query = """
                    SELECT * FROM signals
                    WHERE symbol = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                cursor.execute(query, (symbol.upper(), limit))

            elif bot_name:
                # Handle short names
                bot_mapping = {
                    'Alpha': 'AlphaCryptoSignal',
                    'Sentient': 'SentientGuard',
                    'Apprentice': 'Apprentice Alchemist'
                }
                full_bot_name = bot_mapping.get(bot_name, bot_name)

                query = """
                    SELECT * FROM signals
                    WHERE bot_name LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                cursor.execute(query, (f'%{full_bot_name}%', limit))

            else:
                query = """
                    SELECT * FROM signals
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                cursor.execute(query, (limit,))

            results = cursor.fetchall()
            conn.close()
            return [dict(row) for row in results]

        except Exception as e:
            print(f"{Fore.RED}Database error: {e}")
            return []

    def search_logs(self, log_file, search_terms, context_lines=3):
        """Search log file for specific terms and return matches with context"""
        if not Path(log_file).exists():
            return []

        matches = []
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()

            for i, line in enumerate(lines):
                if any(term.lower() in line.lower() for term in search_terms):
                    # Get context lines
                    start = max(0, i - context_lines)
                    end = min(len(lines), i + context_lines + 1)
                    context = ''.join(lines[start:end])
                    matches.append({
                        'line_num': i + 1,
                        'line': line.strip(),
                        'context': context
                    })

        except Exception as e:
            print(f"{Fore.YELLOW}Warning: Could not read {log_file}: {e}")

        return matches

    def trace_signal(self, signal):
        """Trace a single signal through the pipeline"""
        signal_id = signal['id']
        symbol = signal['symbol']
        signal_type = signal['signal_type']
        status = signal['status']
        created_at = signal['created_at']
        bot_name = signal['bot_name']

        print(f"\n{Style.BRIGHT}{'='*80}")
        print(f"{Fore.CYAN}{Style.BRIGHT}SIGNAL TRACE: ID {signal_id} - {symbol} {signal_type.upper()}")
        print(f"{Style.BRIGHT}{'='*80}\n")

        # Timeline header
        print(f"{Style.BRIGHT}TIMELINE:")
        print(f"{Style.DIM}─────────────────────────────────────────────────────────────────────────────────\n")

        # Step 1: Database record
        created_time = datetime.fromisoformat(created_at)
        print(f"{Fore.CYAN}{created_time.strftime('%H:%M:%S.%f')[:-3]} ⟶ DATABASE: Signal ID {signal_id} inserted")
        print(f"{Style.DIM}                     Status: {status}")
        print(f"{Style.DIM}                     Bot: {bot_name}")
        print(f"{Style.DIM}                     Type: {signal_type}")

        if signal_type == 'entry':
            entry_price = signal.get('entry_1')
            stop_loss = signal.get('stop_loss')
            target = signal.get('target_1')
            direction = signal.get('direction', 'N/A')
            print(f"{Style.DIM}                     Direction: {direction}")
            print(f"{Style.DIM}                     Entry: {entry_price}")
            print(f"{Style.DIM}                     Stop: {stop_loss}")
            print(f"{Style.DIM}                     Target: {target}")
        else:
            exit_price = signal.get('target_1')
            pnl = signal.get('notes', '')
            print(f"{Style.DIM}                     Exit Price: {exit_price}")
            print(f"{Style.DIM}                     Notes: {pnl}")

        print()

        # Step 2: Parser logs
        parser_matches = self.search_logs(
            self.parser_log,
            [symbol, f"ID: {signal_id}"],
            context_lines=2
        )

        if parser_matches:
            for match in parser_matches[:3]:  # Show first 3 matches
                print(f"{Fore.GREEN}XX:XX:XX.XXX ⟶ PARSER: {match['line']}")
            print()
        else:
            print(f"{Fore.YELLOW}XX:XX:XX.XXX ⟶ PARSER: No specific log entries found")
            print(f"{Style.DIM}                     (Parser may have logged to aggregation channel activity)")
            print()

        # Step 3: Fleet execution logs
        fleet_matches = self.search_logs(
            self.fleet_log,
            [symbol, f"Signal {signal_id}", f"signal_id={signal_id}"],
            context_lines=5
        )

        if fleet_matches:
            for match in fleet_matches:
                line = match['line']
                if 'SUCCESS' in line or '✅' in line:
                    print(f"{Fore.GREEN}XX:XX:XX.XXX ⟶ FLEET: {line}")
                elif 'ERROR' in line or '❌' in line or 'FAILED' in line:
                    print(f"{Fore.RED}XX:XX:XX.XXX ⟶ FLEET: {line}")
                else:
                    print(f"{Fore.BLUE}XX:XX:XX.XXX ⟶ FLEET: {line}")
            print()
        else:
            if status in ['pending', 'failed']:
                print(f"{Fore.RED}XX:XX:XX.XXX ⟶ FLEET: Signal not processed (status: {status})")
                print(f"{Style.DIM}                     Check if fleet_runner is running")
                print(f"{Style.DIM}                     Check bot_id matches in FLEET_CONFIG")
            else:
                print(f"{Fore.YELLOW}XX:XX:XX.XXX ⟶ FLEET: No log entries found, but status is '{status}'")
            print()

        # Step 4: Analysis
        print(f"{Style.BRIGHT}ANALYSIS:")
        print(f"{Style.DIM}─────────────────────────────────────────────────────────────────────────────────\n")

        if status == 'filled' or status == 'executed':
            print(f"{Fore.GREEN}✅ Signal successfully processed")
            if signal_type == 'entry':
                print(f"{Style.DIM}   Entry order should be filled on Hyperliquid")
            else:
                print(f"{Style.DIM}   Exit order should be completed on Hyperliquid")
        elif status == 'pending':
            print(f"{Fore.YELLOW}⏳ Signal is pending")
            print(f"{Style.DIM}   Possible reasons:")
            print(f"{Style.DIM}   - Fleet runner not running")
            print(f"{Style.DIM}   - Bot paused via admin controls")
            print(f"{Style.DIM}   - Signal queue backlog")
        elif status == 'failed':
            notes = signal.get('notes', '')
            print(f"{Fore.RED}❌ Signal failed")
            print(f"{Style.DIM}   Error: {notes}")
        else:
            print(f"{Fore.CYAN}ℹ️  Signal status: {status}")

        # Check for related signals
        if signal_type == 'entry':
            # Look for corresponding exit
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM signals
                    WHERE symbol = ?
                    AND bot_name = ?
                    AND signal_type = 'exit'
                    AND created_at > ?
                    ORDER BY created_at ASC
                    LIMIT 1
                """, (symbol, bot_name, created_at))
                exit_signal = cursor.fetchone()
                conn.close()

                if exit_signal:
                    exit_id = exit_signal['id']
                    exit_time = exit_signal['created_at']
                    print(f"\n{Fore.CYAN}🔗 Related Exit Signal: ID {exit_id} at {exit_time}")
                else:
                    print(f"\n{Fore.YELLOW}⚠️  No exit signal found yet (position may still be open)")

            except Exception as e:
                pass

        print()

    def trace_all(self, signals):
        """Trace multiple signals"""
        print(f"\n{Fore.CYAN}{Style.BRIGHT}TRACING {len(signals)} SIGNALS")

        for i, signal in enumerate(signals):
            self.trace_signal(signal)
            if i < len(signals) - 1:
                print(f"\n{Style.DIM}{'─'*80}\n")


def main():
    parser = argparse.ArgumentParser(description='Trace signal flow through the pipeline')
    parser.add_argument('--signal-id', type=int, help='Trace specific signal ID')
    parser.add_argument('--symbol', help='Trace signals for specific symbol')
    parser.add_argument('--bot', help='Trace signals for specific bot (Alpha, Sentient, Apprentice)')
    parser.add_argument('--recent', type=int, default=5, help='Number of recent signals to show (default: 5)')
    parser.add_argument('--all', action='store_true', help='Show all recent signals')

    args = parser.parse_args()

    tracer = SignalTracer()

    if args.signal_id:
        signals = tracer.get_signal_from_db(signal_id=args.signal_id)
        if not signals:
            print(f"{Fore.RED}Signal ID {args.signal_id} not found in database")
            sys.exit(1)
    elif args.symbol:
        signals = tracer.get_signal_from_db(symbol=args.symbol, limit=args.recent)
        if not signals:
            print(f"{Fore.RED}No signals found for symbol {args.symbol}")
            sys.exit(1)
    elif args.bot:
        signals = tracer.get_signal_from_db(bot_name=args.bot, limit=args.recent)
        if not signals:
            print(f"{Fore.RED}No signals found for bot {args.bot}")
            sys.exit(1)
    elif args.all:
        signals = tracer.get_signal_from_db(limit=args.recent)
        if not signals:
            print(f"{Fore.RED}No signals found in database")
            sys.exit(1)
    else:
        # Default: show most recent signals
        signals = tracer.get_signal_from_db(limit=args.recent)
        if not signals:
            print(f"{Fore.RED}No signals found in database")
            sys.exit(1)

    tracer.trace_all(signals)


if __name__ == "__main__":
    main()
