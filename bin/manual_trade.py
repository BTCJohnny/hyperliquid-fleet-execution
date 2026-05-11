"""
CONTEXT_FOR_LLM_INGESTION:
--------------------------------------------------------------------------------
SYSTEM ROLE:
Manual Trade Input Interface for Hyperliquid Fleet.

CAPABILITIES:
1. Interactive CLI for manual trade entry
2. Real-time position size calculation with risk management
3. Ticker validation against Hyperliquid metadata
4. Price validation (stop loss & take profit logic checks)
5. Database integration (inserts to signals table)
6. Fleet status checking (warns if Manual Trader not active)

USAGE:
python manual_trade.py

CONFIGURATION:
- Requires PRIVATE_KEY_MANUAL in .env
- Requires "Manual Trader" bot in fleet_runner.py FLEET_CONFIG
- Database: /Users/johnny_main/Developer/data/signals/signals.db

INTEGRATION:
- Signals inserted are identical to Telegram signals
- Full fleet monitoring (fill monitor, reconciliation, admin controls)
- Position sizing follows exact same formulas as HyperLiquidTopGun

SAFETY:
- Validates ticker exists in Hyperliquid metadata
- Validates stop loss is on correct side (long: SL < entry, short: SL > entry)
- Validates targets are on correct side (long: TP > entry, short: TP < entry)
- Applies leverage cap (reduces size if notional > equity × max_leverage)
- Preview mode (shows calculations before confirmation)
- Database-only writes (no direct order placement)
--------------------------------------------------------------------------------
"""

import os
import sys
import sqlite3
import math
from datetime import datetime
from dotenv import load_dotenv, find_dotenv
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.utils import constants

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False
    # Fallback if colorama not available
    class Fore:
        GREEN = RED = YELLOW = CYAN = MAGENTA = BLUE = WHITE = ""
    class Style:
        BRIGHT = RESET_ALL = ""

# --- Load Environment ---
load_dotenv(find_dotenv())

# --- Configuration ---
DB_PATH = "/Users/johnny_main/Developer/data/signals/signals.db"
IS_MAINNET = os.getenv("IS_MAINNET") == "True"
BOT_NAME = "Manual Trader"

# Load Manual Trader risk settings from fleet config
MANUAL_CONFIG = get_manual_trader_config()

DEFAULT_RISK_PCT = MANUAL_CONFIG['risk_per_trade']
MAX_LEVERAGE = MANUAL_CONFIG['max_leverage']
MAX_RISK_PCT = 0.10      # Still allow up to 10% override
MIN_RISK_PCT = 0.001     # Still enforce minimum 0.1%

# --- Global State ---
metadata_cache = None
sz_decimals_map = {}


# ============================================================================
# RISK CONFIGURATION FROM FLEET
# ============================================================================

def get_manual_trader_config():
    """
    Read Manual Trader risk settings from fleet_runner.py FLEET_CONFIG.
    Falls back to .env if not found.

    This ensures manual trade risk settings match the fleet configuration
    instead of using hardcoded defaults.
    """
    # Import fleet config
    try:
        # fleet_runner.py lives in the project root, one level above bin/
        import_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if import_path not in sys.path:
            sys.path.insert(0, import_path)

        from fleet_runner import FLEET_CONFIG

        # Find Manual Trader config
        for bot_config in FLEET_CONFIG:
            if bot_config.get("bot_id") == BOT_NAME:
                return {
                    'risk_per_trade': bot_config.get('risk_per_trade', 0.01),
                    'max_leverage': bot_config.get('max_leverage', 1.0),
                    'default_sl_dist': bot_config.get('default_sl_dist', 0.05),
                    'max_concurrent_positions': bot_config.get('max_concurrent_positions', 2)
                }
    except ImportError:
        print(f"{Fore.YELLOW}⚠️  Could not import fleet_runner. Using .env fallbacks.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.YELLOW}⚠️  Error reading fleet config: {e}. Using .env fallbacks.{Style.RESET_ALL}")

    # Fallback to .env
    return {
        'risk_per_trade': float(os.getenv('RISK_PER_TRADE', '0.01')),
        'max_leverage': float(os.getenv('MAX_LEVERAGE', '1.0')),
        'default_sl_dist': float(os.getenv('DEFAULT_SL_DIST', '0.05')),
        'max_concurrent_positions': int(os.getenv('MAX_CONCURRENT_POSITIONS', '2'))
    }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_metadata(info):
    """Load and cache Hyperliquid metadata."""
    global metadata_cache, sz_decimals_map

    if metadata_cache is None:
        try:
            metadata_cache = info.meta()
            sz_decimals_map = {
                asset['name']: asset['szDecimals']
                for asset in metadata_cache['universe']
            }
        except Exception as e:
            print(f"{Fore.RED}❌ Failed to load metadata: {e}{Style.RESET_ALL}")
            sys.exit(1)

    return metadata_cache


def validate_ticker(ticker, metadata):
    """Check if ticker exists in Hyperliquid metadata."""
    ticker_clean = ticker.upper().replace("USDT", "").replace("PERP", "")
    return ticker_clean in sz_decimals_map


def get_sz_decimals(ticker):
    """Get size decimals for a ticker from metadata."""
    ticker_clean = ticker.upper().replace("USDT", "").replace("PERP", "")
    return sz_decimals_map.get(ticker_clean, 3)


def get_current_price(info, ticker):
    """Get current mid price for a ticker."""
    try:
        ticker_clean = ticker.upper().replace("USDT", "").replace("PERP", "")
        mids = info.all_mids()

        # Find the ticker in mids
        for coin_name, price_str in mids.items():
            if coin_name == ticker_clean:
                return float(price_str)

        return None
    except:
        return None


def round_px(ticker, price):
    """
    Rounds price according to Hyperliquid's strict rules:
    1. Max 5 Significant Figures
    2. Max Decimals = 6 - szDecimals (for Perps)

    Matches hyperliquid_top_gun.py lines 72-99
    """
    if price == 0:
        return 0.0

    try:
        # Rule 1: Max 5 Significant Figures
        magnitude = math.floor(math.log10(abs(price)))
        sig_figs_decimals = 5 - 1 - magnitude

        # Rule 2: Max Decimals allowed by Hyperliquid Metadata
        sz_decimals = get_sz_decimals(ticker)
        max_decimals = 6 - sz_decimals

        # The stricter of the two rules wins
        final_decimals = min(sig_figs_decimals, max_decimals)

        # If allowed decimals < 0, round to nearest 10, 100, etc.
        if final_decimals < 0:
            return round(price, final_decimals)

        return round(price, final_decimals)

    except Exception:
        return price


def validate_stop_loss(entry, sl, direction):
    """
    Validate stop loss is on correct side.
    Long: SL must be < entry
    Short: SL must be > entry
    """
    if entry == sl:
        return False, "Entry and stop loss cannot be the same"

    if direction.lower() in ['long', 'bullish']:
        if sl >= entry:
            return False, "Stop loss must be BELOW entry for LONG"
    else:  # short or bearish
        if sl <= entry:
            return False, "Stop loss must be ABOVE entry for SHORT"

    return True, None


def validate_targets(entry, targets, direction):
    """
    Validate take profit targets are on correct side.
    Long: TPs must be > entry
    Short: TPs must be < entry
    """
    for i, tp in enumerate(targets, 1):
        if tp is None:
            continue

        if direction.lower() in ['long', 'bullish']:
            if tp <= entry:
                return False, f"Target {i} must be ABOVE entry for LONG"
        else:  # short or bearish
            if tp >= entry:
                return False, f"Target {i} must be BELOW entry for SHORT"

    return True, None


def calculate_position_size(equity, risk_pct, entry, sl):
    """
    Calculate position size based on risk.
    Matches hyperliquid_top_gun.py lines 276-282

    Formula: size = (equity × risk_pct) / |entry - sl|
    """
    risk_amt = equity * risk_pct
    price_diff = abs(entry - sl)

    if price_diff == 0:
        raise ValueError("Invalid stop loss (price diff is 0)")

    size = risk_amt / price_diff
    return size, risk_amt


def apply_leverage_cap(size, entry, equity, max_leverage):
    """
    Apply leverage cap if notional value exceeds limit.
    Matches hyperliquid_top_gun.py lines 285-287

    If (size × entry) > (equity × max_leverage), reduce size
    """
    notional_value = size * entry
    max_notional = equity * max_leverage

    if notional_value > max_notional:
        original_size = size
        size = max_notional / entry
        return size, True, original_size

    return size, False, size


def get_wallet_state(info, address):
    """Fetch wallet equity and open positions."""
    try:
        user_state = info.user_state(address)
        equity = float(user_state["marginSummary"]["accountValue"])

        open_positions = user_state.get("assetPositions", [])
        positions = []
        for p in open_positions:
            szi = float(p["position"]["szi"])
            if szi != 0:
                positions.append({
                    "coin": p["position"]["coin"],
                    "size": szi,
                    "entry": float(p["position"].get("entryPx", 0))
                })

        return {
            "equity": equity,
            "positions": positions,
            "position_count": len(positions)
        }
    except Exception as e:
        raise ValueError(f"Failed to fetch wallet state: {e}")


def check_fleet_status():
    """Check if Manual Trader bot is active (not paused)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT command
            FROM bot_controls
            WHERE bot_id = ?
            ORDER BY id DESC LIMIT 1
        """, (BOT_NAME,))
        row = c.fetchone()
        conn.close()

        if row and row[0] == 'PAUSE':
            return False
        return True
    except:
        return None  # Unknown status


def insert_signal_to_db(signal_data):
    """
    Insert signal to database.
    Matches test_db_integration.py lines 38-42
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("""
            INSERT INTO signals
            (bot_name, symbol, direction, entry_1, stop_loss,
             target_1, target_2, target_3, target_4, target_5,
             status, signal_type, provider, source, raw_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            signal_data['bot_name'],
            signal_data['symbol'],
            signal_data['direction'],
            signal_data['entry_1'],
            signal_data['stop_loss'],
            signal_data.get('target_1'),
            signal_data.get('target_2'),
            signal_data.get('target_3'),
            signal_data.get('target_4'),
            signal_data.get('target_5'),
            'pending',
            'entry',
            'Manual Input',
            'cli',
            'Manual trade via manual_trade.py'
        ))

        signal_id = c.lastrowid
        conn.commit()
        conn.close()

        return signal_id

    except Exception as e:
        raise ValueError(f"Database insertion failed: {e}")


# ============================================================================
# INTERACTIVE PROMPTS
# ============================================================================

def prompt_ticker(info):
    """Prompt for ticker with validation."""
    while True:
        ticker = input(f"\n{Fore.CYAN}Ticker (e.g., ETH, BTC, SOL): {Style.RESET_ALL}").strip()

        if not ticker:
            print(f"{Fore.RED}❌ Ticker cannot be empty{Style.RESET_ALL}")
            continue

        ticker_clean = ticker.upper().replace("USDT", "").replace("PERP", "")

        if not validate_ticker(ticker_clean, metadata_cache):
            print(f"{Fore.RED}❌ Ticker '{ticker_clean}' not found in Hyperliquid metadata{Style.RESET_ALL}")
            continue

        # Get current price
        current_price = get_current_price(info, ticker_clean)
        price_info = f" (Current: ${current_price:,.2f})" if current_price else ""

        print(f"{Fore.GREEN}✅ {ticker_clean} found{price_info}{Style.RESET_ALL}")
        return ticker_clean


def prompt_direction():
    """Prompt for direction (long/short)."""
    while True:
        direction = input(f"\n{Fore.CYAN}Direction (long/short): {Style.RESET_ALL}").strip().lower()

        if direction in ['long', 'l', 'bullish']:
            return 'long'
        elif direction in ['short', 's', 'bearish']:
            return 'short'
        else:
            print(f"{Fore.RED}❌ Invalid direction. Use 'long' or 'short'{Style.RESET_ALL}")


def prompt_entry():
    """Prompt for entry price."""
    while True:
        try:
            entry_str = input(f"\n{Fore.CYAN}Entry Price: {Style.RESET_ALL}").strip()
            entry = float(entry_str)

            if entry <= 0:
                print(f"{Fore.RED}❌ Entry price must be positive{Style.RESET_ALL}")
                continue

            return entry

        except ValueError:
            print(f"{Fore.RED}❌ Invalid number{Style.RESET_ALL}")


def prompt_stop_loss(entry, direction):
    """Prompt for stop loss with validation."""
    while True:
        try:
            sl_str = input(f"\n{Fore.CYAN}Stop Loss: {Style.RESET_ALL}").strip()
            sl = float(sl_str)

            if sl <= 0:
                print(f"{Fore.RED}❌ Stop loss must be positive{Style.RESET_ALL}")
                continue

            valid, error = validate_stop_loss(entry, sl, direction)
            if not valid:
                print(f"{Fore.RED}❌ {error}{Style.RESET_ALL}")
                continue

            # Calculate distance percentage
            dist_pct = abs(entry - sl) / entry * 100
            print(f"{Fore.GREEN}✅ Valid ({dist_pct:.2f}% {'below' if direction == 'long' else 'above'} entry){Style.RESET_ALL}")

            return sl

        except ValueError:
            print(f"{Fore.RED}❌ Invalid number{Style.RESET_ALL}")


def prompt_targets(entry, direction):
    """Prompt for up to 5 take profit targets."""
    targets = []

    for i in range(1, 6):
        while True:
            try:
                prompt_msg = f"\n{Fore.CYAN}Target {i} (or press Enter to skip): {Style.RESET_ALL}"
                tp_str = input(prompt_msg).strip()

                if not tp_str:
                    targets.append(None)
                    break

                tp = float(tp_str)

                if tp <= 0:
                    print(f"{Fore.RED}❌ Target must be positive{Style.RESET_ALL}")
                    continue

                valid, error = validate_targets(entry, [tp], direction)
                if not valid:
                    print(f"{Fore.RED}❌ {error}{Style.RESET_ALL}")
                    continue

                # Calculate gain percentage
                gain_pct = abs(tp - entry) / entry * 100
                print(f"{Fore.GREEN}✅ Valid ({gain_pct:+.2f}%){Style.RESET_ALL}")

                targets.append(tp)
                break

            except ValueError:
                print(f"{Fore.RED}❌ Invalid number{Style.RESET_ALL}")

    return targets


def prompt_risk_pct():
    """Prompt for risk percentage."""
    default_pct = DEFAULT_RISK_PCT * 100

    while True:
        try:
            prompt_msg = f"\n{Fore.CYAN}Risk % (default {default_pct}%): {Style.RESET_ALL}"
            risk_str = input(prompt_msg).strip()

            if not risk_str:
                return DEFAULT_RISK_PCT

            risk_pct = float(risk_str) / 100  # Convert % to decimal

            if risk_pct < MIN_RISK_PCT or risk_pct > MAX_RISK_PCT:
                print(f"{Fore.RED}❌ Risk % must be between {MIN_RISK_PCT*100}% and {MAX_RISK_PCT*100}%{Style.RESET_ALL}")
                continue

            return risk_pct

        except ValueError:
            print(f"{Fore.RED}❌ Invalid number{Style.RESET_ALL}")


def prompt_confirmation():
    """Prompt for final confirmation."""
    while True:
        confirm = input(f"\n{Fore.YELLOW}Proceed with this trade? (y/n): {Style.RESET_ALL}").strip().lower()

        if confirm in ['y', 'yes']:
            return True
        elif confirm in ['n', 'no']:
            return False
        else:
            print(f"{Fore.RED}❌ Invalid input. Use 'y' or 'n'{Style.RESET_ALL}")


# ============================================================================
# DISPLAY FUNCTIONS
# ============================================================================

def print_header():
    """Print application header."""
    env = "Mainnet" if IS_MAINNET else "Testnet"

    print("\n" + "=" * 80)
    print(f"{Fore.MAGENTA}🎯 MANUAL TRADE INPUT - Hyperliquid Fleet{Style.RESET_ALL}")
    print("=" * 80)
    print(f"\n{Fore.CYAN}📡 Connected to {env}{Style.RESET_ALL}")


def display_wallet_info(wallet_state, address):
    """Display wallet equity and positions."""
    print(f"{Fore.CYAN}🔑 Wallet: {address[:6]}...{address[-4:]}{Style.RESET_ALL}")

    print(f"\n{Fore.YELLOW}💰 WALLET STATUS{Style.RESET_ALL}")
    print("─" * 80)
    print(f"Equity: ${wallet_state['equity']:,.2f}")

    if wallet_state['positions']:
        positions_str = ", ".join([f"{p['coin']}" for p in wallet_state['positions']])
        print(f"Open Positions: {wallet_state['position_count']} ({positions_str})")
    else:
        print(f"Open Positions: 0")

    print(f"Available: {Fore.GREEN}Yes{Style.RESET_ALL}")


def display_fleet_warning():
    """Display warning if Manual Trader bot not active."""
    fleet_status = check_fleet_status()

    if fleet_status is False:
        print(f"\n{Fore.YELLOW}⚠️  Warning: Manual Trader bot is PAUSED{Style.RESET_ALL}")
        print(f"   Resume with: python admin_controls.py Manual RESUME")
    elif fleet_status is None:
        print(f"\n{Fore.YELLOW}⚠️  Warning: Could not check fleet status{Style.RESET_ALL}")
        print(f"   Ensure fleet is running: python fleet_runner.py")


def display_trade_preview(trade_data, calc_results):
    """Display comprehensive trade preview."""
    print("\n" + "=" * 80)
    print(f"{Fore.CYAN}📊 TRADE PREVIEW - {trade_data['symbol']} {trade_data['direction'].upper()}{Style.RESET_ALL}")
    print("=" * 80)

    print(f"Entry Price:       ${trade_data['entry']:,.2f}")

    sl_dist_pct = abs(trade_data['entry'] - trade_data['stop_loss']) / trade_data['entry'] * 100
    sl_side = 'below' if trade_data['direction'] == 'long' else 'above'
    print(f"Stop Loss:         ${trade_data['stop_loss']:,.2f} ({sl_dist_pct:.2f}% {sl_side} entry)")

    # Display targets
    for i, target in enumerate(trade_data['targets'], 1):
        if target:
            gain_pct = (target - trade_data['entry']) / trade_data['entry'] * 100
            print(f"Take Profit {i}:     ${target:,.2f} ({gain_pct:+.2f}%)")

    print(f"\n{Fore.YELLOW}💰 RISK MANAGEMENT{Style.RESET_ALL}")
    print("─" * 80)
    print(f"Wallet Equity:     ${calc_results['equity']:,.2f}")
    print(f"Risk Per Trade:    {calc_results['risk_pct']*100:.1f}%")
    print(f"Risk Amount:       ${calc_results['risk_amt']:,.2f}")

    print(f"\n{Fore.YELLOW}📐 POSITION SIZING{Style.RESET_ALL}")
    print("─" * 80)
    print(f"Position Size:     {calc_results['size_final']:.{get_sz_decimals(trade_data['symbol'])}} {trade_data['symbol']}")
    print(f"Notional Value:    ${calc_results['notional_value']:,.2f}")
    print(f"Calculated Leverage: {calc_results['leverage']:.2f}x")

    if calc_results['leverage_capped']:
        print(f"{Fore.YELLOW}⚠️  Leverage cap hit: size reduced from {calc_results['size_original']:.4f} to {calc_results['size_final']:.4f}{Style.RESET_ALL}")
        print(f"Status:            {Fore.YELLOW}⚠️  At leverage limit (Max: {MAX_LEVERAGE}x){Style.RESET_ALL}")
    else:
        print(f"Status:            {Fore.GREEN}✅ Within limit (Max: {MAX_LEVERAGE}x){Style.RESET_ALL}")

    print("=" * 80)


def display_success_message(signal_id):
    """Display success message after insertion."""
    print(f"\n{Fore.GREEN}✅ SUCCESS! Trade signal inserted.{Style.RESET_ALL}")
    print(f"\nSignal ID: {signal_id}")
    print(f"Bot: {BOT_NAME}")
    print(f"Status: pending")

    print(f"\n{Fore.CYAN}🤖 NEXT STEPS:{Style.RESET_ALL}")
    print("─" * 80)
    print(f"1. Fleet will pick up signal in ~2 seconds")
    print(f"2. Check status: python admin_controls.py Manual STATUS")
    print(f"3. View orders:  python admin_controls.py Manual ORDERS")
    print(f"4. Monitor logs: tail -f /Users/johnny_main/Developer/data/logs/fleet_activity.log")

    print(f"\n{Fore.CYAN}📊 Position will be tracked automatically:{Style.RESET_ALL}")
    print(f"   - Fill Monitor: Tracks TP/SL hits + breakeven logic")
    print(f"   - Reconciliation: Auto-heals ghost positions every 60s")
    print(f"   - Admin Controls: PAUSE/RESUME/CLOSE_ALL available")

    print("=" * 80 + "\n")


# ============================================================================
# MAIN FLOW
# ============================================================================

def main():
    """Main interactive flow."""

    # Check for private key
    private_key = os.getenv("PRIVATE_KEY_MANUAL")
    if not private_key:
        print(f"{Fore.RED}❌ PRIVATE_KEY_MANUAL not found in .env{Style.RESET_ALL}")
        print(f"\nGenerate a wallet with:")
        print(f"  python -c \"from eth_account import Account; acc=Account.create(); print(f'Address: {{acc.address}}\\nKey: {{acc._private_key.hex()}}')\"")
        print(f"\nThen add to .env:")
        print(f"  PRIVATE_KEY_MANUAL=0x...")
        sys.exit(1)

    # Initialize API connection
    try:
        account = Account.from_key(private_key)
        base_url = constants.MAINNET_API_URL if IS_MAINNET else constants.TESTNET_API_URL
        info = Info(base_url, skip_ws=True)
    except Exception as e:
        print(f"{Fore.RED}❌ Failed to connect to Hyperliquid API: {e}{Style.RESET_ALL}")
        sys.exit(1)

    # Load metadata
    print(f"{Fore.CYAN}Loading metadata...{Style.RESET_ALL}")
    get_metadata(info)
    print(f"{Fore.GREEN}✅ Loaded precision data for {len(sz_decimals_map)} assets{Style.RESET_ALL}")

    # Display header
    print_header()

    # Get wallet state
    try:
        wallet_state = get_wallet_state(info, account.address)
        display_wallet_info(wallet_state, account.address)
    except Exception as e:
        print(f"{Fore.RED}❌ {e}{Style.RESET_ALL}")
        sys.exit(1)

    # Check fleet status
    display_fleet_warning()

    # Collect trade inputs
    print(f"\n{Fore.YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}📝 ENTER TRADE DETAILS{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}")

    ticker = prompt_ticker(info)
    direction = prompt_direction()
    entry = prompt_entry()
    stop_loss = prompt_stop_loss(entry, direction)
    targets = prompt_targets(entry, direction)
    risk_pct = prompt_risk_pct()

    # Calculate position sizing
    try:
        size, risk_amt = calculate_position_size(wallet_state['equity'], risk_pct, entry, stop_loss)
        size_capped, leverage_capped, size_original = apply_leverage_cap(size, entry, wallet_state['equity'], MAX_LEVERAGE)

        # Apply precision rounding
        sz_decimals = get_sz_decimals(ticker)
        size_final = round(size_capped, sz_decimals)

        if size_final <= 0:
            print(f"\n{Fore.RED}❌ Calculated size is 0 (risk too small or rounding error){Style.RESET_ALL}")
            sys.exit(1)

        notional_value = size_final * entry
        leverage = notional_value / wallet_state['equity']

        calc_results = {
            'equity': wallet_state['equity'],
            'risk_pct': risk_pct,
            'risk_amt': risk_amt,
            'size_original': size_original,
            'size_final': size_final,
            'notional_value': notional_value,
            'leverage': leverage,
            'leverage_capped': leverage_capped
        }

    except Exception as e:
        print(f"\n{Fore.RED}❌ Position sizing calculation failed: {e}{Style.RESET_ALL}")
        sys.exit(1)

    # Prepare trade data
    trade_data = {
        'symbol': ticker,
        'direction': direction,
        'entry': entry,
        'stop_loss': stop_loss,
        'targets': targets
    }

    # Display preview
    display_trade_preview(trade_data, calc_results)

    # Confirm
    if not prompt_confirmation():
        print(f"\n{Fore.YELLOW}❌ Trade cancelled.{Style.RESET_ALL}\n")
        sys.exit(0)

    # Insert to database
    try:
        signal_data = {
            'bot_name': BOT_NAME,
            'symbol': ticker,
            'direction': direction,
            'entry_1': entry,
            'stop_loss': stop_loss,
            'target_1': targets[0] if len(targets) > 0 else None,
            'target_2': targets[1] if len(targets) > 1 else None,
            'target_3': targets[2] if len(targets) > 2 else None,
            'target_4': targets[3] if len(targets) > 3 else None,
            'target_5': targets[4] if len(targets) > 4 else None
        }

        signal_id = insert_signal_to_db(signal_data)
        display_success_message(signal_id)

    except Exception as e:
        print(f"\n{Fore.RED}❌ {e}{Style.RESET_ALL}\n")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Fore.YELLOW}❌ Interrupted by user.{Style.RESET_ALL}\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Fore.RED}❌ Unexpected error: {e}{Style.RESET_ALL}\n")
        sys.exit(1)
