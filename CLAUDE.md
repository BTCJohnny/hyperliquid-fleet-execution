# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is an automated trading execution system for Hyperliquid (Testnet/Mainnet) that processes signals from Telegram channels. The system operates as the **execution layer** in a larger pipeline - signal ingestion happens in an external repository at `/Users/johnny_main/Developer/projects/telegram_forwarder/`.

**Architecture:** `Telegram` → `Forwarder` → `Ingester` → `SQLite DB` → `Fleet Runner` (this repo) → `Hyperliquid API`

**Python Version:** Python 3.12+ (uses venv at `./venv`)

**Key Dependencies:**
- `hyperliquid-python-sdk` (0.19.0+) - Hyperliquid API wrapper
- `eth-account` (0.13.7+) - Ethereum account/wallet management
- `pandas` (2.3.0+) - Data analysis for PnL dashboard
- `python-dotenv` (1.1.0+) - Environment variable management
- `colorama` (0.4.6+) - Terminal color formatting

## Common Commands

### Running the System
```bash
# Start the fleet (runs all configured bots)
python fleet_runner.py

# Emergency kill switch (cancel all orders and close all positions)
python nuke_account.py "Apprentice Alchemist"  # Specific bot
python nuke_account.py ALL                      # All bots
```

### Admin Controls
```bash
# Query status for a specific bot or all bots
python admin_controls.py "Apprentice" STATUS
python admin_controls.py ALL STATUS
python admin_controls.py ALL POSITIONS
python admin_controls.py ALL ORDERS

# Control commands (PAUSE, RESUME, CLOSE_ALL)
python admin_controls.py ALL PAUSE
python admin_controls.py "Alpha" RESUME
```

### Analytics & Monitoring
```bash
# View PnL dashboard (terminal-based analytics)
python pnl_dashboard.py

# Database maintenance
python nuke_database.py        # Reset signals database (DESTRUCTIVE)
python reset_id_counter.py     # Reset SQLite ID counter
python enable_wal.py           # Enable WAL mode for concurrent access
```

### Testing & Diagnostics
```bash
# Test files are in test/ directory
python test/connection_test.py       # Fleet connectivity check
python test/check_db_status.py       # Database query tool (pandas-based)
python test/test_db_integration.py   # Full integration test (signal injection → processing)
python test/test_rejection.py        # Order rejection testing (precision checks)
python test/test_controls.py         # Admin controls testing
python test/test_parser_regex.py     # Signal parser regex validation

# Diagnostic & Monitoring Tools
python test/reconcile_alpha_signals.py   # Signal reconciliation report (compare telegram/db/hyperliquid)
python test/test_reconcile_alpha.py      # Unit tests for reconciliation system
python test/view_logs.py                 # Interactive log viewer for all system logs
python test/view_logs.py --status        # Check status of all log files
python test/view_logs.py --errors        # Show only errors/warnings
python test/view_logs.py --bot Alpha     # Filter logs by bot name
python test/view_logs.py --tail -f       # Follow all logs in real-time
```

## Key Architecture Concepts

### Multi-Bot Fleet System

The system uses a **Fleet Runner** pattern where `fleet_runner.py` spawns multiple instances of `HyperLiquidTopGun`, each running in its own daemon thread. Each bot instance:
- Has its own wallet (private key)
- Can have custom risk parameters (risk per trade, max leverage, stop loss distance)
- Polls the SQLite database for signals matching its `bot_id`
- Operates independently with its own logging context
- Runs in a continuous `run_loop()` with 2-second polling interval
- Daemon threads automatically terminate when main thread exits (Ctrl+C)

Configuration is in `FLEET_CONFIG` in `fleet_runner.py`. The `bot_id` must match the `bot_name` column in the signals database.

**Bot Aliases:** The `admin_controls.py` and `nuke_account.py` scripts support shortened aliases for easier CLI usage:
- "Apprentice" → "Apprentice Alchemist"
- "Sentient" → "SentientGuard"
- "Alpha" → "AlphaCryptoSignal"

**Thread Safety:** Each bot instance maintains its own SQLite connection. The database uses WAL mode (if enabled via `enable_wal.py`) for better concurrent access performance.

### Priority-Based Signal Processing

The `HyperLiquidTopGun` class processes signals with strict priority:

1. **Priority 1: Exit Signals** - Always processed first to prevent "ghost orders"
   - Cancel all open orders for the ticker (removes unfilled limit buys)
   - Market close the position
   - Validate API response before marking complete

2. **Priority 2: Entry Signals** - Only processed if no exits are pending
   - **Check max concurrent positions limit** (safety feature)
   - Calculate position size based on risk parameters
   - Apply leverage cap
   - Round price/size to Hyperliquid's precision requirements
   - Place limit entry + stop loss + optional take profit

This prevents race conditions where an exit signal arrives while processing an entry.

**Max Concurrent Positions**: Before processing any entry signal, the bot checks the current number of open positions. If the count equals or exceeds `MAX_CONCURRENT_POSITIONS` (default: 3), the entry signal is skipped with an error message. This safety feature prevents overexposure.

**Bot Execution Loop Flow:**
```
1. Check bot_controls table for PAUSE/RESUME/CLOSE_ALL commands
2. If PAUSED: sleep and continue
3. If CLOSE_ALL: execute emergency close on all positions
4. Query for exit signals (signal_type='exit', status='pending') → Process with Priority 1
5. Query for entry signals (signal_type='entry', status='pending') → Process with Priority 2
6. Sleep 2 seconds
7. Repeat
```

### Dynamic Precision System

Hyperliquid has strict rejection rules for price and size decimals. The system uses metadata-driven precision:

- **Size Rounding:** Uses `szDecimals` from Hyperliquid metadata (cached at initialization). Example: NEO=2 decimals, ETH=4 decimals.
- **Price Rounding:** `round_px(ticker, price)` applies two rules:
  1. Max 5 significant figures
  2. Max decimals = `6 - szDecimals` (for perps)
  - The stricter rule wins

This prevents "Invalid Size" and "Too many decimals" rejections.

### Risk Management System

Position sizing is based on:
- `RISK_PER_TRADE` - % of equity to risk (default 2%)
- `MAX_LEVERAGE` - Maximum allowed leverage (can be overridden per bot)
- `DEFAULT_SL_DIST` - Default stop loss distance if signal doesn't include one
- `MAX_CONCURRENT_POSITIONS` - Maximum open positions per wallet (default 3)

Formula: `size = (equity * risk_per_trade) / abs(entry_price - stop_loss)`

If calculated leverage exceeds `MAX_LEVERAGE`, the size is reduced.

**Safety Limits:**
1. **Concurrent Position Limit**: Before processing entry signals, the bot checks current open positions. If count >= `MAX_CONCURRENT_POSITIONS`, the entry is rejected to prevent overexposure.
2. **Leverage Cap**: Position size is reduced if calculated leverage would exceed `MAX_LEVERAGE`.
3. **Minimum Size Check**: Orders with calculated size <= 0 are rejected.

### External Dependencies

The signal ingestion logic lives **outside this repository**:

- **Signal Parser:** `/Users/johnny_main/Developer/projects/telegram_forwarder/telegram_signals_to_sqlite.py`
  - Contains `parse_aita_signal()` function (handles batch regex)
  - Has duplicate detection with 1hr buffer
  - Managed by launchd service: `com.telegram.signals`
- **Message Forwarder:** `/Users/johnny_main/Developer/projects/telegram_forwarder/telegram_forwarder.py`
  - Forwards messages from source channels to aggregation channel
  - Managed by launchd service: `com.telegram.forwarder`
- **Database:** `/Users/johnny_main/Developer/data/signals/signals.db`

**System Logs:** `/Users/johnny_main/Developer/data/logs/`
- `fleet_launchd.err` - Fleet runner execution logs (all bots)
- `telegram_signals_sqlite.log` - Parser stdout (signal ingestion)
- `telegram_signals_sqlite_error.log` - Parser stderr
- `telegram_forwarder.log` - Forwarder stdout
- `telegram_forwarder_error.log` - Forwarder stderr

**Service Management:**
```bash
# Check service status
launchctl list | grep telegram

# Restart services
launchctl unload ~/Library/LaunchAgents/com.telegram.signals.plist
launchctl load ~/Library/LaunchAgents/com.telegram.signals.plist

launchctl unload ~/Library/LaunchAgents/com.telegram.forwarder.plist
launchctl load ~/Library/LaunchAgents/com.telegram.forwarder.plist
```

When debugging "Missing Signals" or "Parsing Errors," you need to check the external repository and verify services are running.

## Database Schema

**Table:** `signals`

Key columns:
- `bot_name` - Links signal to specific bot instance (must match `bot_id` in fleet config)
- `symbol` - Clean ticker (e.g., "ETH", not "ETHUSDT")
- `signal_type` - `'entry'` or `'exit'`
- `status`:
  - `'pending'` - Waiting for processing
  - `'filled'` - Entry executed
  - `'executed'` - Exit executed
  - `'failed'` - Error occurred (see `notes` column)
- `direction` - `'long'`, `'short'`, `'bullish'`, `'bearish'`
- `entry_1`, `target_1`, `stop_loss` - Price levels
- `position_size_actual` - Calculated size after execution
- `notes` - Error messages for failed signals

**Table:** `bot_controls`

Used for admin commands (PAUSE, RESUME, CLOSE_ALL). The bot polls this table to check for control commands.

Key columns:
- `bot_name` - Target bot (or 'ALL' for fleet-wide commands)
- `command` - Control command (`'PAUSE'`, `'RESUME'`, `'CLOSE_ALL'`)
- `created_at` - Timestamp of command injection
- `executed` - Boolean flag (0 = pending, 1 = completed)

## Configuration

### Environment Variables (.env)

**CRITICAL:** The `.env` file contains actual testnet private keys. Never commit changes to `.env`.

- `PRIVATE_KEY_SENTIENT`, `PRIVATE_KEY_ALCHEMIST`, `PRIVATE_KEY_ALPHA` - Wallet keys for each bot
- `RISK_PER_TRADE` - % of equity to risk per trade (0.02 = 2%)
- `MAX_LEVERAGE` - Max allowed leverage (can be overridden per bot in fleet config)
- `DEFAULT_SL_DIST` - Default stop loss distance (0.05 = 5%)
- `MAX_CONCURRENT_POSITIONS` - Maximum open positions per wallet (default: 3) - Safety limit to prevent overexposure
- `IS_MAINNET` - `False` for testnet, `True` for mainnet

### Fleet Configuration

Edit `FLEET_CONFIG` in `fleet_runner.py` to:
- Add/remove bots
- Override risk parameters per bot
- Change bot_id (must match database `bot_name`)

## Code Modification Guidelines

### When Adding Features

1. **Metadata Loading:** The `meta` dictionary and `sz_decimals_map` are loaded once at initialization. If you need additional metadata fields, extract them in `__init__`.

2. **Precision Handling:** Always use `round_px()` for prices and round sizes to `get_token_sz_decimals()` before sending orders.

3. **API Response Validation:** Use `_check_order_status(result)` to validate all order responses. It handles `None` responses and extracts error messages from the nested response structure. The Hyperliquid API returns responses in the format:
   ```python
   {"status": "ok", "response": {"data": {...}}}  # Success
   {"status": "err", "response": "error message"}  # Failure
   ```

4. **Logging Context:** All log messages should include `[{self.bot_id}]` prefix for multi-bot clarity. All logs go to `/Users/johnny_main/Developer/data/logs/fleet_activity.log`.

5. **Database Transactions:** Always commit after updating signal status. Use try/except to mark signals as 'failed' with error notes.

### Common Pitfalls

- **Ghost Orders:** Exit signals must cancel open orders BEFORE closing positions, otherwise unfilled limit orders remain active.
- **Precision Rejections:** Never send raw float prices/sizes. Always apply rounding.
- **Leverage Overflow:** The system auto-reduces size if calculated leverage exceeds MAX_LEVERAGE, but you should log this clearly.
- **Signal Ticker Cleaning:** Tickers from DB may have "USDT" or "PERP" suffixes. Always clean with `.replace("USDT", "").replace("PERP", "")`.
- **Direction Parsing:** Accept both "long"/"short" and "bullish"/"bearish" for signal direction.

## Testing Approach

- `connection_test.py` - Verifies API connectivity and wallet access for all fleet bots
- `test_rejection.py` - Tests order placement to identify precision issues
- `check_db_status.py` - Pandas-based DB query tool for signal analysis
- `test_db_integration.py` - Full integration test (signal injection → processing)
- `test_controls.py` - Tests admin control commands
- `test_parser_regex.py` - Validates regex patterns for signal parsing

When testing, use the testnet (IS_MAINNET=False) to avoid risking real funds.

## Utility Scripts

### Analytics
- **`pnl_dashboard.py`** - Terminal-based PnL dashboard that queries signals.db and displays:
  - Per-bot performance metrics
  - Win/loss ratios
  - Return percentages extracted from signal notes
  - Uses pandas and colorama for formatted output

### Database Maintenance
- **`nuke_database.py`** - Destructive reset utility that:
  - Deletes all records from `signals` and `bot_controls` tables
  - Runs VACUUM to reclaim space
  - Optionally deletes all log files
  - Requires typing "NUKE" to confirm

- **`reset_id_counter.py`** - Resets SQLite auto-increment counter for clean ID sequences

- **`enable_wal.py`** - Enables WAL (Write-Ahead Logging) mode for SQLite to improve concurrent access performance
