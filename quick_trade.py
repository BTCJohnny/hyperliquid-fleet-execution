#!/usr/bin/env python3
"""
Quick Trade CLI - Direct order placement on Hyperliquid.

Usage:
    python quick_trade.py long ETH 2800 2700           # Long ETH, entry $2800, stop $2700, default risk
    python quick_trade.py short BTC 100000 105000 --risk 2   # Short BTC with 2% risk
    python quick_trade.py cancel ETH                   # Cancel all ETH orders
    python quick_trade.py cancel-all                   # Cancel ALL orders
    python quick_trade.py status                       # Show wallet + positions + orders
    python quick_trade.py close ETH                    # Market close ETH position

Wallet selection:
    --wallet manual      # Use PRIVATE_KEY_MANUAL (default)
    --wallet alchemist   # Use PRIVATE_KEY_ALCHEMIST
    --wallet sentient    # Use PRIVATE_KEY_SENTIENT
    --wallet alpha       # Use PRIVATE_KEY_ALPHA
"""

WALLET_MAP = {
    "manual": "PRIVATE_KEY_MANUAL",
    "alchemist": "PRIVATE_KEY_ALCHEMIST",
    "sentient": "PRIVATE_KEY_SENTIENT",
    "alpha": "PRIVATE_KEY_ALPHA",
}

import os
import sys
import math
import argparse
from dotenv import load_dotenv
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# Load environment
ENV_PATH = "/Users/johnny_main/Developer/projects/telegram_trading_bots/hyper_v1/.env"
load_dotenv(ENV_PATH)

# Configuration
DEFAULT_RISK_PCT = float(os.getenv("RISK_PER_TRADE", "0.01"))
MAX_RISK_PCT = 0.10  # 10% max
MAX_SL_DISTANCE = 0.10  # 10% max stop loss distance


class QuickTrader:
    def __init__(self, wallet="manual"):
        wallet_key = WALLET_MAP.get(wallet.lower(), "PRIVATE_KEY_MANUAL")
        private_key = os.getenv(wallet_key)
        if not private_key or private_key == "0x...":
            print(f"ERROR: {wallet_key} not configured in .env")
            sys.exit(1)
        self.wallet_name = wallet.capitalize()

        self.account = Account.from_key(private_key)
        is_mainnet = os.getenv("IS_MAINNET") == "True"
        base_url = constants.MAINNET_API_URL if is_mainnet else constants.TESTNET_API_URL

        self.info = Info(base_url, skip_ws=True)
        self.exchange = Exchange(self.account, base_url)
        self.env = "Mainnet" if is_mainnet else "Testnet"

        # Load metadata
        meta = self.info.meta()
        self.sz_decimals_map = {a['name']: a['szDecimals'] for a in meta['universe']}

    def get_sz_decimals(self, ticker):
        return self.sz_decimals_map.get(ticker, 3)

    def round_px(self, ticker, price):
        if price == 0:
            return 0.0
        magnitude = math.floor(math.log10(abs(price)))
        sig_figs_decimals = 5 - 1 - magnitude
        sz_decimals = self.get_sz_decimals(ticker)
        max_decimals = 6 - sz_decimals
        final_decimals = min(sig_figs_decimals, max_decimals)
        return round(price, max(0, final_decimals))

    def get_equity(self):
        user_state = self.info.user_state(self.account.address)
        return float(user_state["marginSummary"]["accountValue"])

    def get_current_price(self, ticker):
        mids = self.info.all_mids()
        return float(mids.get(ticker, 0))

    def validate_ticker(self, ticker):
        return ticker in self.sz_decimals_map

    # =========================================================================
    # COMMANDS
    # =========================================================================

    def cmd_status(self):
        """Show wallet status, positions, and open orders."""
        user_state = self.info.user_state(self.account.address)
        equity = float(user_state["marginSummary"]["accountValue"])

        print("=" * 60)
        print(f"WALLET STATUS: {self.wallet_name} ({self.env})")
        print("=" * 60)
        print(f"Address:  {self.account.address[:10]}...{self.account.address[-8:]}")
        print(f"Equity:   ${equity:,.2f}")
        print("-" * 60)

        # Positions
        positions = user_state.get("assetPositions", [])
        open_positions = [p for p in positions if float(p["position"]["szi"]) != 0]

        print(f"OPEN POSITIONS ({len(open_positions)})")
        if open_positions:
            for p in open_positions:
                pos = p["position"]
                size = float(pos["szi"])
                entry = float(pos.get("entryPx", 0))
                upnl = float(pos.get("unrealizedPnl", 0))
                direction = "LONG" if size > 0 else "SHORT"
                print(f"  {pos['coin']:6} | {direction:5} | Size: {abs(size):>10} | Entry: ${entry:>10,.2f} | uPnL: ${upnl:>8,.2f}")
        else:
            print("  (none)")

        # Open orders
        print("-" * 60)
        open_orders = self.info.frontend_open_orders(self.account.address)
        print(f"OPEN ORDERS ({len(open_orders)})")
        if open_orders:
            for o in open_orders:
                side = "BUY" if o['side'] == 'B' else "SELL"
                print(f"  {o['coin']:6} | {side:4} | Size: {float(o['sz']):>10} | Price: ${float(o['limitPx']):>10,.2f} | OID: {o['oid']}")
        else:
            print("  (none)")
        print("=" * 60)

    def cmd_trade(self, direction, ticker, entry, stop, risk_pct):
        """Place a trade with entry and stop loss."""
        ticker = ticker.upper().replace("USDT", "").replace("PERP", "")
        is_buy = direction == "long"

        # Validate ticker
        if not self.validate_ticker(ticker):
            print(f"ERROR: Ticker '{ticker}' not found on Hyperliquid")
            sys.exit(1)

        # Validate stop loss direction
        if is_buy and stop >= entry:
            print(f"ERROR: Stop loss must be BELOW entry for LONG")
            sys.exit(1)
        if not is_buy and stop <= entry:
            print(f"ERROR: Stop loss must be ABOVE entry for SHORT")
            sys.exit(1)

        # Enforce 10% max stop loss distance
        sl_distance_pct = abs(entry - stop) / entry
        if sl_distance_pct > MAX_SL_DISTANCE:
            old_stop = stop
            dist = entry * MAX_SL_DISTANCE
            stop = (entry - dist) if is_buy else (entry + dist)
            print(f"WARNING: SL too wide ({sl_distance_pct*100:.1f}%). Capping to 10%: ${old_stop} -> ${stop:.2f}")

        # Get equity and calculate size
        equity = self.get_equity()
        current_price = self.get_current_price(ticker)

        risk_amt = equity * risk_pct
        price_diff = abs(entry - stop)
        size = risk_amt / price_diff

        # Round for precision
        sz_decimals = self.get_sz_decimals(ticker)
        size = round(size, sz_decimals)
        entry_px = self.round_px(ticker, entry)
        stop_px = self.round_px(ticker, stop)

        if size <= 0:
            print(f"ERROR: Calculated size is 0 (risk too small)")
            sys.exit(1)

        notional = size * entry_px
        leverage = notional / equity

        # Preview
        print("=" * 60)
        print(f"TRADE: {ticker} {direction.upper()} ({self.wallet_name})")
        print("=" * 60)
        print(f"Environment:   {self.env}")
        print(f"Current Price: ${current_price:,.2f}")
        print("-" * 60)
        print(f"Entry:         ${entry_px:,.2f}")
        print(f"Stop Loss:     ${stop_px:,.2f} ({sl_distance_pct*100:.1f}% away)")
        print(f"Risk:          {risk_pct*100:.1f}% = ${risk_amt:,.2f}")
        print("-" * 60)
        print(f"Size:          {size} {ticker}")
        print(f"Notional:      ${notional:,.2f}")
        print(f"Leverage:      {leverage:.2f}x")
        print("=" * 60)

        # Execute
        print("Placing entry order...")
        result_entry = self.exchange.order(
            name=ticker,
            is_buy=is_buy,
            sz=size,
            limit_px=entry_px,
            order_type={"limit": {"tif": "Gtc"}},
            reduce_only=False
        )

        if not result_entry or result_entry.get('status') != 'ok':
            print(f"ERROR: Entry order failed: {result_entry}")
            sys.exit(1)

        try:
            entry_oid = result_entry['response']['data']['statuses'][0]['resting']['oid']
        except:
            entry_oid = "unknown"
        print(f"Entry placed    | OID: {entry_oid}")

        # Place stop loss
        print("Placing stop loss...")
        result_sl = self.exchange.order(
            name=ticker,
            is_buy=not is_buy,
            sz=size,
            limit_px=stop_px,
            order_type={"trigger": {"triggerPx": stop_px, "isMarket": True, "tpsl": "sl"}},
            reduce_only=True
        )

        if not result_sl or result_sl.get('status') != 'ok':
            print(f"ERROR: Stop loss failed: {result_sl}")
            print("WARNING: Cancelling entry order for safety...")
            self.exchange.cancel(ticker, entry_oid)
            sys.exit(1)

        try:
            sl_oid = result_sl['response']['data']['statuses'][0]['resting']['oid']
        except:
            sl_oid = "unknown"
        print(f"Stop loss placed | OID: {sl_oid}")

        print("-" * 60)
        print("SUCCESS")

    def cmd_cancel(self, ticker):
        """Cancel all orders for a ticker."""
        ticker = ticker.upper().replace("USDT", "").replace("PERP", "")

        open_orders = self.info.frontend_open_orders(self.account.address)
        ticker_orders = [o for o in open_orders if o['coin'] == ticker]

        if not ticker_orders:
            print(f"No open orders for {ticker}")
            return

        print(f"Cancelling {len(ticker_orders)} orders for {ticker}...")
        for o in ticker_orders:
            result = self.exchange.cancel(ticker, o['oid'])
            status = "OK" if result and result.get('status') == 'ok' else "FAILED"
            print(f"  OID {o['oid']}: {status}")

        print("Done")

    def cmd_cancel_all(self):
        """Cancel ALL open orders."""
        open_orders = self.info.frontend_open_orders(self.account.address)

        if not open_orders:
            print("No open orders")
            return

        print(f"Cancelling {len(open_orders)} orders...")
        for o in open_orders:
            result = self.exchange.cancel(o['coin'], o['oid'])
            status = "OK" if result and result.get('status') == 'ok' else "FAILED"
            print(f"  {o['coin']} OID {o['oid']}: {status}")

        print("Done")

    def cmd_close(self, ticker):
        """Market close a position."""
        ticker = ticker.upper().replace("USDT", "").replace("PERP", "")

        # First cancel any open orders for this ticker
        open_orders = self.info.frontend_open_orders(self.account.address)
        ticker_orders = [o for o in open_orders if o['coin'] == ticker]

        if ticker_orders:
            print(f"Cancelling {len(ticker_orders)} open orders...")
            for o in ticker_orders:
                self.exchange.cancel(ticker, o['oid'])

        # Market close
        print(f"Market closing {ticker}...")
        result = self.exchange.market_close(ticker)

        if result is None:
            print(f"No position to close for {ticker}")
        elif result.get('status') == 'ok':
            print(f"Position closed")
        else:
            print(f"Close failed: {result}")


def main():
    parser = argparse.ArgumentParser(description="Quick Trade CLI for Hyperliquid")
    parser.add_argument("--wallet", "-w", default="manual", choices=["manual", "alchemist", "sentient", "alpha"],
                        help="Wallet to use (default: manual)")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # status
    subparsers.add_parser("status", help="Show wallet status, positions, orders")

    # long
    p_long = subparsers.add_parser("long", help="Place a long trade")
    p_long.add_argument("ticker", help="Ticker (e.g., ETH, BTC)")
    p_long.add_argument("entry", type=float, help="Entry price")
    p_long.add_argument("stop", type=float, help="Stop loss price")
    p_long.add_argument("--risk", type=float, default=DEFAULT_RISK_PCT*100, help=f"Risk %% (default: {DEFAULT_RISK_PCT*100})")

    # short
    p_short = subparsers.add_parser("short", help="Place a short trade")
    p_short.add_argument("ticker", help="Ticker (e.g., ETH, BTC)")
    p_short.add_argument("entry", type=float, help="Entry price")
    p_short.add_argument("stop", type=float, help="Stop loss price")
    p_short.add_argument("--risk", type=float, default=DEFAULT_RISK_PCT*100, help=f"Risk %% (default: {DEFAULT_RISK_PCT*100})")

    # cancel
    p_cancel = subparsers.add_parser("cancel", help="Cancel all orders for a ticker")
    p_cancel.add_argument("ticker", help="Ticker (e.g., ETH)")

    # cancel-all
    subparsers.add_parser("cancel-all", help="Cancel ALL open orders")

    # close
    p_close = subparsers.add_parser("close", help="Market close a position")
    p_close.add_argument("ticker", help="Ticker (e.g., ETH)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    trader = QuickTrader(wallet=args.wallet)

    if args.command == "status":
        trader.cmd_status()

    elif args.command in ["long", "short"]:
        risk_pct = args.risk / 100  # Convert to decimal
        if risk_pct > MAX_RISK_PCT:
            print(f"ERROR: Risk cannot exceed {MAX_RISK_PCT*100}%")
            sys.exit(1)
        trader.cmd_trade(args.command, args.ticker, args.entry, args.stop, risk_pct)

    elif args.command == "cancel":
        trader.cmd_cancel(args.ticker)

    elif args.command == "cancel-all":
        trader.cmd_cancel_all()

    elif args.command == "close":
        trader.cmd_close(args.ticker)


if __name__ == "__main__":
    main()
