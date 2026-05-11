"""
Unit tests for manual_trade.py

Tests validation logic, position sizing, leverage capping, and precision rounding
without requiring actual API access or database writes.
"""

import sys
import os
import math
import unittest

# Add parent directory to path to import manual_trade functions
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import functions from manual_trade
# Note: We need to import these as modules since manual_trade is a script
import importlib.util
spec = importlib.util.spec_from_file_location(
    "manual_trade",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "manual_trade.py")
)
manual_trade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manual_trade)


class TestTickerValidation(unittest.TestCase):
    """Test ticker validation logic."""

    def setUp(self):
        """Set up test metadata."""
        # Mock metadata with some common tickers
        manual_trade.sz_decimals_map = {
            "ETH": 4,
            "BTC": 5,
            "SOL": 3,
            "NEO": 2,
        }

    def test_valid_ticker(self):
        """Test validation of valid tickers."""
        self.assertTrue(manual_trade.validate_ticker("ETH", None))
        self.assertTrue(manual_trade.validate_ticker("BTC", None))
        self.assertTrue(manual_trade.validate_ticker("SOL", None))

    def test_valid_ticker_with_suffix(self):
        """Test validation handles USDT and PERP suffixes."""
        self.assertTrue(manual_trade.validate_ticker("ETHUSDT", None))
        self.assertTrue(manual_trade.validate_ticker("BTCPERP", None))

    def test_invalid_ticker(self):
        """Test validation rejects invalid tickers."""
        self.assertFalse(manual_trade.validate_ticker("FAKECOIN", None))
        self.assertFalse(manual_trade.validate_ticker("XYZ", None))

    def test_case_insensitive(self):
        """Test validation is case-insensitive."""
        self.assertTrue(manual_trade.validate_ticker("eth", None))
        self.assertTrue(manual_trade.validate_ticker("Eth", None))


class TestStopLossValidation(unittest.TestCase):
    """Test stop loss validation logic."""

    def test_long_valid_sl(self):
        """Test valid stop loss for long position (SL < entry)."""
        valid, error = manual_trade.validate_stop_loss(entry=100, sl=95, direction="long")
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_long_invalid_sl_above(self):
        """Test invalid stop loss for long (SL > entry)."""
        valid, error = manual_trade.validate_stop_loss(entry=100, sl=105, direction="long")
        self.assertFalse(valid)
        self.assertIn("BELOW", error)

    def test_long_invalid_sl_equal(self):
        """Test invalid stop loss equal to entry."""
        valid, error = manual_trade.validate_stop_loss(entry=100, sl=100, direction="long")
        self.assertFalse(valid)
        self.assertIn("cannot be the same", error)

    def test_short_valid_sl(self):
        """Test valid stop loss for short position (SL > entry)."""
        valid, error = manual_trade.validate_stop_loss(entry=100, sl=105, direction="short")
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_short_invalid_sl_below(self):
        """Test invalid stop loss for short (SL < entry)."""
        valid, error = manual_trade.validate_stop_loss(entry=100, sl=95, direction="short")
        self.assertFalse(valid)
        self.assertIn("ABOVE", error)

    def test_bullish_behaves_like_long(self):
        """Test 'bullish' direction behaves like 'long'."""
        valid, error = manual_trade.validate_stop_loss(entry=100, sl=95, direction="bullish")
        self.assertTrue(valid)

    def test_bearish_behaves_like_short(self):
        """Test 'bearish' direction behaves like 'short'."""
        valid, error = manual_trade.validate_stop_loss(entry=100, sl=105, direction="bearish")
        self.assertTrue(valid)


class TestTargetValidation(unittest.TestCase):
    """Test take profit target validation logic."""

    def test_long_valid_targets(self):
        """Test valid targets for long position (TPs > entry)."""
        valid, error = manual_trade.validate_targets(
            entry=100,
            targets=[105, 110, 115],
            direction="long"
        )
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_long_invalid_target_below(self):
        """Test invalid target for long (TP < entry)."""
        valid, error = manual_trade.validate_targets(
            entry=100,
            targets=[95],
            direction="long"
        )
        self.assertFalse(valid)
        self.assertIn("ABOVE", error)

    def test_short_valid_targets(self):
        """Test valid targets for short position (TPs < entry)."""
        valid, error = manual_trade.validate_targets(
            entry=100,
            targets=[95, 90, 85],
            direction="short"
        )
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_short_invalid_target_above(self):
        """Test invalid target for short (TP > entry)."""
        valid, error = manual_trade.validate_targets(
            entry=100,
            targets=[105],
            direction="short"
        )
        self.assertFalse(valid)
        self.assertIn("BELOW", error)

    def test_none_targets_ignored(self):
        """Test that None targets are skipped in validation."""
        valid, error = manual_trade.validate_targets(
            entry=100,
            targets=[None, 110, None, 120, None],
            direction="long"
        )
        self.assertTrue(valid)
        self.assertIsNone(error)


class TestPositionSizeCalculation(unittest.TestCase):
    """Test position size calculation logic."""

    def test_basic_position_sizing(self):
        """Test basic position size formula: size = (equity × risk%) / |entry - sl|."""
        equity = 1000
        risk_pct = 0.01  # 1%
        entry = 100
        sl = 95

        size, risk_amt = manual_trade.calculate_position_size(equity, risk_pct, entry, sl)

        # Expected: risk_amt = 1000 × 0.01 = 10
        # Expected: size = 10 / |100 - 95| = 10 / 5 = 2
        self.assertEqual(risk_amt, 10)
        self.assertEqual(size, 2)

    def test_position_sizing_short(self):
        """Test position sizing for short (SL above entry)."""
        equity = 1000
        risk_pct = 0.02  # 2%
        entry = 100
        sl = 110

        size, risk_amt = manual_trade.calculate_position_size(equity, risk_pct, entry, sl)

        # Expected: risk_amt = 1000 × 0.02 = 20
        # Expected: size = 20 / |100 - 110| = 20 / 10 = 2
        self.assertEqual(risk_amt, 20)
        self.assertEqual(size, 2)

    def test_higher_risk_increases_size(self):
        """Test that higher risk % increases position size."""
        equity = 1000
        entry = 100
        sl = 95

        size_1pct, _ = manual_trade.calculate_position_size(equity, 0.01, entry, sl)
        size_2pct, _ = manual_trade.calculate_position_size(equity, 0.02, entry, sl)

        self.assertGreater(size_2pct, size_1pct)

    def test_zero_price_diff_raises_error(self):
        """Test that entry == sl raises ValueError."""
        with self.assertRaises(ValueError):
            manual_trade.calculate_position_size(
                equity=1000,
                risk_pct=0.01,
                entry=100,
                sl=100  # Same as entry
            )


class TestLeverageCap(unittest.TestCase):
    """Test leverage capping logic."""

    def test_no_cap_needed(self):
        """Test when leverage is within limit (no cap)."""
        size = 2
        entry = 100
        equity = 1000
        max_leverage = 5.0

        size_final, capped, size_original = manual_trade.apply_leverage_cap(
            size, entry, equity, max_leverage
        )

        # Notional = 2 × 100 = 200
        # Leverage = 200 / 1000 = 0.2x (under 5x limit)
        self.assertFalse(capped)
        self.assertEqual(size_final, 2)
        self.assertEqual(size_original, 2)

    def test_cap_applied(self):
        """Test when leverage exceeds limit (cap applied)."""
        size = 60  # Would be 6x leverage
        entry = 100
        equity = 1000
        max_leverage = 5.0

        size_final, capped, size_original = manual_trade.apply_leverage_cap(
            size, entry, equity, max_leverage
        )

        # Original: notional = 60 × 100 = 6000, leverage = 6x (exceeds limit)
        # Capped: max_notional = 1000 × 5 = 5000, size = 5000 / 100 = 50
        self.assertTrue(capped)
        self.assertEqual(size_final, 50)
        self.assertEqual(size_original, 60)

    def test_exactly_at_limit(self):
        """Test when leverage is exactly at limit."""
        size = 50
        entry = 100
        equity = 1000
        max_leverage = 5.0

        size_final, capped, _ = manual_trade.apply_leverage_cap(
            size, entry, equity, max_leverage
        )

        # Notional = 50 × 100 = 5000
        # Leverage = 5000 / 1000 = 5.0x (exactly at limit)
        self.assertFalse(capped)
        self.assertEqual(size_final, 50)


class TestPrecisionRounding(unittest.TestCase):
    """Test price precision rounding logic."""

    def setUp(self):
        """Set up metadata for rounding tests."""
        manual_trade.sz_decimals_map = {
            "ETH": 4,
            "BTC": 5,
            "NEO": 2,
        }

    def test_round_px_eth(self):
        """Test price rounding for ETH (4 size decimals)."""
        # ETH: sz_decimals = 4, max_decimals = 6 - 4 = 2
        # Price ~2000: magnitude = 3, sig_figs_decimals = 5 - 1 - 3 = 1
        # Stricter: min(1, 2) = 1 decimal

        rounded = manual_trade.round_px("ETH", 2345.6789)
        self.assertEqual(rounded, 2345.7)

    def test_round_px_btc(self):
        """Test price rounding for BTC (5 size decimals)."""
        # BTC: sz_decimals = 5, max_decimals = 6 - 5 = 1
        # Price ~45000: magnitude = 4, sig_figs_decimals = 5 - 1 - 4 = 0
        # Stricter: min(0, 1) = 0 decimals

        rounded = manual_trade.round_px("BTC", 45678.123)
        self.assertEqual(rounded, 45678)

    def test_round_px_neo(self):
        """Test price rounding for NEO (2 size decimals)."""
        # NEO: sz_decimals = 2, max_decimals = 6 - 2 = 4
        # Price ~12: magnitude = 1, sig_figs_decimals = 5 - 1 - 1 = 3
        # Stricter: min(3, 4) = 3 decimals

        rounded = manual_trade.round_px("NEO", 12.345678)
        self.assertEqual(rounded, 12.346)

    def test_round_px_zero(self):
        """Test rounding zero price."""
        rounded = manual_trade.round_px("ETH", 0)
        self.assertEqual(rounded, 0.0)

    def test_get_sz_decimals(self):
        """Test getting size decimals from metadata."""
        self.assertEqual(manual_trade.get_sz_decimals("ETH"), 4)
        self.assertEqual(manual_trade.get_sz_decimals("BTC"), 5)
        self.assertEqual(manual_trade.get_sz_decimals("NEO"), 2)

    def test_get_sz_decimals_unknown(self):
        """Test default size decimals for unknown ticker."""
        self.assertEqual(manual_trade.get_sz_decimals("UNKNOWN"), 3)


class TestDatabaseInsertionFormat(unittest.TestCase):
    """Test database signal format (without actual DB writes)."""

    def test_signal_data_structure(self):
        """Test that signal data has required fields."""
        signal_data = {
            'bot_name': 'Manual Trader',
            'symbol': 'ETH',
            'direction': 'long',
            'entry_1': 2100.0,
            'stop_loss': 2050.0,
            'target_1': 2200.0,
            'target_2': 2300.0,
            'target_3': None,
            'target_4': None,
            'target_5': None
        }

        # Verify required fields
        self.assertEqual(signal_data['bot_name'], 'Manual Trader')
        self.assertIn('symbol', signal_data)
        self.assertIn('direction', signal_data)
        self.assertIn('entry_1', signal_data)
        self.assertIn('stop_loss', signal_data)

        # Verify targets can be None
        self.assertIsNone(signal_data['target_3'])

    def test_ticker_cleaning(self):
        """Test that ticker is cleaned (no USDT/PERP suffix)."""
        ticker_with_suffix = "ETHUSDT"
        ticker_clean = ticker_with_suffix.upper().replace("USDT", "").replace("PERP", "")

        self.assertEqual(ticker_clean, "ETH")


class TestIntegration(unittest.TestCase):
    """Integration tests combining multiple functions."""

    def setUp(self):
        """Set up for integration tests."""
        manual_trade.sz_decimals_map = {
            "ETH": 4,
        }

    def test_full_trade_calculation(self):
        """Test full trade calculation flow."""
        # Input parameters
        equity = 1000
        risk_pct = 0.01  # 1%
        entry = 2100
        sl = 2050
        direction = "long"
        max_leverage = 5.0

        # Validate stop loss
        valid, error = manual_trade.validate_stop_loss(entry, sl, direction)
        self.assertTrue(valid)

        # Calculate position size
        size, risk_amt = manual_trade.calculate_position_size(equity, risk_pct, entry, sl)
        self.assertEqual(risk_amt, 10)  # 1000 × 0.01
        self.assertEqual(size, 0.2)  # 10 / (2100 - 2050)

        # Apply leverage cap
        size_final, capped, _ = manual_trade.apply_leverage_cap(size, entry, equity, max_leverage)
        self.assertFalse(capped)  # 0.2 × 2100 = 420, leverage = 0.42x (under 5x)

        # Round to precision
        sz_decimals = manual_trade.get_sz_decimals("ETH")
        size_rounded = round(size_final, sz_decimals)
        self.assertEqual(size_rounded, 0.2)

    def test_full_trade_with_leverage_cap(self):
        """Test full trade calculation with leverage cap applied."""
        equity = 1000
        risk_pct = 0.10  # 10% (high risk)
        entry = 2000
        sl = 1900
        max_leverage = 5.0

        # Calculate size
        size, risk_amt = manual_trade.calculate_position_size(equity, risk_pct, entry, sl)
        # risk_amt = 100, size = 100 / 100 = 1.0

        # Without cap: notional = 1.0 × 2000 = 2000, leverage = 2x (OK)
        size_final, capped, _ = manual_trade.apply_leverage_cap(size, entry, equity, max_leverage)
        self.assertFalse(capped)

        # Now test with higher risk that triggers cap
        risk_pct = 0.30  # 30% (very high)
        size, risk_amt = manual_trade.calculate_position_size(equity, risk_pct, entry, sl)
        # risk_amt = 300, size = 300 / 100 = 3.0
        # notional = 3.0 × 2000 = 6000, leverage = 6x (exceeds 5x)

        size_final, capped, _ = manual_trade.apply_leverage_cap(size, entry, equity, max_leverage)
        self.assertTrue(capped)
        # max_notional = 1000 × 5 = 5000, size = 5000 / 2000 = 2.5
        self.assertEqual(size_final, 2.5)


def run_tests():
    """Run all tests."""
    unittest.main(argv=[''], verbosity=2, exit=False)


if __name__ == "__main__":
    print("=" * 80)
    print("MANUAL TRADE UNIT TESTS")
    print("=" * 80)
    print()
    run_tests()
