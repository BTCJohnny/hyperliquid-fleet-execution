# Database Schema Contract

## Overview

This document defines the schema contract between the signal ingestion layer ([telegram_forwarder](https://github.com/BTCJohnny/telegram_forwarder)) and execution layer (hyperliquid-fleet-execution). Any changes to this schema must be coordinated between both repositories.

**Integration Point:** SQLite database serves as the API contract between loosely coupled services.

## Table: signals

### Core Columns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | NOT NULL | Auto | Auto-increment primary key |
| `symbol` | TEXT | NOT NULL | - | Ticker symbol (e.g., "ETH", "BTC") |
| `direction` | TEXT | - | 'long' | Trade direction: 'long', 'short', 'bullish', 'bearish' |
| `signal_type` | TEXT | - | 'setup' | Signal type: 'entry' or 'exit' |
| `bot_name` | TEXT | - | - | Bot identifier (routes to specific wallet) |
| `status` | TEXT | - | 'pending' | Signal status (see Status Workflow below) |
| `created_at` | TIMESTAMP | - | CURRENT_TIMESTAMP | Signal creation time |

### Price Levels

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `entry_1` | REAL | Yes | Entry price |
| `entry_2` | REAL | Yes | Alternative entry price (rarely used) |
| `entry_3` | REAL | Yes | Alternative entry price (rarely used) |
| `target_1` | REAL | Yes | Take profit target 1 (25% of position) |
| `target_2` | REAL | Yes | Take profit target 2 (25% of position) |
| `target_3` | REAL | Yes | Take profit target 3 (25% of position) |
| `target_4` | REAL | Yes | Take profit target 4 (25% of position) |
| `target_5` | REAL | Yes | Take profit target 5 (remaining position) |
| `stop_loss` | REAL | Yes | Stop loss price |

**Notes:**
- Position is split equally across all non-null targets
- If 4 targets exist: TP1=25%, TP2=25%, TP3=25%, TP4=25%
- Last TP gets remainder to handle rounding errors

### Order Tracking (Added 2026-01-12)

These columns store Hyperliquid order IDs for correlation with fill events.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `order_id_entry` | INTEGER | Yes | Hyperliquid entry order ID |
| `order_id_sl` | INTEGER | Yes | Hyperliquid stop loss order ID |
| `order_id_tp1` | INTEGER | Yes | Hyperliquid TP1 order ID |
| `order_id_tp2` | INTEGER | Yes | Hyperliquid TP2 order ID |
| `order_id_tp3` | INTEGER | Yes | Hyperliquid TP3 order ID |
| `order_id_tp4` | INTEGER | Yes | Hyperliquid TP4 order ID |
| `order_id_tp5` | INTEGER | Yes | Hyperliquid TP5 order ID |

**Important:** Hyperliquid resets order IDs monthly on the 1st of each month. Always filter by `created_at > datetime('now', '-30 days')` when matching fills to signals.

### Fill Timestamps (Added 2026-01-12)

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `entry_filled_at` | TEXT | Yes | ISO timestamp when entry order filled |
| `tp1_filled_at` | TEXT | Yes | ISO timestamp when TP1 filled |
| `tp2_filled_at` | TEXT | Yes | ISO timestamp when TP2 filled |
| `tp3_filled_at` | TEXT | Yes | ISO timestamp when TP3 filled |
| `tp4_filled_at` | TEXT | Yes | ISO timestamp when TP4 filled |
| `tp5_filled_at` | TEXT | Yes | ISO timestamp when TP5 filled |

**Format:** ISO 8601 format (e.g., "2026-01-12T14:30:45")

### Breakeven Tracking (Added 2026-01-12)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `sl_moved_to_be` | BOOLEAN | - | 0 | Flag: Has SL been moved to breakeven? |
| `be_sl_order_id` | INTEGER | Yes | - | New SL order ID after breakeven |

**Breakeven Logic:**
- When TP1 fills, `sl_moved_to_be` is set to 1 (TRUE)
- Original SL is cancelled
- New SL placed at entry price (breakeven)
- `be_sl_order_id` stores the new SL order ID

### Additional Columns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `leverage` | INTEGER | Yes | 1 | Leverage multiplier (informational only) |
| `position_size_actual` | REAL | Yes | - | Actual position size executed (in coins) |
| `notes` | TEXT | Yes | - | Error messages or additional info |
| `raw_message` | TEXT | Yes | - | Original signal text from Telegram |
| `provider` | TEXT | Yes | - | Signal source (e.g., 'AlphaCrypto', 'AITA') |
| `confidence_score` | INTEGER | Yes | - | Signal confidence (1-5, from parser) |
| `pnl_percent` | REAL | Yes | - | Profit/Loss percentage (for exit signals) |
| `position_size_actual` | REAL | Yes | - | Actual position size executed (in coins) |
| `leverage` | INTEGER | Yes | 1 | Leverage multiplier |
| `market_type` | TEXT | Yes | 'perp' | Market type (spot, futures, perp) |

### Additional Metadata

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `notes` | TEXT | Yes | Error messages or additional info |
| `raw_message` | TEXT | Yes | Original signal text from Telegram |
| `provider` | TEXT | Yes | Signal source (e.g., 'AlphaCrypto', 'AITA') |
| `source` | TEXT | Yes | Source system (e.g., 'telegram') |
| `confidence_score` | REAL | Yes | Signal confidence (0.0-1.0) |
| `position_size_actual` | REAL | Yes | Actual position size executed (in coin units) |
| `leverage` | INTEGER | Yes | Leverage multiplier |
| `market_type` | TEXT | Yes | Market type (e.g., 'spot', 'futures', 'perp') |
| `pnl_percent` | REAL | Yes | Profit/loss percentage for exit signals |

### Breakeven Tracking (Added 2026-01-12)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `sl_moved_to_be` | BOOLEAN | No | 0 | Flag: Has SL been moved to breakeven? |
| `be_sl_order_id` | INTEGER | Yes | - | New SL order ID after breakeven |

**Usage:** When TP1 fills, `sl_moved_to_be` is set to `1` and original SL is replaced with new SL at entry price.

### Additional Columns

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `leverage` | INTEGER | Yes | Leverage multiplier (e.g., 5, 10, 20) |
| `position_size_actual` | REAL | Yes | Actual position size executed (in base currency) |
| `notes` | TEXT | Yes | Error messages or additional info |
| `raw_message` | TEXT | Yes | Original signal text from Telegram |
| `provider` | TEXT | Yes | Signal source (e.g., 'AITA', 'AlphaCrypto') |
| `confidence_score` | TEXT | Yes | Signal confidence (e.g., "3/5", "5/5") |
| `market_type` | TEXT | Yes | 'spot' or 'futures' (default: 'spot') |
| `pnl_percent` | REAL | Yes | Profit/loss percentage (for exit signals) |

---

## Status Workflow

### Ingestion Layer (telegram_forwarder)

```
Signal received → Parse → INSERT with status='pending'
```

### Execution Layer (hyperliquid-fleet-execution)

**Entry Signal Flow:**
```
'pending' → (calculate size, place orders) → 'filled' → (TP/SL trigger) → 'executed'
                                           ↓ (if error)
                                        'failed' (with error notes)
```

**Exit Signal Flow:**
```
'pending' → (cancel orders + close position) → 'executed'
                                             ↓ (if error)
                                          'failed' (with error notes)
```

**Status Definitions:**
- `pending` - Signal waiting for execution
- `filled` - Entry orders placed successfully, position open
- `executed` - Exit completed or all TPs/SL hit
- `failed` - Error during execution (see `notes` column)

---

## Bot Name Routing

The `bot_name` column determines which wallet executes the signal.

| bot_name | Wallet | Risk Profile | Max Leverage |
|----------|--------|--------------|--------------|
| `Apprentice Alchemist` | PRIVATE_KEY_ALCHEMIST | Conservative | 1.0x |
| `SentientGuard` | PRIVATE_KEY_SENTIENT | Conservative | 1.0x |
| `AlphaCryptoSignal` | PRIVATE_KEY_ALPHA | Aggressive | 20.0x |

**Integration Requirement:**
- Signal parser must populate `bot_name` correctly based on Telegram channel source
- Execution layer filters signals WHERE `bot_name = ?`
- Each bot processes only its assigned signals

---

## Schema Migration Guide

### Adding New Columns

**Process:**
1. Update this document with new column specification
2. Run `ALTER TABLE` migration in database:
   ```sql
   ALTER TABLE signals ADD COLUMN new_column_name TYPE DEFAULT value;
   ```
3. Update ingestion layer to populate new column (if applicable)
4. Update execution layer to consume new column (if applicable)
5. Test end-to-end with sample signal

**Example Migration:**
```sql
-- Add new column
ALTER TABLE signals ADD COLUMN trailing_stop_enabled BOOLEAN DEFAULT 0;

-- Verify
PRAGMA table_info(signals);
```

### Breaking Changes

If a change breaks backward compatibility:
1. Create a migration script in both repos
2. Coordinate deployment timing
3. Test with feature flag if possible
4. Document in both repositories

**Example Breaking Change:**
- Renaming `target_1` to `tp1` would require coordinated update
- Better approach: Add new column, populate both, migrate, then drop old column

---

## Database Configuration

### Location

Default: `/Users/johnny_main/Developer/data/signals/signals.db`

Configurable via signal parser. Execution layer expects database at this path or path specified in configuration.

### WAL Mode (Write-Ahead Logging)

**Purpose:** Enables concurrent reads while writing

**Enable WAL:**
```bash
python enable_wal.py
```

**Verification:**
```bash
sqlite3 /path/to/signals.db "PRAGMA journal_mode;"
# Should output: wal
```

**WAL Files:**
- `.db-shm` - Shared memory index
- `.db-wal` - Write-ahead log

**Cleanup:**
```sql
-- Force checkpoint (writes WAL to main DB)
PRAGMA wal_checkpoint(TRUNCATE);
```

### Indexing (Recommended)

For optimal performance, create indexes on frequently queried columns:

```sql
-- Index for signal processing queries
CREATE INDEX idx_status_botname ON signals(status, bot_name);

-- Index for fill matching queries
CREATE INDEX idx_order_ids ON signals(order_id_tp1, order_id_tp2, order_id_tp3, order_id_tp4, order_id_tp5);

-- Index for date filtering
CREATE INDEX idx_created_at ON signals(created_at);
```

---

## Example Queries

### Ingestion Layer - Insert Signal

```sql
INSERT INTO signals (
    symbol, direction, entry_1, target_1, target_2, target_3, target_4, target_5,
    stop_loss, signal_type, bot_name, status, leverage, provider, raw_message
) VALUES (
    'ETH',           -- symbol
    'long',          -- direction
    3000.0,          -- entry_1
    3100.0,          -- target_1
    3200.0,          -- target_2
    3300.0,          -- target_3
    3400.0,          -- target_4
    3500.0,          -- target_5
    2900.0,          -- stop_loss
    'entry',         -- signal_type
    'AlphaCryptoSignal',  -- bot_name
    'pending',       -- status
    10,              -- leverage
    'AlphaCrypto',   -- provider
    '🔥 ETH LONG Entry: 3000...'  -- raw_message
);
```

### Execution Layer - Poll for Pending Signals

```sql
SELECT id, symbol, direction, entry_1, target_1, target_2, target_3, target_4, target_5, stop_loss, leverage
FROM signals
WHERE bot_name = 'AlphaCryptoSignal'
  AND status = 'pending'
  AND signal_type = 'entry'
ORDER BY created_at ASC
LIMIT 1;
```

### Execution Layer - Update After Entry Fill

```sql
UPDATE signals
SET status = 'filled',
    position_size_actual = 100.5,
    order_id_entry = 123456,
    order_id_sl = 123457,
    order_id_tp1 = 123458,
    order_id_tp2 = 123459,
    order_id_tp3 = 123460,
    order_id_tp4 = 123461,
    entry_filled_at = '2026-01-12T11:30:00'
WHERE id = 42;
```

### Execution Layer - Match Fill to Signal (with 30-day filter)

**Critical: Must include time filter to handle monthly OID reset**

```sql
SELECT id, direction, entry_1, order_id_sl, sl_moved_to_be, position_size_actual
FROM signals
WHERE bot_name = ?
  AND (order_id_tp1 = ? OR order_id_tp2 = ? OR order_id_tp3 = ? OR order_id_tp4 = ? OR order_id_tp5 = ?)
  AND status = 'filled'
  AND datetime(created_at) > datetime('now', '-30 days')
LIMIT 1;
```

### Execution Layer - Mark Signal as Failed

```sql
UPDATE signals
SET status = 'failed',
    notes = 'Order rejected: Invalid size (too many decimals)'
WHERE id = 42;
```

---

## Testing Queries

### View Recent Pending Signals

```sql
SELECT id, bot_name, symbol, direction, signal_type, status, created_at
FROM signals
WHERE status = 'pending'
ORDER BY created_at DESC
LIMIT 10;
```

### Check Bot Activity

```sql
SELECT bot_name, status, COUNT(*) as count
FROM signals
WHERE datetime(created_at) > datetime('now', '-1 day')
GROUP BY bot_name, status;
```

### Find Failed Signals with Errors

```sql
SELECT id, bot_name, symbol, status, notes, created_at
FROM signals
WHERE status = 'failed'
  AND notes IS NOT NULL
ORDER BY created_at DESC
LIMIT 20;
```

### Check Breakeven Triggers

```sql
SELECT id, bot_name, symbol, sl_moved_to_be, tp1_filled_at, be_sl_order_id
FROM signals
WHERE sl_moved_to_be = 1
ORDER BY created_at DESC
LIMIT 10;
```

---

## Version History

| Version | Date | Changes | Repos Affected |
|---------|------|---------|----------------|
| 1.0 | 2024-XX-XX | Initial schema | Both |
| 1.1 | 2026-01-09 | Added `target_2-5` for multi-TP support | Both |
| 1.2 | 2026-01-12 | Added order tracking and breakeven columns | Execution only |

**Current Version:** 1.2

---

## Database Backup Strategy

### Recommended Backups

1. **Before Schema Migration:**
   ```bash
   cp signals.db signals.db.backup.$(date +%Y%m%d_%H%M%S)
   ```

2. **Daily Backups (Automated):**
   ```bash
   # Add to cron
   0 2 * * * cp /path/to/signals.db /backups/signals.db.$(date +\%Y\%m\%d)
   ```

3. **Before Major Updates:**
   ```bash
   # Checkpoint WAL, then backup
   sqlite3 signals.db "PRAGMA wal_checkpoint(TRUNCATE);"
   tar -czf signals_backup_$(date +%Y%m%d).tar.gz signals.db*
   ```

### Restore from Backup

```bash
# Stop both services first
# Replace database
cp signals.db.backup.20260112 signals.db
# Restart services
```

---

## Troubleshooting

### Database Locked Errors

**Symptoms:** `sqlite3.OperationalError: database is locked`

**Causes:**
- Not using WAL mode
- Timeout too short
- Concurrent writes without proper handling

**Solutions:**
1. Enable WAL mode: `python enable_wal.py`
2. Increase timeout: `sqlite3.connect(db_path, timeout=10)`
3. Verify no hanging connections

### Missing Signals

**Symptoms:** Signals in database but not processed

**Diagnosis:**
```sql
SELECT bot_name, status, COUNT(*)
FROM signals
WHERE datetime(created_at) > datetime('now', '-1 hour')
GROUP BY bot_name, status;
```

**Common Causes:**
- `bot_name` mismatch between parser and fleet config
- Status stuck in 'pending' (check execution logs)
- Fleet not running

### Fill Not Detected

**Symptoms:** TP filled on Hyperliquid but breakeven not triggered

**Diagnosis:**
```sql
SELECT id, order_id_tp1, tp1_filled_at, sl_moved_to_be
FROM signals
WHERE bot_name = 'AlphaCryptoSignal'
  AND status = 'filled'
  AND sl_moved_to_be = 0
ORDER BY created_at DESC
LIMIT 5;
```

**Common Causes:**
- Order ID mismatch (monthly reset without time filter)
- Fill monitor thread crashed (check logs)
- API returned empty fills array

---

## Contact and Coordination

When making schema changes, coordinate between repositories:

1. **Create Issue:** Open issue in both repos describing change
2. **Update Docs:** Update DATABASE_SCHEMA.md in both repos
3. **Test Migration:** Test on dev database first
4. **Deploy:** Coordinate deployment timing
5. **Verify:** Test end-to-end after deployment

**Related Repositories:**
- Signal Ingestion: https://github.com/BTCJohnny/telegram_forwarder
- Execution Layer: https://github.com/BTCJohnny/hyperliquid-fleet-execution
