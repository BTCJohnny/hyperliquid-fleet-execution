"""
Health check for the trading pipeline.

Verifies:
- Fleet runner process logging is fresh (catches process death).
- Each enabled bot's three threads are writing heartbeats (catches thread
  death where the process is alive but a thread silently exited).
- Telegram ingest stack log freshness.

Emits a macOS notification on any failure.

Designed to run under launchd every ~5 minutes (com.hyperliquid.healthcheck).
Always exits 0 so launchd's KeepAlive-on-crash never fires from this script.
"""

import os
import subprocess
import sys
import time

LOGS_DIR = "/Users/johnny_main/Developer/data/logs"
SIGNALS_DIR = "/Users/johnny_main/Developer/data/signals"

# Per-thread heartbeat staleness budgets (seconds).
# signal: 2s poll + processing — 60s is generous
# fill_monitor: 10s poll — 120s
# reconcile: 60s poll — 300s
THREAD_BUDGETS = {
    "signal":       60,
    "fill_monitor": 120,
    "reconcile":    300,
}

# (label, filename, max_age_minutes)
LOG_CHECKS = [
    ("Fleet runner",       "fleet_launchd.err",            3),
    ("Telegram parser",    "telegram_signals_sqlite.log", 10),
    ("Telegram forwarder", "telegram_forwarder.log",      10),
]


def notify(title, message):
    msg = message.replace('"', "'")
    ttl = title.replace('"', "'")
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{msg}" with title "{ttl}" sound name "Glass"'],
        check=False,
    )


def load_enabled_bots():
    """Pull the enabled bot list from fleet_runner.FLEET_CONFIG.
    Returns a list of safe_bot_id strings (matching the heartbeat filename suffix)."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, repo_root)
    try:
        from fleet_runner import FLEET_CONFIG
    except Exception as e:
        print(f"WARN: could not import FLEET_CONFIG: {e}")
        return []
    return [
        bot["bot_id"].replace(" ", "_").replace("/", "_")
        for bot in FLEET_CONFIG
        if bot.get("enabled") and bot.get("private_key")
    ]


def main():
    now = time.time()
    failures = []

    # 1. Log-file freshness (catches process death)
    for label, fname, max_age_min in LOG_CHECKS:
        path = os.path.join(LOGS_DIR, fname)
        if not os.path.exists(path):
            failures.append(f"{label}: log missing ({fname})")
            continue
        age_min = (now - os.path.getmtime(path)) / 60.0
        if age_min > max_age_min:
            failures.append(f"{label}: stale {age_min:.1f}m (limit {max_age_min}m)")

    # 2. Per-thread heartbeats (catches silent thread death)
    for safe_id in load_enabled_bots():
        for thread, budget_sec in THREAD_BUDGETS.items():
            hb_path = os.path.join(SIGNALS_DIR, f"heartbeat_{safe_id}_{thread}.txt")
            if not os.path.exists(hb_path):
                failures.append(f"{safe_id}/{thread}: heartbeat missing")
                continue
            try:
                with open(hb_path) as f:
                    last_beat = float(f.read().strip())
            except Exception as e:
                failures.append(f"{safe_id}/{thread}: heartbeat unreadable ({e})")
                continue
            age = now - last_beat
            if age > budget_sec:
                failures.append(f"{safe_id}/{thread}: stale {age:.0f}s (limit {budget_sec}s)")

    if failures:
        notify("Fleet Health", " | ".join(failures))
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] FAIL: {failures}")
    else:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] OK")


if __name__ == "__main__":
    main()
