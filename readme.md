# 🤖 Hyperliquid "Top Gun" Trading Fleet

**System Role:** Automated Execution Engine for Telegram-based Trading Signals.
**Context:** This repository handles the *execution* phase of a pipeline that forwards, parses, and executes crypto trading signals on Hyperliquid (Testnet/Mainnet).

---

## 🗺️ System Architecture

The system operates as a unidirectional pipeline:

1.  **Source:** Telegram Channels (Signal Providers).
2.  **Ingestion (External):** Signals are parsed and saved to a centralized SQLite database.
3.  **Execution (This Repo):** A "Fleet Runner" polls the DB and dispatches orders via `HyperLiquidTopGun`.

### 🔄 Data Flow
`Telegram` -> `Forwarder` -> `Ingester` -> `SQLite DB` -> `Fleet Runner` -> `Hyperliquid API`

---

## 📍 Integration with Signal Ingestion

**⚠️ CRITICAL CONTEXT:**
This execution layer consumes signals from an external ingestion system. The repositories are **separate and independent**, integrated via a shared SQLite database.

### Signal Source Repository

**GitHub:** [BTCJohnny/telegram_forwarder](https://github.com/BTCJohnny/telegram_forwarder)

This repository handles:
- Forwarding Telegram signals from multiple channels
- Parsing signal text into structured data
- Writing to SQLite database with `status='pending'`

### Database Contract

**Location:** `/Users/johnny_main/Developer/data/signals/signals.db`
**Table:** `signals`
**Schema Documentation:** See [docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md)

**Key Integration Points:**
- `bot_name` - Routes signal to specific execution bot
- `status` - Lifecycle: `'pending'` → `'filled'` → `'executed'`
- `order_id_entry`, `order_id_sl`, `order_id_tp1-5` - Hyperliquid order IDs (filled by this layer)

### Signal Flow

```
Telegram Channel → Forwarder → Parser → signals.db (status='pending')
                                              ↓
                        This Layer polls for 'pending' signals
                                              ↓
                        Places orders on Hyperliquid DEX
                                              ↓
                        Updates status to 'filled' / 'executed'
```

### Logs Directory

* **Shared Location:** `/Users/johnny_main/Developer/data/logs/`
    * `fleet_activity.log` - Execution logs (this repo)
    * `telegram_signals_sqlite.log` - Parsing logs (external repo)

---

## ✨ Features

- **Multi-Bot Fleet Orchestration** - Run 3+ bots concurrently with independent risk profiles
- **Risk-Managed Position Sizing** - Configurable per-trade risk, leverage caps, and maximum positions
- **Multiple Take Profit Targets** - Partial position closes at TP1-5 with customizable split
- **Breakeven Stop Loss** - Automatically moves SL to entry price after TP1 hits (eliminates downside risk)
- **Fill Monitoring System** - Background threads detect fills and trigger reactive strategies
- **Database-Driven Architecture** - SQLite-based signal queue with WAL mode for concurrency
- **Dynamic Precision Handling** - Adapts to Hyperliquid's per-asset rounding requirements
- **Admin CLI Tools** - Query positions, orders, and control bot behavior
- **Emergency Controls** - Quickly close all positions and cancel orders

## 📂 Repository Structure

| File | Purpose |
| :--- | :--- |
| **`fleet_runner.py`** | **Fleet Manager.** Spawns 2 threads per bot (signal processing + fill monitoring). |
| **`hyperliquid_top_gun.py`** | **Core Engine.** Trading logic, order placement, breakeven automation. |
| **`admin_controls.py`** | **CLI Tool.** Query DB (`STATUS`, `POSITIONS`, `ORDERS`) and control bots (`PAUSE`, `RESUME`). |
| **`nuke_account.py`** | **Emergency Kill Switch.** Market close all positions + cancel all orders. |
| **`pnl_dashboard.py`** | **PnL Reporter.** View profit/loss across all bots. |
| **`enable_wal.py`** | **DB Setup.** Enable SQLite WAL mode for concurrent access. |
| **`test/`** | **Test Suite.** Connection tests, DB integration tests, rejection tests. |

## 📚 Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Comprehensive system design and threading model
- **[docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md)** - Complete database schema contract
- **[MONITORING.md](MONITORING.md)** - Observability and debugging guide
- **[CLAUDE.md](CLAUDE.md)** - AI assistant guidance for code modifications

---

## 🛠️ Installation

### Prerequisites

- Python 3.8+
- Signal ingestion layer running ([telegram_forwarder](https://github.com/BTCJohnny/telegram_forwarder))
- SQLite database with signals table

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/BTCJohnny/hyperliquid-fleet-execution.git
   cd hyperliquid-fleet-execution
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env and add your wallet private keys
   ```

4. **Enable WAL mode on database:**
   ```bash
   python enable_wal.py
   ```

5. **Test connectivity:**
   ```bash
   python test/connection_test.py
   ```

### Configuration

Edit `.env` file:

```bash
# Wallet Private Keys (NEVER COMMIT THIS FILE)
PRIVATE_KEY_SENTIENT=0x...
PRIVATE_KEY_ALCHEMIST=0x...
PRIVATE_KEY_ALPHA=0x...

# Risk Management
RISK_PER_TRADE=0.02           # 2% per trade
MAX_LEVERAGE=1.0              # Maximum leverage
DEFAULT_SL_DIST=0.05          # 5% default stop loss
MAX_CONCURRENT_POSITIONS=3    # Max positions per wallet

# Features
ENABLE_BREAKEVEN_SL=True      # Move SL to breakeven after TP1

# Network
IS_MAINNET=False              # Use testnet
```

**Per-Bot Overrides:**
Edit `FLEET_CONFIG` in `fleet_runner.py` to customize risk per bot:

```python
{
    "bot_id": "AlphaCryptoSignal",
    "private_key": os.getenv("PRIVATE_KEY_ALPHA"),
    "risk_per_trade": 0.02,
    "max_leverage": 20.0,  # OVERRIDE: Higher leverage for this bot
    "default_sl_dist": 0.02
}
```

---

## ⚙️ Core Logic & Protocols

### A. Threading Model

Each bot runs **2 daemon threads**:

1. **Signal Processing Thread** (`{bot_id}-signal`)
   - Polls database every 2 seconds for `status='pending'`
   - Priority 1: Exit signals (cancel orders + close position)
   - Priority 2: Entry signals (calculate size + place orders)
   - Updates signal status after execution

2. **Fill Monitor Thread** (`{bot_id}-monitor`)
   - Polls Hyperliquid `user_fills()` API every 10 seconds
   - Detects when TP orders are filled
   - Triggers breakeven stop loss when TP1 hits
   - Tracks fills with 30-day window (handles monthly order ID reset)

### B. Breakeven Stop Loss (New Feature)

When TP1 fills, the system automatically:
1. Cancels original stop loss order
2. Calculates remaining position size (75% if 4 TPs)
3. Places new SL at entry price (breakeven)
4. Updates database with `sl_moved_to_be=1` and new SL order ID

**Result:** Eliminates downside risk while preserving upside potential on remaining 75% of position.

### C. The "Cancel & Close" Protocol (Exits)

When an **Exit Signal** is received:
1. **Cancel Open Orders** for that ticker *first* (removes unfilled limit buys)
2. **Market Close** the position
3. **Validate Receipt:** Check API response for errors before marking complete

### D. Dynamic Precision (Meme Coin Support)

Hyperliquid has strict rejection rules for Price and Size:
* **Size Rounding:** Uses metadata `szDecimals` (e.g., NEO=2, ETH=4)
* **Price Rounding:** Uses `round_px(ticker, price)` helper
    * Rule 1: Max 5 Significant Figures
    * Rule 2: Max Decimals = `6 - szDecimals`
    * Stricter rule wins

### E. Risk-Managed Position Sizing

**Formula:**
```
size = (equity * risk_per_trade) / abs(entry_price - stop_loss)
```

**Leverage Cap Enforcement:**
```
if actual_leverage > max_leverage:
    size = size * (max_leverage / actual_leverage)
```

**Maximum Positions:**
- Entry signals skipped if `MAX_CONCURRENT_POSITIONS` reached
- Prevents overexposure

### F. Monthly Order ID Reset Handling

**Challenge:** Hyperliquid resets order IDs on the 1st of each month.

**Solution:** All fill-matching queries include:
```sql
WHERE datetime(created_at) > datetime('now', '-30 days')
```

This prevents false matches across month boundaries.

---

## 🚀 Operational Commands

### Start the Fleet
```bash
python fleet_runner.py