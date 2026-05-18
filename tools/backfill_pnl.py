"""
Backfill pnl_percent_actual for closed entry signals using cumulative
close fills from Hyperliquid.

Earlier behavior recorded only the first close fill's PnL, so multi-leg
exits (TP1+TP2+TP3+BE/SL) were under-reported. This pulls every wallet's
fills once and replays the new _get_pnl_from_fills logic against any
closed signal whose entry_filled_at falls inside the available fills
window.

Usage:
    python tools/backfill_pnl.py             # apply
    python tools/backfill_pnl.py --dry-run   # report deltas, write nothing
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(REPO_ROOT, ".env"))

from fleet_runner import FLEET_CONFIG  # noqa: E402
from hyperliquid_top_gun import HyperLiquidTopGun  # noqa: E402

DB_PATH = "/Users/johnny_main/Developer/data/signals/signals.db"


def make_bot(cfg):
    return HyperLiquidTopGun(
        bot_id=cfg["bot_id"],
        private_key=cfg["private_key"],
        risk_per_trade=cfg.get("risk_per_trade") or 0.01,
        max_leverage=cfg.get("max_leverage") or 1.0,
        default_sl_dist=cfg.get("default_sl_dist") or 0.10,
        max_concurrent_positions=cfg.get("max_concurrent_positions") or 3,
        allowed_directions=cfg.get("allowed_directions") or "both",
        max_roi_loss=cfg.get("max_roi_loss") or 0.20,
    )


def backfill_for_bot(cfg, conn, dry_run):
    if not cfg.get("private_key"):
        print(f"  skip {cfg['bot_id']}: no private key")
        return (0, 0, 0)

    bot = make_bot(cfg)
    c = conn.cursor()
    c.execute(
        """
        SELECT id, symbol, entry_1, position_size_actual, entry_filled_at, pnl_percent_actual
        FROM signals
        WHERE bot_name = ?
          AND signal_type = 'entry'
          AND status = 'closed'
          AND entry_filled_at IS NOT NULL
          AND entry_1 IS NOT NULL
          AND position_size_actual IS NOT NULL
        ORDER BY entry_filled_at DESC
        """,
        (cfg["bot_id"],),
    )
    rows = c.fetchall()

    updated = 0
    no_data = 0
    unchanged = 0
    total_old = 0.0
    total_new = 0.0

    for sid, symbol, entry_px, size, entry_at, old_pnl in rows:
        ticker = symbol.upper().replace("USDT", "").replace("PERP", "")
        pnl_info = bot._get_pnl_from_fills(ticker, entry_px, size, entry_at)
        if pnl_info is None:
            no_data += 1
            continue
        new_pnl, net_pnl, _avg_close = pnl_info
        old_val = float(old_pnl) if old_pnl is not None else 0.0
        delta = new_pnl - old_val
        total_old += old_val
        total_new += new_pnl

        if abs(delta) < 0.005:  # <0.5bp difference, ignore
            unchanged += 1
            continue

        print(
            f"  {ticker:<8} id={sid:<5} entry={entry_at[:19]} "
            f"old={old_val:+7.3f}% → new={new_pnl:+7.3f}% (Δ {delta:+.3f}%, ${net_pnl:+.2f} net)"
        )
        updated += 1
        if not dry_run:
            today = datetime.now().date().isoformat()
            note_tail = (
                f" | Backfilled cumulative PnL: {new_pnl:.2f}% (net ${net_pnl:+.2f}) on {today}"
            )
            c.execute(
                "UPDATE signals SET pnl_percent_actual = ?, "
                "notes = COALESCE(notes, '') || ? WHERE id = ?",
                (new_pnl, note_tail, sid),
            )

    if not dry_run:
        conn.commit()

    print(
        f"  [{cfg['bot_id']}] scanned={len(rows)} updated={updated} "
        f"unchanged={unchanged} no_fills_data={no_data}"
    )
    print(f"  total_old={total_old:+.2f}% total_new={total_new:+.2f}% delta={total_new-total_old:+.2f}%")
    return (updated, unchanged, no_data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report deltas, write nothing")
    parser.add_argument("--bot", help="Restrict to one bot_id (default: all in FLEET_CONFIG)")
    args = parser.parse_args()

    if args.dry_run:
        print(">>> DRY RUN — no DB writes <<<\n")

    conn = sqlite3.connect(DB_PATH, timeout=30)
    grand = [0, 0, 0]
    for cfg in FLEET_CONFIG:
        if args.bot and cfg["bot_id"] != args.bot:
            continue
        print(f"\n=== {cfg['bot_id']} ===")
        u, c_, n = backfill_for_bot(cfg, conn, args.dry_run)
        grand[0] += u
        grand[1] += c_
        grand[2] += n
    conn.close()

    print("\n=== TOTAL ===")
    print(f"updated={grand[0]} unchanged={grand[1]} no_fills_data={grand[2]}")
    if args.dry_run:
        print("(dry run — no DB changes)")


if __name__ == "__main__":
    main()
