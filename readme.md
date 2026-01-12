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

## 📍 External Dependencies & Paths

**⚠️ CRITICAL CONTEXT:**
The signal ingestion logic lives **outside** this repository. If debugging "Missing Signals" or "Parsing Errors," references must be made to the following paths.

### 1. Signal Ingestion (The "Listener")
Parses raw Telegram text into structured SQL rows. Handles Regex for Entries/Exits and Batch Messages.
* **Path:** `/Users/johnny_main/Developer/projects/telegram_forwarder/telegram_signals_to_sqlite.py`
* **Key Functions:** `parse_aita_signal` (Batch regex), `is_duplicate` (1hr buffer).

### 2. Message Forwarder (The "Bouncer")
Aggregates signals from multiple source channels into a single target channel.
* **Path:** `/Users/johnny_main/Developer/projects/telegram_forwarder/telegram_forwarder.py`

### 3. Data & Logs (Shared Resources)
* **Database:** `/Users/johnny_main/Developer/data/signals/signals.db`
* **Logs Directory:** `/Users/johnny_main/Developer/data/logs/`
    * `fleet_activity.log` (Execution logs from this repo)
    * `telegram_signals_sqlite.log` (Parsing logs from external repo)

---

## 📂 Repository Structure (Execution Side)

| File | Purpose |
| :--- | :--- |
| **`fleet_runner.py`** | **The Manager.** Spawns instances of `HyperLiquidTopGun` for each active bot config. Handles process lifecycle and logging. |
| **`hyperliquid_top_gun.py`** | **The Pilot.** Core trading logic class. <br>- **Priority 1:** Process Exits (Cancel & Close).<br>- **Priority 2:** Process Entries (Risk Calc, Dynamic Precision). |
| **`admin_controls.py`** | CLI tool to query the DB (`POSITIONS`, `ORDERS`) and inject control commands (`PAUSE`, `RESUME`). |
| **`nuke_account.py`** | Emergency script. Performs a Market Close on all positions and cancels all open orders for a specific bot. |

---

## ⚙️ Core Logic & Protocols

### A. The "Cancel & Close" Protocol (Exits)
When an **Exit Signal** is received, the bot performs a specific sequence to prevent "ghost orders":
1.  **Cancel Open Orders** for that ticker *first* (removes unfilled Limit Buys).
2.  **Market Close** the position.
3.  **Validate Receipt:** Checks API response for errors before marking as complete.

### B. Dynamic Precision (Meme Coin Support)
Hyperliquid has strict rejection rules for Price and Size.
* **Size Rounding:** Uses metadata `szDecimals` (e.g., NEO=2, ETH=4).
* **Price Rounding:** Uses `round_px(ticker, price)` helper.
    * Rule 1: Max 5 Significant Figures.
    * Rule 2: Max Decimals allowed by metadata.

### C. Database Schema (`signals.db`)
**Table:** `signals`
* `id` (PK)
* `bot_name` (Text): Links signal to specific bot instance.
* `symbol` (Text): Clean ticker (e.g., "ETH").
* `signal_type` (Text): `'entry'` or `'exit'`.
* `status` (Text):
    * `'pending'`: Waiting for Fleet Runner.
    * `'filled'`: Entry Executed.
    * `'executed'`: Exit Executed.
    * `'failed'`: Error (see `notes` column).

---

## 🚀 Operational Commands

### Start the Fleet
```bash
python fleet_runner.py