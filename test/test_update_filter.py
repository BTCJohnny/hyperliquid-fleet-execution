"""
Test suite for update message filtering

Tests the is_update_message() function to ensure:
1. Update/announcement messages are correctly filtered
2. Legitimate trading signals are NOT filtered (no false positives)
"""
import sys
import os

# Add parent directory to path to import from telegram_forwarder
sys.path.insert(0, '/Users/johnny_main/Developer/projects/telegram_forwarder')

from telegram_signals_to_sqlite import SignalParser

def test_update_message_filter():
    """Test cases for is_update_message() function"""

    print("=" * 70)
    print("TESTING UPDATE MESSAGE FILTER")
    print("=" * 70)

    # Test Case 1: Update message with "Signal ID - [number]" format
    print("\n[Test 1] Signal ID dash format + date")
    update_msg_1 = """Signal ID - 12
January, 2026
$ZRO Update! Target achieved: 1st, 2nd, 3rd"""
    is_update, reason = SignalParser.is_update_message(update_msg_1)
    assert is_update, "Should detect 'Signal ID - number' + date format"
    print(f"✅ PASS: Filtered - {reason}")

    # Test Case 2: Update message with "achieved" keyword
    print("\n[Test 2] 'achieved' keyword")
    update_msg_2 = """🎯 $ACE/USDT
Target 3 achieved!
Great job team!"""
    is_update, reason = SignalParser.is_update_message(update_msg_2)
    assert is_update, "Should detect 'achieved' keyword"
    print(f"✅ PASS: Filtered - {reason}")

    # Test Case 3: Announcement message
    print("\n[Test 3] 'reminder' keyword")
    update_msg_3 = """📢 Reminder: Always use stop losses!"""
    is_update, reason = SignalParser.is_update_message(update_msg_3)
    assert is_update, "Should detect 'reminder' keyword"
    print(f"✅ PASS: Filtered - {reason}")

    # Test Case 4: Legitimate AlphaCrypto entry signal (should NOT filter)
    print("\n[Test 4] Legitimate AlphaCrypto entry signal")
    legit_signal_1 = """Signal ID: 5678
Pair: $ZRO/USDT
Direction: LONG
Entry:
1) 1.42
Take Profit:
1) 1.50
2) 1.55
Stop Limit: 1.29"""
    is_update, reason = SignalParser.is_update_message(legit_signal_1)
    assert not is_update, "Should NOT filter legitimate entry signal"
    print(f"✅ PASS: Not filtered (legitimate signal)")

    # Test Case 5: Legitimate AlphaCrypto exit signal (should NOT filter)
    print("\n[Test 5] Legitimate AlphaCrypto exit signal")
    legit_signal_2 = """Pair: $POL/USDT
Target 1 Hit @ 0.175
Entry: 0.169
PnL: +3.55%
Status: Take Profit Executed"""
    is_update, reason = SignalParser.is_update_message(legit_signal_2)
    assert not is_update, "Should NOT filter legitimate exit signal"
    print(f"✅ PASS: Not filtered (legitimate exit)")

    # Test Case 6: AITA signal (should NOT filter)
    print("\n[Test 6] AITA signal")
    aita_signal = """⚡️ Apprentice Alchemist
Direction: Bullish 🟢
🪙 NEO: Entry @ $3.95, Size: 3/5"""
    is_update, reason = SignalParser.is_update_message(aita_signal)
    assert not is_update, "Should NOT filter AITA signals"
    print(f"✅ PASS: Not filtered (AITA signal)")

    # Test Case 7: Edge case - "Signal ID - " with date but no update keyword
    print("\n[Test 7] Signal ID dash + date (edge case)")
    edge_case = """Signal ID - 999
December, 2025
Final results for the month"""
    is_update, reason = SignalParser.is_update_message(edge_case)
    assert is_update, "Should filter 'Signal ID - number' + date even without explicit update keyword"
    print(f"✅ PASS: Filtered - {reason}")

    # Test Case 8: "Signal ID:" (colon) format should NOT filter (legitimate format)
    print("\n[Test 8] Signal ID colon format (legitimate)")
    legit_colon = """Signal ID: 123
Pair: $BTC/USDT
Direction: SHORT"""
    is_update, reason = SignalParser.is_update_message(legit_colon)
    assert not is_update, "Should NOT filter 'Signal ID:' (colon) format"
    print(f"✅ PASS: Not filtered (legitimate Signal ID: format)")

    # Test Case 9: Legitimate exit with "achieved" in proper structure (should NOT filter)
    print("\n[Test 9] Legitimate exit with 'achieved' keyword but proper structure")
    legit_with_achieved = """Pair: $ACE/USDT
Target achieved
Hit @ 0.297
PnL: +4.14%"""
    is_update, reason = SignalParser.is_update_message(legit_with_achieved)
    assert not is_update, "Should NOT filter exits with proper structure even if 'achieved' present"
    print(f"✅ PASS: Not filtered (proper exit structure overrides keyword)")

    # Test Case 10: Update keyword "update!" (case variations)
    print("\n[Test 10] 'update!' keyword (case insensitive)")
    update_with_exclamation = """$ZRO Update! 🔈
✅ Target achieved: 1st, 2nd, 3rd.🔥"""
    is_update, reason = SignalParser.is_update_message(update_with_exclamation)
    assert is_update, "Should detect 'update!' keyword (case insensitive)"
    print(f"✅ PASS: Filtered - {reason}")

    # Test Case 11: AlphaCrypto entry with "Signal ID - [number]" + date BUT with "Provided By" (should NOT filter)
    print("\n[Test 11] AlphaCrypto entry with 'Signal ID -' + date + 'Provided By'")
    alpha_entry_with_date = """🚀 Alpha_Crypto Signal ID - 14
January, 2026
-------------------------------------
Market Type: Futures
Pair: $ZRO/USDT
Direction: LONG

Entry:
1) 1.42

Take Profit:
1) 1.50
2) 1.55

Stop Limit: 1.29
Leverage: 5x

Provided By,
- @AlphaCryptoSignal"""
    is_update, reason = SignalParser.is_update_message(alpha_entry_with_date)
    assert not is_update, "Should NOT filter AlphaCrypto entries with 'Provided By' even if date present"
    print(f"✅ PASS: Not filtered (proper AlphaCrypto entry structure)")

    print("\n" + "=" * 70)
    print("🎉 ALL TESTS PASSED!")
    print("=" * 70)
    print("\nSummary:")
    print("- Update messages:     Correctly filtered (5/5)")
    print("- Legitimate signals:  Not filtered (6/6)")
    print("- Total:              11/11 tests passed")
    print("\n✅ Filter is working as expected!\n")

if __name__ == "__main__":
    # Set test environment
    os.environ['UPDATE_FILTER_KEYWORDS'] = 'update!,achieved,confirmation,alert,reminder,announcement'

    try:
        test_update_message_filter()
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
