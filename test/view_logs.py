"""
Comprehensive Log Viewer for Trading System

Provides easy access to all system logs with filtering, tailing, and monitoring capabilities.

Usage:
    python test/view_logs.py                    # Interactive menu
    python test/view_logs.py --tail             # Tail all logs
    python test/view_logs.py --service fleet    # View specific service
    python test/view_logs.py --errors           # Show only errors
    python test/view_logs.py --bot Alpha        # Filter by bot name
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from colorama import Fore, Style, init
import subprocess

# Initialize colorama
init(autoreset=True)

# Log file locations
LOGS = {
    'fleet': {
        'path': '/Users/johnny_main/Developer/data/logs/fleet_launchd.err',
        'description': 'Fleet Runner execution logs (all bots)',
        'color': Fore.CYAN
    },
    'parser': {
        'path': '/Users/johnny_main/Developer/data/logs/telegram_signals_sqlite.log',
        'description': 'Signal parser logs (telegram → database)',
        'color': Fore.GREEN
    },
    'parser_error': {
        'path': '/Users/johnny_main/Developer/data/logs/telegram_signals_sqlite_error.log',
        'description': 'Signal parser error logs',
        'color': Fore.RED
    },
    'forwarder': {
        'path': '/Users/johnny_main/Developer/data/logs/telegram_forwarder.log',
        'description': 'Telegram message forwarder logs',
        'color': Fore.YELLOW
    },
    'forwarder_error': {
        'path': '/Users/johnny_main/Developer/data/logs/telegram_forwarder_error.log',
        'description': 'Telegram forwarder error logs',
        'color': Fore.RED
    }
}

BOTS = ['AlphaCryptoSignal', 'SentientGuard', 'Apprentice Alchemist', 'Alpha', 'Sentient', 'Apprentice']


def check_log_status():
    """Check status of all log files"""
    print(f"\n{Style.BRIGHT}{'='*80}")
    print(f"{Fore.CYAN}{Style.BRIGHT}LOG FILE STATUS")
    print(f"{'='*80}\n")

    for name, info in LOGS.items():
        path = info['path']
        exists = os.path.exists(path)

        if exists:
            size = os.path.getsize(path)
            mtime = os.path.getmtime(path)
            age = datetime.now() - datetime.fromtimestamp(mtime)

            status = f"{Fore.GREEN}✓ EXISTS"
            details = f"Size: {size:,} bytes | Last modified: {age.seconds//60}m {age.seconds%60}s ago"
        else:
            status = f"{Fore.RED}✗ MISSING"
            details = "File not found"

        print(f"{info['color']}{name:<20} {status}")
        print(f"  Path: {path}")
        print(f"  {details}")
        print(f"  {info['description']}")
        print()


def tail_log(log_name, lines=50, follow=False):
    """Tail a specific log file"""
    if log_name not in LOGS:
        print(f"{Fore.RED}Unknown log: {log_name}")
        print(f"Available logs: {', '.join(LOGS.keys())}")
        return

    info = LOGS[log_name]
    path = info['path']

    if not os.path.exists(path):
        print(f"{Fore.RED}Log file not found: {path}")
        return

    print(f"\n{Style.BRIGHT}{'='*80}")
    print(f"{info['color']}{Style.BRIGHT}{info['description'].upper()}")
    print(f"{Style.BRIGHT}{'='*80}\n")

    if follow:
        # Use tail -f for live following
        try:
            subprocess.run(['tail', '-f', path])
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Stopped following log")
    else:
        # Read last N lines
        try:
            result = subprocess.run(['tail', f'-{lines}', path], capture_output=True, text=True)
            print(result.stdout)
        except Exception as e:
            print(f"{Fore.RED}Error reading log: {e}")


def view_all_logs(lines=20):
    """View recent entries from all logs"""
    print(f"\n{Style.BRIGHT}{'='*80}")
    print(f"{Fore.CYAN}{Style.BRIGHT}RECENT LOG ENTRIES (last {lines} lines per log)")
    print(f"{Style.BRIGHT}{'='*80}\n")

    for name, info in LOGS.items():
        path = info['path']

        if not os.path.exists(path):
            continue

        print(f"{info['color']}{Style.BRIGHT}[{name.upper()}] {info['description']}")
        print(f"{Style.DIM}─────────────────────────────────────────────────────────────────────────────────{Style.RESET_ALL}")

        try:
            result = subprocess.run(['tail', f'-{lines}', path], capture_output=True, text=True)
            lines_output = result.stdout.strip().split('\n')

            for line in lines_output:
                # Color code by severity
                if 'ERROR' in line or '❌' in line:
                    print(f"{Fore.RED}{line}")
                elif 'WARNING' in line or '⚠️' in line:
                    print(f"{Fore.YELLOW}{line}")
                elif 'SUCCESS' in line or '✅' in line:
                    print(f"{Fore.GREEN}{line}")
                else:
                    print(line)

            print()
        except Exception as e:
            print(f"{Fore.RED}Error reading log: {e}\n")


def filter_by_bot(bot_name, lines=100):
    """Show log entries for a specific bot"""
    print(f"\n{Style.BRIGHT}{'='*80}")
    print(f"{Fore.CYAN}{Style.BRIGHT}LOGS FOR: {bot_name}")
    print(f"{Style.BRIGHT}{'='*80}\n")

    found_any = False

    # Search fleet logs
    fleet_path = LOGS['fleet']['path']
    if os.path.exists(fleet_path):
        try:
            result = subprocess.run(['grep', '-i', bot_name, fleet_path], capture_output=True, text=True)
            if result.stdout:
                print(f"{Fore.CYAN}{Style.BRIGHT}[FLEET LOGS]")
                print(f"{Style.DIM}─────────────────────────────────────────────────────────────────────────────────{Style.RESET_ALL}")

                lines_output = result.stdout.strip().split('\n')[-lines:]
                for line in lines_output:
                    if 'ERROR' in line or '❌' in line:
                        print(f"{Fore.RED}{line}")
                    elif 'WARNING' in line or '⚠️' in line:
                        print(f"{Fore.YELLOW}{line}")
                    elif 'SUCCESS' in line or '✅' in line:
                        print(f"{Fore.GREEN}{line}")
                    else:
                        print(line)
                print()
                found_any = True
        except:
            pass

    # Search parser logs
    parser_path = LOGS['parser']['path']
    if os.path.exists(parser_path):
        try:
            result = subprocess.run(['grep', '-i', bot_name, parser_path], capture_output=True, text=True)
            if result.stdout:
                print(f"{Fore.GREEN}{Style.BRIGHT}[PARSER LOGS]")
                print(f"{Style.DIM}─────────────────────────────────────────────────────────────────────────────────{Style.RESET_ALL}")

                lines_output = result.stdout.strip().split('\n')[-lines:]
                for line in lines_output:
                    print(line)
                print()
                found_any = True
        except:
            pass

    if not found_any:
        print(f"{Fore.YELLOW}No log entries found for bot: {bot_name}")


def show_errors(lines=50):
    """Show only error and warning messages"""
    print(f"\n{Style.BRIGHT}{'='*80}")
    print(f"{Fore.RED}{Style.BRIGHT}ERRORS & WARNINGS (last {lines} entries)")
    print(f"{Style.BRIGHT}{'='*80}\n")

    found_any = False

    for name, info in LOGS.items():
        path = info['path']

        if not os.path.exists(path):
            continue

        try:
            # Grep for ERROR or WARNING
            result = subprocess.run(
                ['grep', '-E', '(ERROR|WARNING|❌|⚠️|FAILED|Failed)', path],
                capture_output=True,
                text=True
            )

            if result.stdout:
                print(f"{info['color']}{Style.BRIGHT}[{name.upper()}]")
                print(f"{Style.DIM}─────────────────────────────────────────────────────────────────────────────────{Style.RESET_ALL}")

                lines_output = result.stdout.strip().split('\n')[-lines:]
                for line in lines_output:
                    if 'ERROR' in line or '❌' in line:
                        print(f"{Fore.RED}{line}")
                    else:
                        print(f"{Fore.YELLOW}{line}")

                print()
                found_any = True
        except:
            pass

    if not found_any:
        print(f"{Fore.GREEN}✅ No errors or warnings found in recent logs!")


def tail_all(follow=False):
    """Tail all logs simultaneously"""
    print(f"\n{Style.BRIGHT}{'='*80}")
    print(f"{Fore.CYAN}{Style.BRIGHT}MONITORING ALL LOGS")
    print(f"{Style.BRIGHT}{'='*80}\n")

    existing_logs = [info['path'] for info in LOGS.values() if os.path.exists(info['path'])]

    if not existing_logs:
        print(f"{Fore.RED}No log files found!")
        return

    if follow:
        print(f"{Fore.YELLOW}Following logs (Ctrl-C to stop)...")
        print(f"Watching {len(existing_logs)} log files\n")
        try:
            # Use tail -f with multiple files
            subprocess.run(['tail', '-f'] + existing_logs)
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Stopped following logs")
    else:
        # Show last 20 lines from each
        for name, info in LOGS.items():
            if os.path.exists(info['path']):
                print(f"{info['color']}{Style.BRIGHT}[{name.upper()}]")
                result = subprocess.run(['tail', '-20', info['path']], capture_output=True, text=True)
                print(result.stdout)
                print()


def interactive_menu():
    """Show interactive menu"""
    while True:
        print(f"\n{Style.BRIGHT}{'='*80}")
        print(f"{Fore.CYAN}{Style.BRIGHT}TRADING SYSTEM LOG VIEWER")
        print(f"{Style.BRIGHT}{'='*80}\n")

        print(f"{Fore.GREEN}1. Check log file status")
        print(f"{Fore.GREEN}2. View all recent logs")
        print(f"{Fore.GREEN}3. Tail specific log")
        print(f"{Fore.GREEN}4. Filter by bot name")
        print(f"{Fore.GREEN}5. Show errors only")
        print(f"{Fore.GREEN}6. Tail all logs (live)")
        print(f"{Fore.GREEN}7. Fleet logs (last 50 lines)")
        print(f"{Fore.GREEN}8. Parser logs (last 50 lines)")
        print(f"{Fore.RED}0. Exit")

        choice = input(f"\n{Fore.CYAN}Enter choice: {Style.RESET_ALL}").strip()

        if choice == '0':
            print(f"{Fore.YELLOW}Goodbye!")
            break
        elif choice == '1':
            check_log_status()
        elif choice == '2':
            view_all_logs(lines=20)
        elif choice == '3':
            print(f"\n{Fore.CYAN}Available logs:")
            for i, name in enumerate(LOGS.keys(), 1):
                print(f"  {i}. {name}")
            log_choice = input(f"{Fore.CYAN}Enter log name: {Style.RESET_ALL}").strip()
            if log_choice in LOGS:
                tail_log(log_choice, lines=50)
        elif choice == '4':
            print(f"\n{Fore.CYAN}Common bot names: {', '.join(BOTS)}")
            bot = input(f"{Fore.CYAN}Enter bot name: {Style.RESET_ALL}").strip()
            filter_by_bot(bot)
        elif choice == '5':
            show_errors()
        elif choice == '6':
            tail_all(follow=True)
        elif choice == '7':
            tail_log('fleet', lines=50)
        elif choice == '8':
            tail_log('parser', lines=50)
        else:
            print(f"{Fore.RED}Invalid choice")

        input(f"\n{Fore.CYAN}Press Enter to continue...")


def main():
    parser = argparse.ArgumentParser(description='View trading system logs')
    parser.add_argument('--status', action='store_true', help='Check log file status')
    parser.add_argument('--tail', action='store_true', help='Tail all logs')
    parser.add_argument('--follow', '-f', action='store_true', help='Follow logs in real-time')
    parser.add_argument('--service', choices=list(LOGS.keys()), help='View specific service log')
    parser.add_argument('--bot', help='Filter by bot name')
    parser.add_argument('--errors', action='store_true', help='Show only errors')
    parser.add_argument('--lines', '-n', type=int, default=50, help='Number of lines to show')

    args = parser.parse_args()

    if args.status:
        check_log_status()
    elif args.tail:
        tail_all(follow=args.follow)
    elif args.service:
        tail_log(args.service, lines=args.lines, follow=args.follow)
    elif args.bot:
        filter_by_bot(args.bot, lines=args.lines)
    elif args.errors:
        show_errors(lines=args.lines)
    else:
        # No args, show interactive menu
        interactive_menu()


if __name__ == "__main__":
    main()
