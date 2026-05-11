#!/usr/bin/env python3
"""
CLEANUP STALE ORDERS
--------------------
Standalone script to immediately cancel all unfilled entry orders older than 24 hours.
This is a one-time cleanup - the fleet's reconciliation loop will handle ongoing cleanup.

Usage:
    python cleanup_stale_orders.py              # Clean up all enabled wallets
    python cleanup_stale_orders.py --all        # Clean up ALL wallets (including disabled)
    python cleanup_stale_orders.py --hours 48   # Use custom staleness threshold (default: 24)
"""

import os
import sys
import sqlite3
import argparse
from datetime import datetime
from dotenv import load_dotenv, find_dotenv
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# --- Load Environment ---
load_dotenv(find_dotenv())

# Database path (same as fleet runner)
DB_PATH = "/Users/johnny_main/Developer/data/signals/signals.db"

# Fleet configuration (mirror of fleet_runner.py)
FLEET_CONFIG = [
    {
        "bot_id": "AITA Hyperliquid",
        "private_key": os.getenv("PRIVATE_KEY_ALCHEMIST"),
        "enabled": True,
    },
    {
        "bot_id": "SentientGuard",
        "private_key": os.getenv("PRIVATE_KEY_SENTIENT"),
        "enabled": False,
    },
    {
        "bot_id": "AlphaCryptoSignal",
        "private_key": os.getenv("PRIVATE_KEY_ALPHA"),
        "enabled": False,
    },
    {
        "bot_id": "Manual Trader",
        "private_key": os.getenv("PRIVATE_KEY_MANUAL"),
        "enabled": False,
    }
]


def get_hl_connection(private_key):
    """Initialize Hyperliquid connection for a wallet."""
    account = Account.from_key(private_key)
    is_mainnet = os.getenv("IS_MAINNET") == "True"
    node_url = constants.MAINNET_API_URL if is_mainnet else constants.TESTNET_API_URL

    info = Info(node_url, skip_ws=True)
    exchange = Exchange(account, node_url)

    return account, info, exchange


def cleanup_wallet_orders(bot_id, private_key, stale_hours=24, dry_run=False):
    """
    Cancel all stale orders for a specific wallet.

    Args:
        bot_id: Bot identifier (matches signals.bot_name)
        private_key: Wallet private key
        stale_hours: Consider orders stale after this many hours
        dry_run: If True, don't actually cancel - just report

    Returns:
        Tuple of (stale_db_orders, stale_hl_orders, cancelled_count)
    """
    print(f"\n{'='*60}")
    print(f"  Wallet: {bot_id}")
    print(f"{'='*60}")

    account, info, exchange = get_hl_connection(private_key)
    print(f"  Address: {account.address[:10]}...")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    stale_db_orders = []
    cancelled_count = 0

    # --- PART 1: Find stale orders from database ---
    print(f"\n  Checking database for unfilled orders older than {stale_hours}h...")

    c.execute("""
        SELECT id, symbol, order_id_entry, order_id_sl,
               order_id_tp1, order_id_tp2, order_id_tp3, order_id_tp4, order_id_tp5,
               created_at, entry_1
        FROM signals
        WHERE bot_name = ?
        AND status = 'sent'
        AND datetime(created_at) < datetime('now', ?)
    """, (bot_id, f'-{stale_hours} hours'))

    stale_signals = c.fetchall()

    if stale_signals:
        print(f"  Found {len(stale_signals)} stale signals in database:")

        for row in stale_signals:
            signal_id, ticker, entry_oid, sl_oid, tp1, tp2, tp3, tp4, tp5, created_at, entry_price = row
            ticker = ticker.upper().replace("USDT", "").replace("PERP", "")

            age_hours = (datetime.now() - datetime.fromisoformat(created_at)).total_seconds() / 3600
            print(f"\n    Signal {signal_id}: {ticker}")
            print(f"      Created: {created_at} ({age_hours:.1f}h ago)")
            print(f"      Entry Price: ${float(entry_price) if entry_price else 'N/A'}")
            print(f"      Entry OID: {entry_oid}")

            stale_db_orders.append({
                'signal_id': signal_id,
                'ticker': ticker,
                'entry_oid': entry_oid,
                'sl_oid': sl_oid,
                'tp_oids': [tp1, tp2, tp3, tp4, tp5],
                'created_at': created_at
            })

            if not dry_run:
                # Cancel entry order
                if entry_oid:
                    try:
                        exchange.cancel(ticker, entry_oid)
                        print(f"      Cancelled entry order {entry_oid}")
                        cancelled_count += 1
                    except Exception as e:
                        print(f"      Could not cancel entry: {e}")

                # Cancel SL order
                if sl_oid:
                    try:
                        exchange.cancel(ticker, sl_oid)
                        print(f"      Cancelled SL order {sl_oid}")
                        cancelled_count += 1
                    except Exception as e:
                        print(f"      Could not cancel SL: {e}")

                # Cancel TP orders
                for i, tp_oid in enumerate([tp1, tp2, tp3, tp4, tp5], 1):
                    if tp_oid:
                        try:
                            exchange.cancel(ticker, tp_oid)
                            print(f"      Cancelled TP{i} order {tp_oid}")
                            cancelled_count += 1
                        except Exception as e:
                            print(f"      Could not cancel TP{i}: {e}")

                # Update database
                c.execute("""
                    UPDATE signals
                    SET status = 'expired',
                        notes = COALESCE(notes, '') || ' | Manually cleaned up via cleanup_stale_orders.py'
                    WHERE id = ?
                """, (signal_id,))
    else:
        print(f"  No stale signals in database")

    conn.commit()

    # --- PART 2: Check Hyperliquid for orphaned orders ---
    print(f"\n  Checking Hyperliquid for orphaned orders...")

    try:
        open_orders = info.frontend_open_orders(account.address)

        if open_orders:
            print(f"  Found {len(open_orders)} open orders on Hyperliquid:")

            for order in open_orders:
                ticker = order['coin']
                oid = order['oid']
                side = 'BUY' if order['side'] == 'B' else 'SELL'
                price = order.get('limitPx', 'N/A')
                size = order.get('sz', 'N/A')
                order_type = order.get('orderType', 'unknown')

                print(f"\n    {ticker} {side} @ ${price}")
                print(f"      OID: {oid} | Size: {size} | Type: {order_type}")

                # Check if this order is tracked in database
                c.execute("""
                    SELECT id, status FROM signals
                    WHERE (order_id_entry = ? OR order_id_sl = ? OR
                           order_id_tp1 = ? OR order_id_tp2 = ? OR
                           order_id_tp3 = ? OR order_id_tp4 = ? OR order_id_tp5 = ?)
                    AND bot_name = ?
                """, (oid, oid, oid, oid, oid, oid, oid, bot_id))

                db_match = c.fetchone()
                if db_match:
                    print(f"      DB Status: Signal {db_match[0]} (status={db_match[1]})")
                else:
                    print(f"      DB Status: ORPHANED (not tracked in database)")
        else:
            print(f"  No open orders on Hyperliquid")

    except Exception as e:
        print(f"  Error checking Hyperliquid orders: {e}")

    conn.close()

    return len(stale_db_orders), len(open_orders) if open_orders else 0, cancelled_count


def main():
    parser = argparse.ArgumentParser(description='Clean up stale limit orders')
    parser.add_argument('--all', action='store_true', help='Process all wallets (including disabled)')
    parser.add_argument('--hours', type=int, default=24, help='Staleness threshold in hours (default: 24)')
    parser.add_argument('--dry-run', action='store_true', help='Report only, do not cancel orders')
    args = parser.parse_args()

    print("=" * 60)
    print("  STALE ORDER CLEANUP")
    print("=" * 60)
    print(f"  Staleness threshold: {args.hours} hours")
    print(f"  Mode: {'DRY RUN (no changes)' if args.dry_run else 'LIVE (will cancel orders)'}")
    print(f"  Network: {'MAINNET' if os.getenv('IS_MAINNET') == 'True' else 'TESTNET'}")

    total_db_stale = 0
    total_hl_orders = 0
    total_cancelled = 0

    for config in FLEET_CONFIG:
        bot_id = config["bot_id"]
        private_key = config["private_key"]
        enabled = config.get("enabled", True)

        # Skip disabled wallets unless --all flag
        if not args.all and not enabled:
            print(f"\n  Skipping {bot_id} (disabled)")
            continue

        if not private_key:
            print(f"\n  Skipping {bot_id} (no private key)")
            continue

        try:
            db_stale, hl_orders, cancelled = cleanup_wallet_orders(
                bot_id, private_key,
                stale_hours=args.hours,
                dry_run=args.dry_run
            )
            total_db_stale += db_stale
            total_hl_orders += hl_orders
            total_cancelled += cancelled
        except Exception as e:
            print(f"\n  ERROR processing {bot_id}: {e}")

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Stale signals found in DB: {total_db_stale}")
    print(f"  Open orders on Hyperliquid: {total_hl_orders}")
    if not args.dry_run:
        print(f"  Orders cancelled: {total_cancelled}")
    print("=" * 60)


if __name__ == "__main__":
    main()
