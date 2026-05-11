"""
Configuration Audit Tool

Validates system configuration and identifies potential issues.

Usage:
    python test/audit_config.py
    python test/audit_config.py --verbose  # Show detailed output
"""

import os
import sys
import subprocess
import sqlite3
from pathlib import Path
from colorama import Fore, Style, init
from datetime import datetime

init(autoreset=True)


class ConfigAuditor:
    def __init__(self, verbose=False):
        self.issues = []
        self.warnings = []
        self.successes = []
        self.verbose = verbose

    def log_issue(self, msg):
        """Log a critical issue"""
        self.issues.append(msg)
        print(f"{Fore.RED}❌ ISSUE: {msg}")

    def log_warning(self, msg):
        """Log a warning"""
        self.warnings.append(msg)
        print(f"{Fore.YELLOW}⚠️  WARNING: {msg}")

    def log_success(self, msg):
        """Log a success"""
        self.successes.append(msg)
        if self.verbose:
            print(f"{Fore.GREEN}✅ {msg}")

    def check_env_files(self):
        """Verify .env files exist and contain required keys"""
        print(f"\n{Style.BRIGHT}{'='*80}")
        print(f"{Fore.CYAN}{Style.BRIGHT}1. CHECKING ENVIRONMENT FILES")
        print(f"{Style.BRIGHT}{'='*80}\n")

        # Check fleet .env
        fleet_env = Path("/Users/johnny_main/Developer/projects/telegram_trading_bots/hyper_v1/.env")
        if fleet_env.exists():
            self.log_success(f"Fleet .env found: {fleet_env}")

            # Check required keys
            required_fleet_keys = [
                'PRIVATE_KEY_SENTIENT',
                'PRIVATE_KEY_ALCHEMIST',
                'PRIVATE_KEY_ALPHA',
                'RISK_PER_TRADE',
                'MAX_LEVERAGE',
                'IS_MAINNET'
            ]

            with open(fleet_env) as f:
                content = f.read()
                for key in required_fleet_keys:
                    if key in content:
                        self.log_success(f"Fleet .env has {key}")
                    else:
                        self.log_warning(f"Fleet .env missing {key}")
        else:
            self.log_issue(f"Fleet .env not found: {fleet_env}")

        # Check forwarder .env
        forwarder_env = Path("/Users/johnny_main/Developer/projects/telegram_forwarder/.env")
        if forwarder_env.exists():
            self.log_success(f"Forwarder .env found: {forwarder_env}")

            # Check required keys
            required_forwarder_keys = [
                'TELEGRAM_SOURCE_1_CHANNEL_ID',
                'TELEGRAM_SOURCE_2_CHANNEL_ID',
                'TELEGRAM_AGGREGATION_CHANNEL_ID',
                'DUPLICATE_DETECTION_HOURS',
                'ALPHA_EXIT_KEYWORDS'
            ]

            with open(forwarder_env) as f:
                content = f.read()
                for key in required_forwarder_keys:
                    if key in content:
                        self.log_success(f"Forwarder .env has {key}")
                    else:
                        self.log_warning(f"Forwarder .env missing {key}")
        else:
            self.log_issue(f"Forwarder .env not found: {forwarder_env}")

    def check_services(self):
        """Verify launchd services are running"""
        print(f"\n{Style.BRIGHT}{'='*80}")
        print(f"{Fore.CYAN}{Style.BRIGHT}2. CHECKING SERVICES")
        print(f"{Style.BRIGHT}{'='*80}\n")

        services = {
            'com.telegram.signals': 'Telegram signal parser',
            'com.telegram.forwarder': 'Telegram message forwarder'
        }

        for service_name, description in services.items():
            try:
                result = subprocess.run(
                    ['launchctl', 'list'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if service_name in result.stdout:
                    # Extract PID
                    for line in result.stdout.split('\n'):
                        if service_name in line:
                            parts = line.split()
                            pid = parts[0]
                            if pid != '-':
                                self.log_success(f"{description} ({service_name}) running (PID: {pid})")
                            else:
                                self.log_warning(f"{description} ({service_name}) loaded but not running")
                            break
                else:
                    self.log_warning(f"{description} ({service_name}) not loaded")

            except Exception as e:
                self.log_issue(f"Error checking {service_name}: {e}")

    def check_parser_capabilities(self):
        """Test parser functions"""
        print(f"\n{Style.BRIGHT}{'='*80}")
        print(f"{Fore.CYAN}{Style.BRIGHT}3. CHECKING PARSER CAPABILITIES")
        print(f"{Style.BRIGHT}{'='*80}\n")

        # Add telegram_forwarder to path
        sys.path.insert(0, '/Users/johnny_main/Developer/projects/telegram_forwarder')

        try:
            from telegram_signals_to_sqlite import SignalParser

            # Test AlphaCrypto entry parsing
            test_entry = """
Pair: $TEST/USDT
Direction: LONG
Entry: 1) 1.234
Take Profit: 1) 1.500
Stop Limit: 1.000
Leverage: 5x
"""
            entry_result = SignalParser.parse_alpha_crypto_signal(test_entry)
            if entry_result and len(entry_result) > 0:
                self.log_success("AlphaCrypto entry parsing works")
                if entry_result[0].get('direction') == 'long':
                    self.log_success("AlphaCrypto stores lowercase direction")
                else:
                    self.log_warning(f"AlphaCrypto direction is '{entry_result[0].get('direction')}', expected 'long'")
            else:
                self.log_warning("AlphaCrypto entry parsing returned no results")

            # Test AlphaCrypto exit parsing
            test_exit = """
Pair: $TEST/USDT
Target 1 Hit @ 1.500
Entry: 1.234
PnL: +21.5%
Status: Take Profit Executed
"""
            exit_result = SignalParser.parse_alpha_crypto_signal(test_exit)
            if exit_result and len(exit_result) > 0:
                signal = exit_result[0]
                if signal.get('signal_type') == 'exit':
                    self.log_success("AlphaCrypto exit parsing works")
                    if signal.get('exit_price') or signal.get('target_1'):
                        self.log_success("Exit price extracted successfully")
                    if signal.get('pnl_percent'):
                        self.log_success("PnL percentage extracted successfully")
                else:
                    self.log_warning("AlphaCrypto exit parser returned entry signal instead of exit")
            else:
                self.log_warning("AlphaCrypto exit parsing returned no results")

            # Test AITA parsing
            test_aita = """
Trade Summary:
BTC Bullish Entry
Entry: 50000
Target: 55000
Stop: 48000
"""
            aita_result = SignalParser.parse_aita_signal(test_aita)
            if aita_result and len(aita_result) > 0:
                self.log_success("AITA signal parsing works")
            else:
                self.log_warning("AITA signal parsing returned no results")

        except ImportError as e:
            self.log_issue(f"Cannot import parser module: {e}")
        except Exception as e:
            self.log_issue(f"Parser test failed: {e}")

    def check_database(self):
        """Validate database schema and connections"""
        print(f"\n{Style.BRIGHT}{'='*80}")
        print(f"{Fore.CYAN}{Style.BRIGHT}4. CHECKING DATABASE")
        print(f"{Style.BRIGHT}{'='*80}\n")

        db_path = Path("/Users/johnny_main/Developer/data/signals/signals.db")

        if not db_path.exists():
            self.log_issue(f"Database not found: {db_path}")
            return

        self.log_success(f"Database found: {db_path}")

        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Check signals table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signals'")
            if cursor.fetchone():
                self.log_success("Signals table exists")

                # Check required columns
                cursor.execute("PRAGMA table_info(signals)")
                columns = {row[1] for row in cursor.fetchall()}

                required_columns = [
                    'id', 'symbol', 'direction', 'signal_type', 'status',
                    'entry_1', 'target_1', 'stop_loss', 'bot_name',
                    'provider', 'created_at', 'notes'
                ]

                for col in required_columns:
                    if col in columns:
                        self.log_success(f"Column '{col}' exists")
                    else:
                        self.log_warning(f"Column '{col}' missing")

                # Check for recent signals
                cursor.execute("SELECT COUNT(*) FROM signals WHERE created_at > datetime('now', '-7 days')")
                recent_count = cursor.fetchone()[0]
                if recent_count > 0:
                    self.log_success(f"Found {recent_count} signals in last 7 days")
                else:
                    self.log_warning("No signals found in last 7 days")

                # Check for AlphaCrypto signals
                cursor.execute("SELECT COUNT(*) FROM signals WHERE bot_name='AlphaCryptoSignal'")
                alpha_count = cursor.fetchone()[0]
                if alpha_count > 0:
                    self.log_success(f"Found {alpha_count} AlphaCryptoSignal signals")

                    # Check for exit signals
                    cursor.execute("SELECT COUNT(*) FROM signals WHERE bot_name='AlphaCryptoSignal' AND signal_type='exit'")
                    exit_count = cursor.fetchone()[0]
                    if exit_count > 0:
                        self.log_success(f"Found {exit_count} AlphaCrypto exit signals")
                    else:
                        self.log_warning("No AlphaCrypto exit signals found yet (exit parsing newly added)")

            else:
                self.log_issue("Signals table does not exist")

            # Test write permissions
            try:
                cursor.execute("SELECT 1")
                self.log_success("Database is readable")
            except Exception as e:
                self.log_issue(f"Database read test failed: {e}")

            conn.close()

        except Exception as e:
            self.log_issue(f"Database connection failed: {e}")

    def check_log_files(self):
        """Check log file locations and permissions"""
        print(f"\n{Style.BRIGHT}{'='*80}")
        print(f"{Fore.CYAN}{Style.BRIGHT}5. CHECKING LOG FILES")
        print(f"{Style.BRIGHT}{'='*80}\n")

        log_files = {
            '/Users/johnny_main/Developer/data/logs/fleet_launchd.err': 'Fleet runner execution',
            '/Users/johnny_main/Developer/data/logs/telegram_signals_sqlite.log': 'Signal parser stdout',
            '/Users/johnny_main/Developer/data/logs/telegram_signals_sqlite_error.log': 'Signal parser stderr',
            '/Users/johnny_main/Developer/data/logs/telegram_forwarder.log': 'Message forwarder stdout',
            '/Users/johnny_main/Developer/data/logs/telegram_forwarder_error.log': 'Message forwarder stderr'
        }

        for log_path, description in log_files.items():
            path = Path(log_path)
            if path.exists():
                # Check age
                mtime = datetime.fromtimestamp(path.stat().st_mtime)
                age = datetime.now() - mtime
                age_str = f"{age.seconds // 60}m {age.seconds % 60}s ago"

                # Check size
                size = path.stat().st_size
                size_str = f"{size:,} bytes"

                if age.total_seconds() < 3600:  # Modified in last hour
                    self.log_success(f"{description}: {log_path} (modified {age_str})")
                else:
                    self.log_warning(f"{description}: {log_path} (modified {age_str} - may be stale)")

                # Check if writable
                if os.access(log_path, os.W_OK):
                    self.log_success(f"{description} is writable")
                else:
                    self.log_warning(f"{description} is not writable")
            else:
                self.log_warning(f"{description}: {log_path} does not exist")

    def generate_report(self):
        """Generate final audit report"""
        print(f"\n{Style.BRIGHT}{'='*80}")
        print(f"{Fore.CYAN}{Style.BRIGHT}AUDIT SUMMARY")
        print(f"{Style.BRIGHT}{'='*80}\n")

        print(f"{Fore.GREEN}✅ Successes: {len(self.successes)}")
        print(f"{Fore.YELLOW}⚠️  Warnings:  {len(self.warnings)}")
        print(f"{Fore.RED}❌ Issues:    {len(self.issues)}\n")

        if self.issues:
            print(f"{Fore.RED}{Style.BRIGHT}CRITICAL ISSUES:")
            for issue in self.issues:
                print(f"  • {issue}")
            print()

        if self.warnings:
            print(f"{Fore.YELLOW}{Style.BRIGHT}WARNINGS:")
            for warning in self.warnings:
                print(f"  • {warning}")
            print()

        # Overall status
        if len(self.issues) == 0:
            if len(self.warnings) == 0:
                print(f"{Fore.GREEN}{Style.BRIGHT}✅ SYSTEM CONFIGURATION: EXCELLENT")
            else:
                print(f"{Fore.YELLOW}{Style.BRIGHT}⚠️  SYSTEM CONFIGURATION: GOOD (with warnings)")
        else:
            print(f"{Fore.RED}{Style.BRIGHT}❌ SYSTEM CONFIGURATION: ISSUES FOUND")

        print()


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Audit trading system configuration')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show all success messages')
    args = parser.parse_args()

    print(f"\n{Fore.CYAN}{Style.BRIGHT}TRADING SYSTEM CONFIGURATION AUDIT")
    print(f"{Style.DIM}Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    auditor = ConfigAuditor(verbose=args.verbose)

    auditor.check_env_files()
    auditor.check_services()
    auditor.check_parser_capabilities()
    auditor.check_database()
    auditor.check_log_files()

    auditor.generate_report()


if __name__ == "__main__":
    main()
