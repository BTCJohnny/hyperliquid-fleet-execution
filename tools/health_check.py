"""
Health check for the trading pipeline.

Verifies the fleet runner and the Telegram ingest stack are alive by checking
log-file freshness. Emits a macOS notification on any failure.

Designed to run under launchd every ~5 minutes (com.hyperliquid.healthcheck).
Always exits 0 so launchd's KeepAlive-on-crash never fires from this script.
"""

import os
import subprocess
import time

LOGS_DIR = "/Users/johnny_main/Developer/data/logs"

# (label, filename, max_age_minutes)
CHECKS = [
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


def main():
    now = time.time()
    failures = []
    for label, fname, max_age_min in CHECKS:
        path = os.path.join(LOGS_DIR, fname)
        if not os.path.exists(path):
            failures.append(f"{label}: log missing ({fname})")
            continue
        age_min = (now - os.path.getmtime(path)) / 60.0
        if age_min > max_age_min:
            failures.append(f"{label}: stale {age_min:.1f}m (limit {max_age_min}m)")

    if failures:
        notify("Fleet Health", " | ".join(failures))
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] FAIL: {failures}")
    else:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] OK")


if __name__ == "__main__":
    main()
