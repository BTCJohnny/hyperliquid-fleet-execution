"""
Unit tests for AlphaCryptoSignal reconciliation system

Usage:
    python test/test_reconcile_alpha.py
"""

import sys
import os
from datetime import datetime

# Add test directory to path for imports
test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, test_dir)

from reconcile_alpha_signals import (
    DatabaseCollector,
    HyperliquidCollector,
    FleetLogParser,
    SignalReconciler
)


def test_database_collector():
    """Test database query functionality"""
    print("\n🧪 Test 1: Database Collector")

    collector = DatabaseCollector()
    signals = collector.get_all_signals()

    print(f"   ├─ Retrieved {len(signals)} signals")
    assert isinstance(signals, list), "Should return a list"

    if signals:
        # Verify known POL signal exists
        pol_signals = [s for s in signals if s['symbol'] == 'POL']
        if pol_signals:
            pol = pol_signals[0]
            print(f"   ├─ Found POL signal (ID: {pol['id']})")
            assert pol['status'] == 'filled', f"POL should be filled, got {pol['status']}"
            assert pol['entry_1'] == 0.169, f"POL entry should be 0.169, got {pol['entry_1']}"
            assert pol['bot_name'] == 'AlphaCryptoSignal', "Should be AlphaCryptoSignal bot"

        # Test entry/exit filters
        entries = collector.get_entry_signals()
        exits = collector.get_exit_signals()
        print(f"   ├─ Entry signals: {len(entries)}")
        print(f"   └─ Exit signals: {len(exits)}")
        assert len(entries) + len(exits) == len(signals), "Entry + Exit should equal total"

    print("   ✅ Database Collector test passed")
    return True


def test_hyperliquid_collector():
    """Test Hyperliquid API query functionality"""
    print("\n🧪 Test 2: Hyperliquid Collector")

    try:
        collector = HyperliquidCollector()
        print(f"   ├─ Connected to API (wallet: {collector.address[:8]}...)")

        positions = collector.get_positions()
        print(f"   ├─ Retrieved {len(positions)} positions")
        assert isinstance(positions, list), "Should return a list"

        if positions:
            for pos in positions:
                assert 'ticker' in pos, "Position should have ticker"
                assert 'side' in pos, "Position should have side"
                assert 'size' in pos, "Position should have size"
                assert 'entry_px' in pos, "Position should have entry_px"
                print(f"   ├─ {pos['ticker']}: {pos['side']} {pos['size']:.4f} @ ${pos['entry_px']:.4f}")

        fills = collector.get_fills(hours=24)
        print(f"   └─ Retrieved {len(fills)} fills (24h)")

        print("   ✅ Hyperliquid Collector test passed")
        return True
    except Exception as e:
        print(f"   ⚠️  Hyperliquid test skipped: {e}")
        return False


def test_fleet_log_parser():
    """Test fleet log parsing"""
    print("\n🧪 Test 3: Fleet Log Parser")

    parser = FleetLogParser()
    executions = parser.parse_execution_logs()

    print(f"   ├─ Parsed {len(executions)} execution entries")
    assert isinstance(executions, list), "Should return a list"

    if executions:
        # Check for known POL execution (Signal 7)
        pol_exec = next((e for e in executions if e['signal_id'] == 7), None)
        if pol_exec:
            print(f"   ├─ Found POL execution (Signal 7): {pol_exec['status']}")
            assert pol_exec['status'] == 'success', "POL execution should be success"

    # Test correlation function
    if executions and any(e['signal_id'] for e in executions):
        test_id = next(e['signal_id'] for e in executions if e['signal_id'])
        correlated = parser.correlate_signal_to_log(test_id)
        print(f"   ├─ Correlation test: Signal {test_id} → {correlated['status'] if correlated else 'Not found'}")

    print("   ✅ Fleet Log Parser test passed")
    return True


def test_reconciler_logic():
    """Test reconciliation logic with mock data"""
    print("\n🧪 Test 4: Reconciler Logic")

    # Mock data
    mock_signals = [
        {
            'id': 1,
            'symbol': 'BTC',
            'signal_type': 'entry',
            'status': 'pending',
            'direction': 'LONG',
            'entry_1': 45000.0,
            'created_at': '2026-01-10 10:00:00'
        },
        {
            'id': 2,
            'symbol': 'ETH',
            'signal_type': 'entry',
            'status': 'filled',
            'direction': 'LONG',
            'entry_1': 2500.0,
            'position_size_actual': 2.5,
            'created_at': '2026-01-10 11:00:00'
        },
        {
            'id': 3,
            'symbol': 'SOL',
            'signal_type': 'entry',
            'status': 'failed',
            'direction': 'SHORT',
            'entry_1': 100.0,
            'created_at': '2026-01-10 12:00:00'
        }
    ]

    mock_positions = [
        {
            'ticker': 'ETH',
            'side': 'LONG',
            'size': 2.5,
            'entry_px': 2500.0,
            'mark_px': 2550.0,
            'pnl': 125.0
        },
        {
            'ticker': 'DOGE',  # Orphan position
            'side': 'LONG',
            'size': 1000.0,
            'entry_px': 0.10,
            'mark_px': 0.11,
            'pnl': 100.0
        }
    ]

    mock_fills = []
    mock_logs = []

    reconciler = SignalReconciler(mock_signals, mock_positions, mock_fills, mock_logs)

    # Test 1: Find unexecuted
    unexecuted = reconciler.find_unexecuted()
    print(f"   ├─ Unexecuted signals: {len(unexecuted)}")
    assert len(unexecuted) == 2, f"Should find 2 unexecuted (BTC pending, SOL failed), got {len(unexecuted)}"
    assert any(s['symbol'] == 'BTC' for s in unexecuted), "Should include BTC (pending)"
    assert any(s['symbol'] == 'SOL' for s in unexecuted), "Should include SOL (failed)"

    # Test 2: Find orphan positions
    orphans = reconciler.find_orphan_positions()
    print(f"   ├─ Orphan positions: {len(orphans)}")
    assert len(orphans) == 1, f"Should find 1 orphan (DOGE), got {len(orphans)}"
    assert orphans[0]['ticker'] == 'DOGE', "Orphan should be DOGE"

    # Test 3: Match signal to position
    eth_signal = mock_signals[1]
    matched_pos = reconciler.match_signal_to_position(eth_signal)
    print(f"   ├─ ETH signal matched: {matched_pos['ticker'] if matched_pos else 'None'}")
    assert matched_pos is not None, "Should match ETH signal to position"
    assert matched_pos['ticker'] == 'ETH', "Should match to ETH position"

    print("   ✅ Reconciler Logic test passed")
    return True


def test_full_reconciliation():
    """Test end-to-end reconciliation with real data"""
    print("\n🧪 Test 5: Full Reconciliation")

    try:
        # Collect real data
        db_collector = DatabaseCollector()
        db_signals = db_collector.get_all_signals()
        print(f"   ├─ Database: {len(db_signals)} signals")

        hl_collector = HyperliquidCollector()
        hl_positions = hl_collector.get_positions()
        hl_fills = hl_collector.get_fills(hours=24)
        print(f"   ├─ Hyperliquid: {len(hl_positions)} positions, {len(hl_fills)} fills")

        log_parser = FleetLogParser()
        log_executions = log_parser.parse_execution_logs()
        print(f"   ├─ Fleet logs: {len(log_executions)} executions")

        # Run reconciliation
        reconciler = SignalReconciler(db_signals, hl_positions, hl_fills, log_executions)

        # Basic validation
        unexecuted = reconciler.find_unexecuted()
        orphans = reconciler.find_orphan_positions()
        mismatches = reconciler.find_parameter_mismatches()

        print(f"   ├─ Analysis complete:")
        print(f"   │  ├─ Unexecuted: {len(unexecuted)}")
        print(f"   │  ├─ Orphans: {len(orphans)}")
        print(f"   │  └─ Mismatches: {len(mismatches)}")

        # Verify POL signal is matched (if it exists in DB)
        pol_signals = [s for s in db_signals if s['symbol'] == 'POL']
        if pol_signals:
            pol = pol_signals[0]
            if pol['status'] == 'filled':
                # Should either have a position or be an exit
                pos = reconciler.match_signal_to_position(pol)
                log = reconciler.match_signal_to_log(pol)
                print(f"   ├─ POL signal verification:")
                print(f"   │  ├─ Position match: {'Yes' if pos else 'No'}")
                print(f"   │  └─ Log match: {'Yes' if log else 'No'}")

        print("   ✅ Full Reconciliation test passed")
        return True
    except Exception as e:
        print(f"   ⚠️  Full reconciliation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all tests"""
    print("="*80)
    print("🧪 Running AlphaCryptoSignal Reconciliation Tests")
    print("="*80)

    results = []

    # Run tests
    results.append(("Database Collector", test_database_collector()))
    results.append(("Hyperliquid Collector", test_hyperliquid_collector()))
    results.append(("Fleet Log Parser", test_fleet_log_parser()))
    results.append(("Reconciler Logic", test_reconciler_logic()))
    results.append(("Full Reconciliation", test_full_reconciliation()))

    # Summary
    print("\n" + "="*80)
    print("📊 Test Summary")
    print("="*80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"   {status}: {name}")

    print(f"\n   Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n   🎉 All tests passed!")
        return True
    else:
        print(f"\n   ⚠️  {total - passed} test(s) failed")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
