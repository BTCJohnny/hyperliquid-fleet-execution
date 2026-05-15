"""
Health check for the trading pipeline.

Verifies:
- Fleet runner process logging is fresh (catches process death).
- Each enabled bot's three threads are writing heartbeats (catches thread
  death where the process is alive but a thread silently exited).
- Telegram ingest stack log freshness.

Notification policy: notify only on state changes — OK→FAIL (new outage),
FAIL→OK (recovery), or failure-signature change (new error mode). If
something stays broken, re-nag every RENAG_SECONDS (default 4h) so a long
outage gets ~6 reminders/day, not 288. Every run still prints status to
stdout so launchd logs remain a full history.

Designed to run under launchd every ~5 minutes (com.hyperliquid.healthcheck).
Always exits 0 so launchd's KeepAlive-on-crash never fires from this script.
"""

import hashlib
import json
import os
import subprocess
import sys
import time

LOGS_DIR = "/Users/johnny_main/Developer/data/logs"
SIGNALS_DIR = "/Users/johnny_main/Developer/data/signals"
STATE_PATH = "/Users/johnny_main/Developer/data/signals/healthcheck_state.json"
RENAG_SECONDS = 4 * 60 * 60  # re-notify every 4h if same failure persists

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


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "OK", "signature": "", "last_notified_ts": 0}


def save_state(state):
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"WARN: could not save state: {e}")


def signature_of(failures):
    """Stable hash of the failure set, ignoring numeric drift in age values.
    Without this, every run produces a 'new' signature (since stale ages
    keep changing), defeating the dedupe."""
    if not failures:
        return ""
    # Strip the numeric tail like "stale 4.3m" → "stale Nm" so age drift
    # doesn't look like a new failure.
    import re
    canon = []
    for f in failures:
        canon.append(re.sub(r'\d+(\.\d+)?', 'N', f))
    canon.sort()
    return hashlib.sha256("\n".join(canon).encode()).hexdigest()[:16]


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

    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    state = load_state()
    new_status = "FAIL" if failures else "OK"
    new_sig = signature_of(failures)
    should_notify = False
    reason = ""

    if new_status == "FAIL" and state["status"] == "OK":
        should_notify, reason = True, "new outage"
    elif new_status == "OK" and state["status"] == "FAIL":
        should_notify, reason = True, "recovered"
    elif new_status == "FAIL" and new_sig != state.get("signature"):
        should_notify, reason = True, "new failure mode"
    elif new_status == "FAIL" and (now - state.get("last_notified_ts", 0)) > RENAG_SECONDS:
        hours = (now - state.get("last_notified_ts", 0)) / 3600
        should_notify, reason = True, f"re-nag ({hours:.1f}h since last)"

    if should_notify:
        if new_status == "FAIL":
            notify("Fleet Health", " | ".join(failures))
        else:
            notify("Fleet Health", "Recovered — all checks passing")
        state["last_notified_ts"] = now

    state["status"] = new_status
    state["signature"] = new_sig
    save_state(state)

    if failures:
        notif_tag = f" [notified: {reason}]" if should_notify else " [silenced]"
        print(f"[{ts}] FAIL{notif_tag}: {failures}")
    else:
        notif_tag = " [notified: recovered]" if should_notify else ""
        print(f"[{ts}] OK{notif_tag}")


if __name__ == "__main__":
    main()
