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
python admin_controls.py ALL PAUSE          # Pause all bots (takes effect within 2 seconds)
python admin_controls.py "Alpha" RESUME     # Resume specific bot
python admin_controls.py "Sentient" PAUSE   # Pause specific bot (e.g., to use wallet manually)
```

**Pausing vs Removing a Bot:**
- **PAUSE command**: Bot threads stay alive but skip signal processing. Useful for temporary stops without service restart. Resume instantly with RESUME command.
- **Remove from fleet**: Comment out bot in `FLEET_CONFIG` in `fleet_runner.py`, then restart service. Use when permanently reassigning wallet to other purposes.
- **Comment out private key**: Comment `PRIVATE_KEY_X` in `.env`, then restart service. Bot will be skipped with warning log.
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
python test/test_update_filter.py    # Update message filter validation (10 test cases)

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

The system uses a **Fleet Runner** pattern where `fleet_runner.py` spawns multiple instances of `HyperLiquidTopGun`, each running in **three daemon threads per bot**:

1. **Signal Processing Thread** (`run_loop()`) - Polls database every 2 seconds for pending signals
2. **Fill Monitor Thread** (`run_fill_monitor()`) - Monitors Hyperliquid fills for TP/SL execution and breakeven logic
3. **Position Reconciliation Thread** (`run_position_reconciliation()`) - Syncs database state with actual Hyperliquid positions every 60 seconds

Each bot instance:
- Has its own wallet (private key)
- Can have custom risk parameters (risk per trade, max leverage, stop loss distance)
- Polls the SQLite database for signals matching its `bot_id`
- Operates independently with its own logging context
- All daemon threads automatically terminate when main thread exits (Ctrl+C)

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
   - **Price staleness check** (market order fallback if >2% stale)
   - Calculate position size based on risk parameters
   - Apply leverage cap
   - Round price/size to Hyperliquid's precision requirements
   - Place limit/market entry + stop loss + optional take profit

This prevents race conditions where an exit signal arrives while processing an entry.

### Price Staleness Detection

Before placing entry orders, the system compares the signal's entry price against current market price:

**Logic:**
1. Fetch current market price via `info.all_mids()`
2. Calculate distance: `abs(entry_px - current_px) / current_px`
3. If distance > 2%: Use **MARKET order** instead of limit order
4. If distance ≤ 2%: Use **LIMIT order** (normal behavior)

**Why This Matters:**
- Signals may arrive with prices from hours/days ago
- Placing a limit order at $69.36 when market is at $63.94 (8.5% away) will never fill
- Market order fallback ensures immediate execution at current price
- Stop loss is recalculated relative to current price to maintain proper risk

**Example Log:**
```
⚠️ Entry price stale (8.5% from market @ $63.94). Using MARKET order.
📊 Adjusted SL for market price: $57.55
🚀 Sending Order: LTC | Size: 0.5 | MARKET @ 63.94
```

**Status Behavior:**
- Market orders → status='filled' (immediate execution)
- Limit orders → status='sent' (awaiting fill confirmation)

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

### Position Reconciliation System (Auto-Healing)

The fleet includes an **automatic position reconciliation system** that runs every 60 seconds per bot to detect and fix "ghost positions" (database entries marked as `status='filled'` but no longer exist on Hyperliquid).

**How It Works:**
1. Queries database for all positions with `status='filled'` (considered "open")
2. Queries Hyperliquid API for actual open positions
3. Compares the two states
4. For any position in DB but NOT on Hyperliquid:
   - Marks as `status='closed'` in database
   - Attempts to retrieve PnL from recent fills (last 100 fills)
   - Logs the reconciliation with actual PnL if available

**Catches All Edge Cases:**
- System restarts (Fill Monitor missed events)
- Hyperliquid API outages (502 errors during Fill Monitor)
- Stop losses hit automatically (Hyperliquid closes position, not the bot)
- Take profits filled (same as above)
- Manual position closes on Hyperliquid UI
- Fill Monitor failures

**Location:** `hyperliquid_top_gun.py` lines 856-984
- `run_position_reconciliation()` - Main reconciliation loop
- `_get_pnl_from_fills()` - Helper to retrieve PnL from Hyperliquid fill history

**Logs:** Search for `👻 GHOST POSITION DETECTED` and `✅ Reconciled` in fleet logs.

**Self-Healing:** The system automatically corrects database drift within 60 seconds, regardless of root cause. This ensures the dashboard and MAX_CONCURRENT_POSITIONS checks stay accurate.

### Stale Order Auto-Cleanup (24h)

The reconciliation loop also cleans up unfilled limit orders older than 24 hours:

**How It Works:**
1. Queries database for signals with `status='sent'` older than 24 hours
2. Cancels entry order, stop loss, and any take profit orders on Hyperliquid
3. Updates signal status to `'expired'` with note

**Why This Matters:**
- Limit orders placed at stale prices may never fill
- Orphaned orders accumulate and clutter the order book
- Associated SL/TP orders consume margin even if entry never fills

**Location:** `hyperliquid_top_gun.py` method `_cleanup_stale_orders()`

**Logs:** Search for `🕐 STALE ORDER` and `Order expired after 24h` in fleet logs.

**Manual Cleanup:** Use `cleanup_stale_orders.py` for immediate cleanup without waiting for reconciliation cycle.

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
  - **Update Message Filter** (lines 302-350): Explicit filtering layer that rejects update/announcement messages BEFORE database insertion
    - Detects "Signal ID - [number]" format with date keywords
    - Filters configurable keywords: update!, achieved, alert, reminder, announcement
    - Prevents false positives by checking for proper signal structure first
    - Logs: `🚫 FILTERED UPDATE MESSAGE: [reason]`
    - Configurable via `.env`: `UPDATE_FILTER_KEYWORDS`, `LOG_FILTERED_MESSAGES`
  - Contains `parse_aita_signal()` and `parse_alpha_crypto_signal()` functions (handles batch regex)
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
  - `'processing'` - Locked for processing (prevents duplicate handling)
  - `'sent'` - Orders placed, awaiting fill (limit orders only)
  - `'filled'` - Entry executed (position currently open)
  - `'closed'` - Position closed (by TP/SL hit, manual close, or reconciliation)
  - `'executed'` - Exit executed (for exit signals)
  - `'expired'` - Order auto-cancelled after 24h without fill
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
- `test_update_filter.py` - Validates update message filtering (10 test cases covering both filtering and non-filtering scenarios)

When testing, use the testnet (IS_MAINNET=False) to avoid risking real funds.

## Utility Scripts

### Analytics
- **`pnl_dashboard.py`** - Terminal-based PnL dashboard that queries signals.db and displays:
  - Per-bot performance metrics (closed trades only)
  - Win/loss ratios calculated from actual Hyperliquid PnL
  - Telegram signal provider PnL vs. actual bot execution PnL comparison
  - Active open positions with entry prices and sizes
  - Includes both exit signals AND auto-closed positions (status='closed')
  - Uses pandas and colorama for formatted output

### Database Maintenance
- **`nuke_database.py`** - Destructive reset utility that:
  - Deletes all records from `signals` and `bot_controls` tables
  - Runs VACUUM to reclaim space
  - Optionally deletes all log files
  - Requires typing "NUKE" to confirm

- **`reset_id_counter.py`** - Resets SQLite auto-increment counter for clean ID sequences

- **`enable_wal.py`** - Enables WAL (Write-Ahead Logging) mode for SQLite to improve concurrent access performance

### Order Cleanup
- **`cleanup_stale_orders.py`** - Immediate cleanup of unfilled orders without waiting for reconciliation:
  ```bash
  python cleanup_stale_orders.py              # Clean up enabled wallets
  python cleanup_stale_orders.py --all        # Include disabled wallets
  python cleanup_stale_orders.py --hours 48   # Custom staleness threshold
  python cleanup_stale_orders.py --dry-run    # Report only, no changes
  ```
  - Cancels entry/SL/TP orders older than threshold
  - Shows orphaned orders on Hyperliquid not tracked in database
  - Updates signal status to 'expired'
