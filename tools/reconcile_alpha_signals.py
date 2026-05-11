"""
Signal Reconciliation Tool for AlphaCryptoSignal Bot

Compares telegram parser logs, database signals, and Hyperliquid positions
to identify and troubleshoot mismatches in the trading pipeline.

Usage:
    python test/reconcile_alpha_signals.py
"""

import sqlite3
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.utils import constants
from colorama import Fore, Style, init

# Initialize colorama for colored terminal output
init(autoreset=True)

# Load environment variables
load_dotenv()

# Configuration
DB_PATH = "/Users/johnny_main/Developer/data/signals/signals.db"
FLEET_LOG_PATH = "/Users/johnny_main/Developer/data/logs/fleet_launchd.err"
PARSER_LOG_PATH = "/Users/johnny_main/Developer/data/logs/telegram_signals_sqlite.log"
BOT_NAME = "AlphaCryptoSignal"


class DatabaseCollector:
    """Query all AlphaCryptoSignal signals from signals.db"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def get_all_signals(self) -> List[Dict]:
        """Retrieve all signals for AlphaCryptoSignal bot"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM signals
                WHERE bot_name = ?
                ORDER BY created_at DESC
            """, (BOT_NAME,))

            signals = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return signals
        except Exception as e:
            print(f"{Fore.RED}❌ Database Error: {e}")
            return []

    def get_entry_signals(self) -> List[Dict]:
        """Filter for entry signals only"""
        return [s for s in self.get_all_signals() if s['signal_type'] == 'entry']

    def get_exit_signals(self) -> List[Dict]:
        """Filter for exit signals only"""
        return [s for s in self.get_all_signals() if s['signal_type'] == 'exit']


class HyperliquidCollector:
    """Query Hyperliquid API for positions and fills"""

    def __init__(self):
        private_key = os.getenv("PRIVATE_KEY_ALPHA")
        if not private_key:
            raise ValueError("PRIVATE_KEY_ALPHA not found in .env")

        self.account = Account.from_key(private_key)
        self.address = self.account.address

        is_mainnet = os.getenv("IS_MAINNET") == "True"
        base_url = constants.MAINNET_API_URL if is_mainnet else constants.TESTNET_API_URL
        self.info = Info(base_url, skip_ws=True)

    def get_positions(self) -> List[Dict]:
        """Get current open positions"""
        try:
            state = self.info.user_state(self.address)
            positions = state.get("assetPositions", [])

            # Filter for active positions only
            active = []
            all_mids = self.info.all_mids()

            for p in positions:
                pos = p["position"]
                size = float(pos["szi"])

                if size != 0:
                    ticker = pos["coin"]
                    entry_px = float(pos["entryPx"])
                    mark_px = float(all_mids.get(ticker, 0))

                    # Calculate PnL
                    if size > 0:
                        pnl = (mark_px - entry_px) * size
                        side = "LONG"
                    else:
                        pnl = (entry_px - mark_px) * abs(size)
                        side = "SHORT"

                    active.append({
                        'ticker': ticker,
                        'side': side,
                        'size': abs(size),
                        'entry_px': entry_px,
                        'mark_px': mark_px,
                        'pnl': pnl
                    })

            return active
        except Exception as e:
            print(f"{Fore.YELLOW}⚠️  Hyperliquid API Error: {e}")
            return []

    def get_fills(self, hours: int = 24) -> List[Dict]:
        """Get recent fills (if available from API)"""
        try:
            # Note: user_fills may not be available in all API versions
            # This is a best-effort attempt
            fills = self.info.user_fills(self.address)
            if not fills:
                return []

            cutoff = datetime.now() - timedelta(hours=hours)
            recent_fills = []

            for fill in fills:
                # Parse fill timestamp (format may vary)
                try:
                    fill_time = datetime.fromtimestamp(fill['time'] / 1000)
                    if fill_time >= cutoff:
                        recent_fills.append({
                            'ticker': fill['coin'],
                            'side': 'LONG' if float(fill['sz']) > 0 else 'SHORT',
                            'size': abs(float(fill['sz'])),
                            'price': float(fill['px']),
                            'timestamp': fill_time
                        })
                except:
                    continue

            return recent_fills
        except:
            # user_fills not available or error occurred
            return []


class FleetLogParser:
    """Parse fleet_launchd.err for execution details"""

    def __init__(self, log_path: str = FLEET_LOG_PATH):
        self.log_path = log_path

    def parse_execution_logs(self) -> List[Dict]:
        """Extract execution details for AlphaCryptoSignal"""
        if not os.path.exists(self.log_path):
            return []

        executions = []

        try:
            with open(self.log_path, 'r') as f:
                lines = f.readlines()

            for line in lines:
                if BOT_NAME not in line:
                    continue

                # Parse success messages: "✅ Signal 7 SUCCESS. Orders Placed."
                success_match = re.search(r'Signal (\d+) SUCCESS', line)
                if success_match:
                    signal_id = int(success_match.group(1))
                    timestamp = self._extract_timestamp(line)
                    executions.append({
                        'signal_id': signal_id,
                        'status': 'success',
                        'timestamp': timestamp,
                        'log_line': line.strip()
                    })

                # Parse failure messages: "❌ Execution Failed: ..."
                elif '❌ Execution Failed' in line or '❌ Signal' in line:
                    timestamp = self._extract_timestamp(line)
                    # Try to extract signal context from nearby lines
                    executions.append({
                        'signal_id': None,
                        'status': 'failed',
                        'timestamp': timestamp,
                        'log_line': line.strip()
                    })

            return executions
        except Exception as e:
            print(f"{Fore.YELLOW}⚠️  Log Parse Error: {e}")
            return []

    def correlate_signal_to_log(self, signal_id: int) -> Optional[Dict]:
        """Find log entries for a specific signal ID"""
        executions = self.parse_execution_logs()
        return next((e for e in executions if e['signal_id'] == signal_id), None)

    def _extract_timestamp(self, log_line: str) -> Optional[datetime]:
        """Extract timestamp from log line"""
        # Format: "2026-01-10 08:27:29,018 - ..."
        match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', log_line)
        if match:
            return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
        return None


class SignalReconciler:
    """Compare data sources and identify mismatches"""

    def __init__(self, db_signals: List[Dict], hl_positions: List[Dict],
                 hl_fills: List[Dict], log_executions: List[Dict]):
        self.db_signals = db_signals
        self.hl_positions = hl_positions
        self.hl_fills = hl_fills
        self.log_executions = log_executions

    def find_unexecuted(self) -> List[Dict]:
        """Type 2: Signals in DB but not executed (status='pending' or 'failed')"""
        return [s for s in self.db_signals if s['status'] in ['pending', 'failed']]

    def find_parameter_mismatches(self) -> List[Dict]:
        """Type 3: Executed with wrong size/price"""
        mismatches = []

        for signal in self.db_signals:
            if signal['status'] != 'filled':
                continue

            # Compare database position_size_actual with expected
            # Note: Expected size calculation would require equity data
            # For now, we'll flag if position_size_actual differs significantly from fills

            # Try to find matching fill
            signal_time = datetime.fromisoformat(signal['created_at'])
            matching_fills = [
                f for f in self.hl_fills
                if f['ticker'] == signal['symbol']
                and abs((f['timestamp'] - signal_time).total_seconds()) < 300  # ±5 min
            ]

            for fill in matching_fills:
                # Check price difference
                entry_price = float(signal['entry_1']) if signal['entry_1'] else 0
                if entry_price > 0:
                    price_diff_pct = abs(fill['price'] - entry_price) / entry_price
                    if price_diff_pct > 0.05:  # >5% difference
                        mismatches.append({
                            'signal': signal,
                            'fill': fill,
                            'issue': f'Price mismatch: signal={entry_price:.4f}, fill={fill["price"]:.4f} ({price_diff_pct*100:.1f}% diff)'
                        })

        return mismatches

    def find_orphan_positions(self) -> List[Dict]:
        """Type 4: Positions with no matching signal in database"""
        db_entry_symbols = {s['symbol'] for s in self.db_signals if s['signal_type'] == 'entry'}
        orphans = []

        for pos in self.hl_positions:
            if pos['ticker'] not in db_entry_symbols:
                orphans.append(pos)

        return orphans

    def match_signal_to_position(self, signal: Dict) -> Optional[Dict]:
        """Find Hyperliquid position matching a database signal"""
        return next((p for p in self.hl_positions if p['ticker'] == signal['symbol']), None)

    def match_signal_to_log(self, signal: Dict) -> Optional[Dict]:
        """Find fleet log entry matching a database signal"""
        return next((e for e in self.log_executions if e['signal_id'] == signal['id']), None)


def generate_report(reconciler: SignalReconciler, db_signals: List[Dict],
                    hl_positions: List[Dict], hl_fills: List[Dict],
                    parser_log_exists: bool) -> str:
    """Generate formatted reconciliation report"""

    lines = []
    sep = "=" * 80

    # Header
    lines.append(sep)
    lines.append(f"{Style.BRIGHT}ALPHACRYPTOSIGNAL RECONCILIATION REPORT")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(sep)
    lines.append("")

    # Summary
    unexecuted = reconciler.find_unexecuted()
    param_mismatches = reconciler.find_parameter_mismatches()
    orphan_positions = reconciler.find_orphan_positions()

    matched_count = len([s for s in db_signals if s['status'] == 'filled'])
    total_issues = len(unexecuted) + len(param_mismatches) + len(orphan_positions)

    lines.append(f"{Fore.CYAN}{Style.BRIGHT}SUMMARY:")
    lines.append(f"{Fore.WHITE}✅ Database Signals:           {len(db_signals)}")
    lines.append(f"✅ Open Positions (Hyperliquid): {len(hl_positions)}")
    lines.append(f"✅ Recent Fills (24h):          {len(hl_fills)}")
    lines.append(f"{'⚠️' if not parser_log_exists else '✅'}  Parser Logs:                {'NOT AVAILABLE' if not parser_log_exists else 'AVAILABLE'}")
    lines.append("")
    lines.append(f"{Fore.CYAN}{Style.BRIGHT}SUCCESS METRICS:")
    lines.append(f"{Fore.GREEN}✅ Fully Matched Signals:       {matched_count} ({matched_count/len(db_signals)*100 if db_signals else 0:.1f}%)")
    if total_issues > 0:
        lines.append(f"{Fore.YELLOW}⚠️  Mismatches Detected:          {total_issues}")
    else:
        lines.append(f"{Fore.GREEN}✅ No Mismatches Detected")
    lines.append("")

    # Category 1: Parser Logs
    lines.append(sep)
    lines.append(f"{Fore.CYAN}{Style.BRIGHT}MISMATCH CATEGORY 1: TELEGRAM→DATABASE PIPELINE")
    lines.append(sep)

    if not parser_log_exists:
        lines.append(f"{Fore.YELLOW}Status: CANNOT VERIFY (Parser log file missing)")
        lines.append(f"Expected: {PARSER_LOG_PATH}")
        lines.append(f"Found: File does not exist")
        lines.append("")
        lines.append(f"{Fore.YELLOW}IMPACT: Cannot verify if telegram signals were received but not saved to DB")
        lines.append("")
        lines.append(f"{Fore.CYAN}RECOMMENDED ACTIONS:")
        lines.append("1. Check if telegram_signals_to_sqlite.py service is running:")
        lines.append("   launchctl list | grep telegram.signals")
        lines.append("")
        lines.append("2. Check service logs location:")
        lines.append("   launchctl print system/com.telegram.signals | grep StandardError")
        lines.append("")
        lines.append("3. Restart service to regenerate logs:")
        lines.append("   launchctl unload ~/Library/LaunchAgents/com.telegram.signals.plist")
        lines.append("   launchctl load ~/Library/LaunchAgents/com.telegram.signals.plist")
    else:
        lines.append(f"{Fore.GREEN}Status: Parser logs available for analysis")
        lines.append("(Parser log analysis not implemented in this version)")
    lines.append("")

    # Category 2: Unexecuted Signals
    lines.append(sep)
    lines.append(f"{Fore.CYAN}{Style.BRIGHT}MISMATCH CATEGORY 2: DATABASE→EXECUTION PIPELINE")
    lines.append(sep)
    lines.append("Description: Signals in database but not executed (status='pending' or 'failed')")
    lines.append("")

    if unexecuted:
        for signal in unexecuted:
            lines.append(f"{Fore.YELLOW}Signal ID {signal['id']}: {signal['symbol']} {signal['direction']} ({signal['status'].upper()})")
            lines.append(f"  Created:  {signal['created_at']}")
            lines.append(f"  Type:     {signal['signal_type']}")
            if signal['notes']:
                lines.append(f"  Notes:    {signal['notes']}")
            lines.append("")

        lines.append(f"{Fore.CYAN}RECOMMENDED ACTIONS:")
        lines.append("1. Check fleet_runner.py is running: ps aux | grep fleet_runner.py")
        lines.append("2. Verify bot_id in FLEET_CONFIG matches database bot_name")
        lines.append("3. Review failed signals for error details")
        lines.append("4. Check fleet logs: tail -50 /Users/johnny_main/Developer/data/logs/fleet_launchd.err")
    else:
        lines.append(f"{Fore.GREEN}✅ No unexecuted signals found")
    lines.append("")

    # Category 3: Parameter Mismatches
    lines.append(sep)
    lines.append(f"{Fore.CYAN}{Style.BRIGHT}MISMATCH CATEGORY 3: EXECUTION PARAMETER ACCURACY")
    lines.append(sep)
    lines.append("Description: Signal executed but size/price differs from expected")
    lines.append("")

    if param_mismatches:
        for mismatch in param_mismatches:
            signal = mismatch['signal']
            lines.append(f"{Fore.YELLOW}Signal ID {signal['id']}: {signal['symbol']}")
            lines.append(f"  Issue: {mismatch['issue']}")
            lines.append("")

        lines.append(f"{Fore.CYAN}RECOMMENDED ACTIONS:")
        lines.append("1. Review risk_per_trade setting (currently 2%)")
        lines.append("2. Check if max_leverage cap reduced size (currently 20x for Alpha)")
        lines.append("3. Verify precision rounding in hyperliquid_top_gun.py:round_px()")
        lines.append("4. Check for 'Using Safety Stop' warnings in fleet logs")
    else:
        lines.append(f"{Fore.GREEN}✅ No parameter mismatches found")
    lines.append("")

    # Category 4: Orphan Positions
    lines.append(sep)
    lines.append(f"{Fore.CYAN}{Style.BRIGHT}MISMATCH CATEGORY 4: ORPHAN POSITIONS")
    lines.append(sep)
    lines.append("Description: Hyperliquid positions with no corresponding database signal")
    lines.append("")

    if orphan_positions:
        for pos in orphan_positions:
            lines.append(f"{Fore.YELLOW}Position: {pos['ticker']} {pos['side']}")
            lines.append(f"  Size:   {pos['size']:.4f}")
            lines.append(f"  Entry:  ${pos['entry_px']:.4f}")
            lines.append(f"  Mark:   ${pos['mark_px']:.4f}")
            lines.append(f"  PnL:    ${pos['pnl']:+.2f}")
            lines.append("")

        lines.append(f"{Fore.CYAN}RECOMMENDED ACTIONS:")
        lines.append("1. Verify wallet address matches expected")
        lines.append("2. Check for manual trades executed directly on Hyperliquid")
        lines.append("3. Search fleet logs for ticker mentions")
        lines.append("4. If manual trade: close position or document in notes")
    else:
        lines.append(f"{Fore.GREEN}✅ No orphan positions found")
    lines.append("")

    # Detailed Signal Analysis
    lines.append(sep)
    lines.append(f"{Fore.CYAN}{Style.BRIGHT}DETAILED SIGNAL ANALYSIS")
    lines.append(sep)
    lines.append("")

    for signal in db_signals:
        # Check if fully matched
        position = reconciler.match_signal_to_position(signal)
        log_entry = reconciler.match_signal_to_log(signal)

        is_matched = (signal['status'] == 'filled' and
                     (position is not None or signal['signal_type'] == 'exit'))

        status_icon = f"{Fore.GREEN}✅ FULLY MATCHED" if is_matched else f"{Fore.YELLOW}⚠️  PARTIAL"

        lines.append(f"{Style.BRIGHT}Signal ID {signal['id']}: {signal['symbol']} {signal['direction']} {status_icon}")
        lines.append(f"├─ Database:     {signal['created_at']} | entry={signal['entry_1']} | status='{signal['status']}' | size={signal.get('position_size_actual', 'N/A')}")

        if log_entry:
            lines.append(f"├─ Fleet Log:    {log_entry['timestamp']} | {log_entry['status']}")
        else:
            lines.append(f"├─ Fleet Log:    {Fore.YELLOW}No matching log entry found")

        if position:
            lines.append(f"└─ Hyperliquid:  OPEN | Entry: ${position['entry_px']:.4f} | Size: {position['size']:.4f} | PnL: ${position['pnl']:+.2f}")
        elif signal['signal_type'] == 'exit' and signal['status'] == 'executed':
            lines.append(f"└─ Hyperliquid:  CLOSED (exit executed)")
        else:
            lines.append(f"└─ Hyperliquid:  {Fore.YELLOW}No matching position found")

        lines.append("")

    # Next Steps
    lines.append(sep)
    lines.append(f"{Fore.CYAN}{Style.BRIGHT}NEXT STEPS")
    lines.append(sep)

    if total_issues > 0 or not parser_log_exists:
        lines.append(f"{Fore.YELLOW}{Style.BRIGHT}IMMEDIATE:")
        if not parser_log_exists:
            lines.append("1. Enable parser logging to verify telegram→database pipeline")
        if unexecuted:
            lines.append(f"{'2' if not parser_log_exists else '1'}. Investigate {len(unexecuted)} unexecuted signals")
        if orphan_positions:
            lines.append(f"{'3' if not parser_log_exists else '2'}. Reconcile {len(orphan_positions)} orphan positions")
    else:
        lines.append(f"{Fore.GREEN}{Style.BRIGHT}✅ System is healthy - all signals matched correctly!")

    lines.append("")
    lines.append(f"{Style.BRIGHT}LONG-TERM:")
    lines.append("1. Enable parser logging for telegram_signals_to_sqlite.py service")
    lines.append("2. Implement automated daily reconciliation reports")
    lines.append("3. Add signal_id tracking from parser to database for easier correlation")
    lines.append("")

    return "\n".join(lines)


def main():
    """Main reconciliation function"""
    print(f"\n{Fore.CYAN}{Style.BRIGHT}Starting AlphaCryptoSignal Reconciliation...")
    print("")

    # Collect data from all sources
    print(f"{Fore.YELLOW}📊 Collecting data from sources...")

    # Database
    db_collector = DatabaseCollector()
    db_signals = db_collector.get_all_signals()
    print(f"   ✓ Database: {len(db_signals)} signals")

    # Hyperliquid
    try:
        hl_collector = HyperliquidCollector()
        hl_positions = hl_collector.get_positions()
        hl_fills = hl_collector.get_fills(hours=24)
        print(f"   ✓ Hyperliquid: {len(hl_positions)} positions, {len(hl_fills)} fills")
    except Exception as e:
        print(f"{Fore.RED}   ✗ Hyperliquid: Error - {e}")
        hl_positions = []
        hl_fills = []

    # Fleet logs
    log_parser = FleetLogParser()
    log_executions = log_parser.parse_execution_logs()
    print(f"   ✓ Fleet logs: {len(log_executions)} execution entries")

    # Parser logs
    parser_log_exists = os.path.exists(PARSER_LOG_PATH)
    print(f"   {'✓' if parser_log_exists else '⚠'} Parser logs: {'Found' if parser_log_exists else 'Not found'}")

    print("")
    print(f"{Fore.YELLOW}🔍 Analyzing data...")

    # Reconcile
    reconciler = SignalReconciler(db_signals, hl_positions, hl_fills, log_executions)

    # Generate report
    report = generate_report(reconciler, db_signals, hl_positions, hl_fills, parser_log_exists)

    print("")
    print(report)


if __name__ == "__main__":
    main()
