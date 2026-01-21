"""
CONTEXT_FOR_LLM_INGESTION:
--------------------------------------------------------------------------------
SYSTEM ROLE:
Core Trading Engine (The "Top Gun" Pilot).

UPDATES (Final V5 - Production Candidate):
- Fix: 'Cancel & Close' logic prevents ghost orders.
- Fix: Dynamic Size Rounding (szDecimals lookup) prevents 'Invalid Size'.
- Fix: Dynamic Price Rounding (Sig Figs + Decimals) prevents 'Too many decimals'.
- Fix: Graceful handling of 'None' responses from API.
--------------------------------------------------------------------------------
"""

import time
import logging
import os
import sqlite3
import math
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

class HyperLiquidTopGun:
    def __init__(self, bot_id, private_key, risk_per_trade=None, max_leverage=None, default_sl_dist=None, max_concurrent_positions=None):
        self.bot_id = bot_id
        self.db_path = "/Users/johnny_main/Developer/data/signals/signals.db"

        # --- CONFIGURATION ---
        env_risk = os.getenv("RISK_PER_TRADE")
        self.risk_per_trade = risk_per_trade if risk_per_trade is not None else (float(env_risk) if env_risk else 0.01)

        env_lev = os.getenv("MAX_LEVERAGE")
        self.max_leverage = max_leverage if max_leverage is not None else (float(env_lev) if env_lev else 5.0)

        env_sl = os.getenv("DEFAULT_SL_DIST")
        self.default_sl_dist = default_sl_dist if default_sl_dist is not None else (float(env_sl) if env_sl else 0.05)

        env_max_pos = os.getenv("MAX_CONCURRENT_POSITIONS")
        self.max_concurrent_positions = max_concurrent_positions if max_concurrent_positions is not None else (int(env_max_pos) if env_max_pos else 3)
        
        # --- CONNECTION & METADATA ---
        try:
            self.account = Account.from_key(private_key)
            is_mainnet = os.getenv("IS_MAINNET") == "True"
            node_url = constants.MAINNET_API_URL if is_mainnet else constants.TESTNET_API_URL
            
            logging.info(f"[{self.bot_id}] Connecting... (Risk: {self.risk_per_trade*100}%, Max Lev: {self.max_leverage}x, Max Positions: {self.max_concurrent_positions})")
            
            self.info = Info(node_url, skip_ws=True)
            self.exchange = Exchange(self.account, node_url)
            
            # --- METADATA CACHE (CRITICAL FOR PRECISION) ---
            self.meta = self.info.meta()
            self.sz_decimals_map = {
                asset['name']: asset['szDecimals'] 
                for asset in self.meta['universe']
            }
            logging.info(f"[{self.bot_id}] Loaded precision data for {len(self.sz_decimals_map)} assets.")
            logging.info(f"[{self.bot_id}] Online. Wallet: {self.account.address[:6]}...")
            
        except Exception as e:
            logging.error(f"[{self.bot_id}] ❌ Init Failed: {e}")
            raise e

    def get_token_sz_decimals(self, ticker):
        """Returns the allowed SIZE decimals for a token (e.g. 3)."""
        return self.sz_decimals_map.get(ticker, 3)

    def round_px(self, ticker, price):
        """
        Rounds price according to Hyperliquid's strict rules:
        1. Max 5 Significant Figures.
        2. Max Decimals = 6 - szDecimals (for Perps).
        """
        if price == 0: return 0.0
        
        try:
            # Rule 1: Max 5 Significant Figures
            magnitude = math.floor(math.log10(abs(price)))
            sig_figs_decimals = 5 - 1 - magnitude
            
            # Rule 2: Max Decimals allowed by Hyperliquid Metadata
            sz_decimals = self.get_token_sz_decimals(ticker)
            max_decimals = 6 - sz_decimals
            
            # The stricter of the two rules wins
            final_decimals = min(sig_figs_decimals, max_decimals)
            
            # If allowed decimals < 0 (e.g. price must be 10, 20), round to integer
            if final_decimals < 0:
                 return round(price, final_decimals)
                 
            return round(price, final_decimals)
            
        except Exception:
            return price

    def _check_order_status(self, result):
        """Parses API receipt. Ignores 'None' (success). Throws on 'error'."""
        if result is None: return

        if result['status'] == 'err':
            raise ValueError(f"API Error: {result['response']}")
        
        try:
            statuses = result['response']['data']['statuses']
            if not statuses: return
            
            first_status = statuses[0]
            if 'error' in first_status:
                raise ValueError(f"Order Rejected: {first_status['error']}")
            return
        except KeyError:
            return

    def _extract_order_id(self, result):
        """
        Extract order ID from Hyperliquid API response.
        Returns None if order wasn't placed or response is malformed.
        """
        if result is None:
            return None

        try:
            statuses = result['response']['data']['statuses']
            if not statuses:
                return None

            first_status = statuses[0]

            # Check for resting order (limit orders)
            if 'resting' in first_status:
                return first_status['resting'].get('oid')

            # Check for filled order (market orders)
            if 'filled' in first_status:
                return first_status['filled'].get('oid')

            return None
        except (KeyError, IndexError, TypeError):
            return None

    def run_loop(self):
        logging.info(f"[{self.bot_id}] Starting Database Poll Loop...")
        conn = sqlite3.connect(self.db_path)
        
        while True:
            try:
                c = conn.cursor()

                # ==========================================================
                # 🛑 PRIORITY 1: CHECK FOR EXITS
                # ==========================================================
                query_exit = """
                    SELECT id, symbol 
                    FROM signals 
                    WHERE bot_name = ? AND status = 'pending' AND signal_type = 'exit'
                    ORDER BY created_at ASC LIMIT 1
                """
                c.execute(query_exit, (self.bot_id,))
                exit_row = c.fetchone()

                if exit_row:
                    sig_id, ticker = exit_row
                    ticker = ticker.upper().replace("USDT", "").replace("PERP", "")
                    logging.info(f"[{self.bot_id}] 📉 EXIT SIGNAL DETECTED: {ticker}")
                    
                    try:
                        # Track what actually happens
                        actions_log = []

                        # --- A. CANCEL OPEN ORDERS ---
                        open_orders = self.info.frontend_open_orders(self.account.address)
                        my_orders = [o for o in open_orders if o['coin'] == ticker]
                        
                        if my_orders:
                            logging.info(f"   🧹 Cancelling {len(my_orders)} orders...")
                            for o in my_orders:
                                self.exchange.cancel(ticker, o['oid'])
                            actions_log.append(f"Cancelled {len(my_orders)} Orders")
                        
                        # --- B. MARKET CLOSE ---
                        # result is None if there was no position to close
                        result = self.exchange.market_close(ticker)
                        self._check_order_status(result)

                        if result is not None:
                            logging.info(f"   💥 Closing {ticker} position...")
                            actions_log.append("Closed Position")

                        # --- C. SMART LOGGING ---
                        if actions_log:
                            # Join actions: "Cancelled 1 Orders & Closed Position"
                            summary = " & ".join(actions_log)
                            logging.info(f"   ✅ Trade Cleaned Up: {summary}")
                        else:
                            # Explicit "No-Op" message
                            logging.info(f"   ℹ️ No active trade found for {ticker} (No orders/position).")

                        c.execute("UPDATE signals SET status = 'executed' WHERE id = ?", (sig_id,))
                        conn.commit()
                        
                    except Exception as e:
                        logging.error(f"   ❌ Close Failed: {e}")
                        c.execute("UPDATE signals SET status = 'failed', notes = ? WHERE id = ?", (str(e), sig_id))
                        conn.commit()
                        
                    time.sleep(1)
                    continue

                # ==========================================================
                # 🚀 PRIORITY 2: CHECK FOR ENTRIES
                # ==========================================================
                query_entry = """
                    SELECT id, symbol, direction, entry_1, target_1, target_2, target_3, target_4, target_5, stop_loss, confidence_score
                    FROM signals
                    WHERE bot_name = ? AND status = 'pending' AND signal_type = 'entry'
                    ORDER BY created_at ASC LIMIT 1
                """
                c.execute(query_entry, (self.bot_id,))
                row = c.fetchone()

                if row:
                    signal_id, ticker, direction, entry, tp1, tp2, tp3, tp4, tp5, sl, confidence_score = row
                    ticker = ticker.upper().replace("USDT", "").replace("PERP", "")
                    logging.info(f"[{self.bot_id}] ENTRY SIGNAL: {ticker} ({direction})")

                    try:
                        # --- VALIDATION ---
                        if not entry: raise ValueError("Signal missing Entry Price")
                        entry_px = float(entry)
                        is_buy = (direction.lower() in ["long", "bullish"])

                        # --- MAX CONCURRENT POSITIONS CHECK ---
                        user_state = self.info.user_state(self.account.address)
                        open_positions = user_state.get("assetPositions", [])
                        current_position_count = len([p for p in open_positions if float(p["position"]["szi"]) != 0])

                        if current_position_count >= self.max_concurrent_positions:
                            raise ValueError(f"Max concurrent positions reached ({current_position_count}/{self.max_concurrent_positions}). Skipping new entry.")

                        # --- RISK / STOP LOSS ---
                        if not sl:
                            dist = entry_px * self.default_sl_dist
                            sl = (entry_px - dist) if is_buy else (entry_px + dist)
                            logging.warning(f"   ⚠️ No SL. Using Safety Stop: {sl:.4f}")
                        stop_px = float(sl)
                        
                        # --- SIZE CALCULATION ---
                        # (user_state already fetched above for position count check)
                        equity = float(user_state["marginSummary"]["accountValue"])

                        # Use signal's confidence_score for risk if available (1/5 = 1%, 5/5 = 5%)
                        # Otherwise fall back to bot's configured risk_per_trade
                        if confidence_score and 1 <= confidence_score <= 5:
                            signal_risk = confidence_score * 0.01  # Maps 1-5 to 1%-5%
                            risk_amt = equity * signal_risk
                            logging.info(f"   📊 Signal Size: {confidence_score}/5 → Risk: {confidence_score}%")
                        else:
                            risk_amt = equity * self.risk_per_trade
                        price_diff = abs(entry_px - stop_px)
                        
                        if price_diff == 0: raise ValueError("Invalid SL (Price == SL)")
                        size_coin = risk_amt / price_diff
                        
                        # Leverage Cap
                        if (size_coin * entry_px) > (equity * self.max_leverage):
                            size_coin = (equity * self.max_leverage) / entry_px
                            logging.warning(f"   ⚠️ Leverage Cap Hit. Reduced Size.")

                        # --- PRECISION HANDLING ---
                        sz_decimals = self.get_token_sz_decimals(ticker)
                        size_coin = round(size_coin, sz_decimals)
                        
                        entry_px = self.round_px(ticker, entry_px)
                        stop_px  = self.round_px(ticker, stop_px)

                        if size_coin <= 0: raise ValueError("Calculated size is 0 (Risk too small).")

                        logging.info(f"   🚀 Sending Order: {ticker} | Size: {size_coin} | Price: {entry_px}")

                        # --- EXECUTION ---
                        result_entry = self.exchange.order(
                            name=ticker, is_buy=is_buy, sz=size_coin, limit_px=entry_px,
                            order_type={"limit": {"tif": "Gtc"}}, reduce_only=False
                        )
                        self._check_order_status(result_entry)
                        entry_oid = self._extract_order_id(result_entry)
                        logging.info(f"   📝 Entry Order ID: {entry_oid}")

                        result_sl = self.exchange.order(
                            name=ticker, is_buy=not is_buy, sz=size_coin, limit_px=stop_px,
                            order_type={"trigger": {"triggerPx": stop_px, "isMarket": True, "tpsl": "sl"}},
                            reduce_only=True
                        )
                        try: self._check_order_status(result_sl)
                        except: pass
                        sl_oid = self._extract_order_id(result_sl)
                        logging.info(f"   📝 Stop Loss Order ID: {sl_oid}") 

                        # Collect all non-null targets
                        tp_oids = {}  # Store all TP order IDs
                        targets = [
                            (1, tp1), (2, tp2), (3, tp3), (4, tp4), (5, tp5)
                        ]
                        targets = [(num, price) for num, price in targets if price is not None]

                        if targets:
                            num_targets = len(targets)
                            partial_size = size_coin / num_targets

                            logging.info(f"   🎯 Placing {num_targets} TP orders with equal distribution ({100/num_targets:.1f}% each)")

                            for idx, (tp_num, target_price) in enumerate(targets):
                                tp_px = self.round_px(ticker, float(target_price))

                                # Calculate partial size for this TP
                                partial_sz = round(partial_size, sz_decimals)

                                # Last TP takes remaining size to handle rounding errors
                                if idx == len(targets) - 1:
                                    remaining = size_coin - (partial_sz * (num_targets - 1))
                                    partial_sz = round(remaining, sz_decimals)

                                # Ensure size is positive
                                if partial_sz <= 0:
                                    logging.warning(f"   ⚠️ TP{tp_num} size too small after rounding, skipping")
                                    continue

                                try:
                                    result_tp = self.exchange.order(
                                        name=ticker,
                                        is_buy=not is_buy,
                                        sz=partial_sz,
                                        limit_px=tp_px,
                                        order_type={"trigger": {"triggerPx": tp_px, "isMarket": True, "tpsl": "tp"}},
                                        reduce_only=True
                                    )
                                    self._check_order_status(result_tp)
                                    tp_oid = self._extract_order_id(result_tp)
                                    tp_oids[tp_num] = tp_oid
                                    logging.info(f"   ✅ TP{tp_num} @ {tp_px} | Size: {partial_sz} ({partial_sz/size_coin*100:.1f}%) | OID: {tp_oid}")
                                except Exception as e:
                                    logging.error(f"   ❌ TP{tp_num} placement failed: {e}")
                                    # Continue placing remaining TPs even if one fails

                        c.execute("""
                            UPDATE signals
                            SET status = 'filled',
                                position_size_actual = ?,
                                order_id_entry = ?,
                                order_id_sl = ?,
                                order_id_tp1 = ?,
                                order_id_tp2 = ?,
                                order_id_tp3 = ?,
                                order_id_tp4 = ?,
                                order_id_tp5 = ?
                            WHERE id = ?
                        """, (
                            size_coin,
                            entry_oid,
                            sl_oid,
                            tp_oids.get(1),
                            tp_oids.get(2),
                            tp_oids.get(3),
                            tp_oids.get(4),
                            tp_oids.get(5),
                            signal_id
                        ))
                        conn.commit()
                        logging.info(f"   ✅ Signal {signal_id} SUCCESS. Orders Placed.")

                    except Exception as e:
                        logging.error(f"   ❌ Execution Failed: {e}")
                        c.execute("UPDATE signals SET status = 'failed', notes = ? WHERE id = ?", (str(e), signal_id))
                        conn.commit()
                
                time.sleep(2)

            except Exception as e:
                logging.error(f"Loop Error: {e}")
                time.sleep(5)
        logging.info(f"[{self.bot_id}] Starting Database Poll Loop...")
        conn = sqlite3.connect(self.db_path)
        
        while True:
            try:
                c = conn.cursor()

                # ==========================================================
                # 🛑 PRIORITY 1: CHECK FOR EXITS
                # ==========================================================
                query_exit = """
                    SELECT id, symbol 
                    FROM signals 
                    WHERE bot_name = ? AND status = 'pending' AND signal_type = 'exit'
                    ORDER BY created_at ASC LIMIT 1
                """
                c.execute(query_exit, (self.bot_id,))
                exit_row = c.fetchone()

                if exit_row:
                    sig_id, ticker = exit_row
                    ticker = ticker.upper().replace("USDT", "").replace("PERP", "")
                    logging.info(f"[{self.bot_id}] 📉 EXIT SIGNAL DETECTED: {ticker}")
                    
                    try:
                        # A. Cancel Open Orders (Fix for ghost limits)
                        open_orders = self.info.frontend_open_orders(self.account.address)
                        my_orders = [o for o in open_orders if o['coin'] == ticker]
                        if my_orders:
                            logging.info(f"   🧹 Cancelling {len(my_orders)} orders...")
                            for o in my_orders:
                                self.exchange.cancel(ticker, o['oid'])
                        
                        # B. Market Close
                        logging.info(f"   💥 Closing {ticker} position...")
                        result = self.exchange.market_close(ticker)
                        self._check_order_status(result)

                        logging.info(f"   ✅ Trade Cleaned Up.")
                        c.execute("UPDATE signals SET status = 'executed' WHERE id = ?", (sig_id,))
                        conn.commit()
                        
                    except Exception as e:
                        logging.error(f"   ❌ Close Failed: {e}")
                        c.execute("UPDATE signals SET status = 'failed', notes = ? WHERE id = ?", (str(e), sig_id))
                        conn.commit()
                        
                    time.sleep(1)
                    continue

                # ==========================================================
                # 🚀 PRIORITY 2: CHECK FOR ENTRIES
                # ==========================================================
                query_entry = """
                    SELECT id, symbol, direction, entry_1, target_1, target_2, target_3, target_4, target_5, stop_loss, confidence_score
                    FROM signals
                    WHERE bot_name = ? AND status = 'pending' AND signal_type = 'entry'
                    ORDER BY created_at ASC LIMIT 1
                """
                c.execute(query_entry, (self.bot_id,))
                row = c.fetchone()

                if row:
                    signal_id, ticker, direction, entry, tp1, tp2, tp3, tp4, tp5, sl, confidence_score = row
                    ticker = ticker.upper().replace("USDT", "").replace("PERP", "")
                    logging.info(f"[{self.bot_id}] ENTRY SIGNAL: {ticker} ({direction})")

                    try:
                        # --- VALIDATION ---
                        if not entry: raise ValueError("Signal missing Entry Price")
                        entry_px = float(entry)
                        is_buy = (direction.lower() in ["long", "bullish"])

                        # --- MAX CONCURRENT POSITIONS CHECK ---
                        user_state = self.info.user_state(self.account.address)
                        open_positions = user_state.get("assetPositions", [])
                        current_position_count = len([p for p in open_positions if float(p["position"]["szi"]) != 0])

                        if current_position_count >= self.max_concurrent_positions:
                            raise ValueError(f"Max concurrent positions reached ({current_position_count}/{self.max_concurrent_positions}). Skipping new entry.")

                        # --- RISK / STOP LOSS ---
                        if not sl:
                            dist = entry_px * self.default_sl_dist
                            sl = (entry_px - dist) if is_buy else (entry_px + dist)
                            logging.warning(f"   ⚠️ No SL. Using Safety Stop: {sl:.4f}")
                        stop_px = float(sl)
                        
                        # --- SIZE CALCULATION ---
                        # (user_state already fetched above for position count check)
                        equity = float(user_state["marginSummary"]["accountValue"])

                        # Use signal's confidence_score for risk if available (1/5 = 1%, 5/5 = 5%)
                        # Otherwise fall back to bot's configured risk_per_trade
                        if confidence_score and 1 <= confidence_score <= 5:
                            signal_risk = confidence_score * 0.01  # Maps 1-5 to 1%-5%
                            risk_amt = equity * signal_risk
                            logging.info(f"   📊 Signal Size: {confidence_score}/5 → Risk: {confidence_score}%")
                        else:
                            risk_amt = equity * self.risk_per_trade
                        price_diff = abs(entry_px - stop_px)
                        
                        if price_diff == 0: raise ValueError("Invalid SL (Price == SL)")
                        size_coin = risk_amt / price_diff
                        
                        # Leverage Cap
                        if (size_coin * entry_px) > (equity * self.max_leverage):
                            size_coin = (equity * self.max_leverage) / entry_px
                            logging.warning(f"   ⚠️ Leverage Cap Hit. Reduced Size.")

                        # --- PRECISION HANDLING (Size & Price) ---
                        
                        # A. Round Size (Decimal places from Metadata)
                        sz_decimals = self.get_token_sz_decimals(ticker)
                        size_coin = round(size_coin, sz_decimals)
                        
                        # B. Round Price (Strict Hyperliquid Compliance)
                        entry_px = self.round_px(ticker, entry_px)
                        stop_px  = self.round_px(ticker, stop_px)

                        if size_coin <= 0: raise ValueError("Calculated size is 0 (Risk too small).")

                        logging.info(f"   🚀 Sending Order: {ticker} | Size: {size_coin} | Price: {entry_px}")

                        # --- EXECUTION ---
                        
                        # LIMIT ENTRY
                        result_entry = self.exchange.order(
                            name=ticker, is_buy=is_buy, sz=size_coin, limit_px=entry_px, 
                            order_type={"limit": {"tif": "Gtc"}}, reduce_only=False
                        )
                        self._check_order_status(result_entry)
                        
                        # STOP LOSS
                        result_sl = self.exchange.order(
                            name=ticker, is_buy=not is_buy, sz=size_coin, limit_px=stop_px, 
                            order_type={"trigger": {"triggerPx": stop_px, "isMarket": True, "tpsl": "sl"}}, 
                            reduce_only=True
                        )
                        try: self._check_order_status(result_sl)
                        except: pass 

                        # TAKE PROFIT
                        if tp:
                            tp_px = float(tp)
                            tp_px = self.round_px(ticker, tp_px) # Correct rounding
                            
                            self.exchange.order(
                                name=ticker, is_buy=not is_buy, sz=size_coin, limit_px=tp_px, 
                                order_type={"trigger": {"triggerPx": tp_px, "isMarket": True, "tpsl": "tp"}}, 
                                reduce_only=True
                            )

                        c.execute("UPDATE signals SET status = 'filled', position_size_actual = ? WHERE id = ?", (size_coin, signal_id))
                        conn.commit()
                        logging.info(f"   ✅ Signal {signal_id} SUCCESS. Orders Placed.")

                    except Exception as e:
                        logging.error(f"   ❌ Execution Failed: {e}")
                        c.execute("UPDATE signals SET status = 'failed', notes = ? WHERE id = ?", (str(e), signal_id))
                        conn.commit()
                
                time.sleep(2)

            except Exception as e:
                logging.error(f"Loop Error: {e}")
                time.sleep(5)
    def run_fill_monitor(self):
        """
        Continuous loop that monitors fills and triggers breakeven stop loss
        when TP1 is hit. Runs in a separate daemon thread.

        Includes periodic full-scan (every 5 minutes) to catch any missed fills
        due to API issues, service restarts, or timestamp gaps.
        """
        from datetime import datetime

        logging.info(f"[{self.bot_id}] Starting Fill Monitor Loop...")

        last_fill_check = 0  # Timestamp of last processed fill
        full_scan_interval = 300  # 5 minutes - periodic full scan to catch missed fills
        last_full_scan = time.time()

        while True:
            try:
                # Periodic full scan to catch missed fills
                if time.time() - last_full_scan > full_scan_interval:
                    logging.info(f"[{self.bot_id}] 🔍 Fill Monitor: Running periodic full scan for missed fills")
                    last_fill_check = 0  # Reset to re-process all available fills
                    last_full_scan = time.time()

                conn = sqlite3.connect(self.db_path, timeout=10)
                c = conn.cursor()

                # Get all fills since last check
                fills = self.info.user_fills(self.account.address)

                if not fills:
                    conn.close()
                    time.sleep(10)  # Check every 10 seconds
                    continue

                # Filter fills that are newer than last check
                new_fills = [f for f in fills if f['time'] > last_fill_check]

                if new_fills:
                    # Update last check timestamp to most recent fill
                    last_fill_check = max(f['time'] for f in new_fills)

                    # Process each fill
                    for fill in new_fills:
                        self._process_fill(fill, c)

                    conn.commit()

                conn.close()
                time.sleep(10)  # Check every 10 seconds

            except Exception as e:
                logging.error(f"[{self.bot_id}] Fill Monitor Error: {e}")
                time.sleep(10)

    def _process_fill(self, fill, cursor):
        """
        Process a single fill and trigger breakeven logic if TP1 hit.
        Also tracks position closures and calculates actual PnL.

        Fill structure:
        {
            'coin': 'ETH',
            'oid': 123456789,
            'px': '2100.5',
            'sz': '25.0',
            'time': 1704067200000,
            'dir': 'Open Long' | 'Close Long' | 'Open Short' | 'Close Short',
            'closedPnl': '50.0'
        }
        """
        from datetime import datetime

        oid = fill['oid']
        ticker = fill['coin']
        fill_time = datetime.fromtimestamp(fill['time'] / 1000).isoformat()
        fill_dir = fill.get('dir', '')
        closed_pnl = float(fill.get('closedPnl', 0.0))

        # Debug logging for fill processing
        logging.debug(f"[{self.bot_id}] Processing fill: {ticker} | OID={oid} | Dir={fill_dir} | Time={fill_time}")

        # TRACK POSITION CLOSURES for actual PnL calculation
        if 'Close' in fill_dir and closed_pnl != 0.0:
            self._track_position_closure(ticker, fill, cursor)

        # Find signal associated with this order ID
        # IMPORTANT: Order IDs reset monthly on Hyperliquid, so filter by time to avoid collisions
        cursor.execute("""
            SELECT id, direction, entry_1, order_id_sl, sl_moved_to_be, position_size_actual
            FROM signals
            WHERE bot_name = ?
            AND (
                order_id_tp1 = ? OR
                order_id_tp2 = ? OR
                order_id_tp3 = ? OR
                order_id_tp4 = ? OR
                order_id_tp5 = ?
            )
            AND status = 'filled'
            AND datetime(created_at) > datetime('now', '-30 days')
        """, (self.bot_id, oid, oid, oid, oid, oid))

        row = cursor.fetchone()

        if not row:
            logging.debug(f"[{self.bot_id}] No signal match for fill: {ticker} OID={oid}")
            return  # Fill not related to any active position

        signal_id, direction, entry_price, sl_oid, sl_moved_to_be, position_size = row

        # Check which TP was filled
        cursor.execute("""
            SELECT
                CASE
                    WHEN order_id_tp1 = ? THEN 1
                    WHEN order_id_tp2 = ? THEN 2
                    WHEN order_id_tp3 = ? THEN 3
                    WHEN order_id_tp4 = ? THEN 4
                    WHEN order_id_tp5 = ? THEN 5
                END as tp_num
            FROM signals WHERE id = ?
        """, (oid, oid, oid, oid, oid, signal_id))

        tp_num = cursor.fetchone()[0]

        logging.info(f"[{self.bot_id}] 🎯 TP{tp_num} FILLED: {ticker} | Signal {signal_id}")

        # Update fill timestamp
        cursor.execute(f"""
            UPDATE signals
            SET tp{tp_num}_filled_at = ?
            WHERE id = ?
        """, (fill_time, signal_id))

        # TRIGGER BREAKEVEN LOGIC IF TP1 HIT
        enable_breakeven = os.getenv('ENABLE_BREAKEVEN_SL', 'True').lower() == 'true'
        if tp_num == 1 and not sl_moved_to_be and enable_breakeven:
            logging.info(f"[{self.bot_id}] 🔄 TRIGGERING BREAKEVEN for Signal {signal_id}")
            self._move_sl_to_breakeven(signal_id, ticker, direction, entry_price, sl_oid, position_size, cursor)

    def _move_sl_to_breakeven(self, signal_id, ticker, direction, entry_price, old_sl_oid, position_size, cursor):
        """
        Cancel existing stop loss and place new one at breakeven (entry price).

        Thread Safety: Uses atomic claim pattern to prevent race conditions between
        Fill Monitor and Position Reconciliation threads.
        """
        try:
            # CRITICAL: Atomic claim to prevent race condition between Fill Monitor and Reconciliation
            # Attempt to claim this signal by setting sl_moved_to_be=1 only if it's still 0
            cursor.execute("""
                UPDATE signals
                SET sl_moved_to_be = 1,
                    notes = COALESCE(notes, '') || ' | BE SL in progress'
                WHERE id = ? AND sl_moved_to_be = 0
            """, (signal_id,))

            if cursor.rowcount == 0:
                # Another thread already claimed this signal, skip to avoid duplicate orders
                logging.warning(f"[{self.bot_id}] ⚠️ BE already claimed for Signal {signal_id}, skipping (race condition avoided)")
                return

            # Commit immediately so other threads see sl_moved_to_be=1
            cursor.connection.commit()

            is_long = direction.lower() in ['long', 'bullish']

            # Check if position still exists before modifying SL
            user_state = self.info.user_state(self.account.address)
            positions = user_state.get("assetPositions", [])
            active_position = next((p for p in positions if p["position"]["coin"] == ticker), None)

            if not active_position or float(active_position["position"]["szi"]) == 0:
                logging.warning(f"   ⚠️ Position already closed for {ticker}, skipping breakeven")
                return

            # Calculate remaining position size after TP1 (75% if 4 TPs)
            # Query how many TPs exist for this signal
            cursor.execute("""
                SELECT
                    CASE WHEN target_1 IS NOT NULL THEN 1 ELSE 0 END +
                    CASE WHEN target_2 IS NOT NULL THEN 1 ELSE 0 END +
                    CASE WHEN target_3 IS NOT NULL THEN 1 ELSE 0 END +
                    CASE WHEN target_4 IS NOT NULL THEN 1 ELSE 0 END +
                    CASE WHEN target_5 IS NOT NULL THEN 1 ELSE 0 END as num_targets
                FROM signals WHERE id = ?
            """, (signal_id,))

            num_targets = cursor.fetchone()[0]
            remaining_size = position_size * (num_targets - 1) / num_targets
            sz_decimals = self.get_token_sz_decimals(ticker)
            remaining_size = round(remaining_size, sz_decimals)

            # STEP 1: Cancel old stop loss
            if old_sl_oid:
                try:
                    self.exchange.cancel(ticker, old_sl_oid)
                    logging.info(f"   🗑️  Cancelled old SL (OID: {old_sl_oid})")
                except Exception as e:
                    logging.warning(f"   ⚠️ Failed to cancel old SL: {e}")

            # STEP 2: Place new stop loss at breakeven (entry price)
            be_price = float(entry_price)
            be_price_rounded = self.round_px(ticker, be_price)

            result_be_sl = self.exchange.order(
                name=ticker,
                is_buy=not is_long,  # Opposite side to close
                sz=remaining_size,
                limit_px=be_price_rounded,
                order_type={"trigger": {"triggerPx": be_price_rounded, "isMarket": True, "tpsl": "sl"}},
                reduce_only=True
            )

            self._check_order_status(result_be_sl)
            be_sl_oid = self._extract_order_id(result_be_sl)

            logging.info(f"   ✅ NEW BREAKEVEN SL @ {be_price_rounded} | Size: {remaining_size} | OID: {be_sl_oid}")

            # STEP 3: Update database with BE order ID (sl_moved_to_be already set at start)
            cursor.execute("""
                UPDATE signals
                SET be_sl_order_id = ?,
                    notes = COALESCE(notes, '') || ' | BE SL triggered after TP1'
                WHERE id = ?
            """, (be_sl_oid, signal_id))
            cursor.connection.commit()

            logging.info(f"[{self.bot_id}] 🛡️ BREAKEVEN ACTIVE for {ticker}")

        except Exception as e:
            logging.error(f"[{self.bot_id}] ❌ Breakeven SL failed: {e}")
            # Reset flag so reconciliation can retry later
            try:
                cursor.execute("""
                    UPDATE signals
                    SET sl_moved_to_be = 0,
                        notes = COALESCE(notes, '') || ' | BE SL failed: ' || ?
                    WHERE id = ?
                """, (str(e)[:100], signal_id))
                cursor.connection.commit()
            except Exception:
                pass  # Don't mask original error

    def _track_position_closure(self, ticker, fill, cursor):
        """
        Track position closures and calculate actual PnL from Hyperliquid fills.
        Updates both entry signal and exit signal (if exists) with actual PnL.

        Args:
            ticker: Symbol (e.g., 'ETH')
            fill: Fill data from Hyperliquid API
            cursor: Database cursor
        """
        from datetime import datetime

        try:
            closed_pnl = float(fill.get('closedPnl', 0.0))
            close_price = float(fill.get('px', 0.0))
            close_size = float(fill.get('sz', 0.0))
            fill_time = datetime.fromtimestamp(fill['time'] / 1000).isoformat()

            if closed_pnl == 0.0 or close_size == 0.0:
                return  # No meaningful PnL to track

            # Find the most recent filled entry for this ticker
            cursor.execute("""
                SELECT id, entry_1, position_size_actual
                FROM signals
                WHERE bot_name = ?
                AND symbol = ?
                AND signal_type = 'entry'
                AND status = 'filled'
                ORDER BY created_at DESC
                LIMIT 1
            """, (self.bot_id, ticker))

            entry_row = cursor.fetchone()

            if not entry_row:
                logging.warning(f"[{self.bot_id}] Position closed for {ticker} but no entry signal found")
                return

            signal_id, entry_price, position_size = entry_row
            entry_price = float(entry_price)
            position_size = float(position_size)

            # Calculate PnL percentage
            # PnL% = (closedPnl / (entry_price * position_size)) * 100
            position_value = entry_price * position_size
            if position_value > 0:
                pnl_percent = (closed_pnl / position_value) * 100
            else:
                pnl_percent = 0.0

            logging.info(f"[{self.bot_id}] 💰 POSITION CLOSED: {ticker} | "
                        f"Entry: ${entry_price:.4f} | Close: ${close_price:.4f} | "
                        f"Size: {position_size} | Actual PnL: {pnl_percent:.2f}% (${closed_pnl:.2f})")

            # Update entry signal with actual PnL
            cursor.execute("""
                UPDATE signals
                SET pnl_percent_actual = ?,
                    notes = COALESCE(notes, '') || ' | Actual PnL: ' || ? || '%'
                WHERE id = ?
            """, (pnl_percent, f"{pnl_percent:.2f}", signal_id))

            # Find and update corresponding exit signal (if exists)
            cursor.execute("""
                SELECT id
                FROM signals
                WHERE bot_name = ?
                AND symbol = ?
                AND signal_type = 'exit'
                AND status IN ('executed', 'no_op')
                AND created_at > (SELECT created_at FROM signals WHERE id = ?)
                ORDER BY created_at ASC
                LIMIT 1
            """, (self.bot_id, ticker, signal_id))

            exit_row = cursor.fetchone()

            if exit_row:
                exit_signal_id = exit_row[0]
                cursor.execute("""
                    UPDATE signals
                    SET pnl_percent_actual = ?
                    WHERE id = ?
                """, (pnl_percent, exit_signal_id))
                logging.info(f"   📝 Updated exit signal {exit_signal_id} with actual PnL")

        except Exception as e:
            logging.error(f"[{self.bot_id}] ❌ Failed to track position closure: {e}")

    def run_position_reconciliation(self):
        """
        Continuous loop that reconciles database position state with actual Hyperliquid positions.
        Runs every 60 seconds to detect and fix ghost positions (positions marked as 'filled'
        in DB but no longer exist on Hyperliquid).

        This catches all edge cases:
        - System restarts (missed fills)
        - API outages (Fill Monitor failures)
        - Stop losses hit automatically
        - Take profits filled
        - Manual position closes on Hyperliquid
        """
        logging.info(f"[{self.bot_id}] Starting Position Reconciliation Loop...")

        while True:
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                c = conn.cursor()

                # Get all positions DB thinks are open (status='filled')
                c.execute("""
                    SELECT id, symbol, entry_1, position_size_actual
                    FROM signals
                    WHERE bot_name = ?
                    AND signal_type = 'entry'
                    AND status = 'filled'
                    ORDER BY created_at DESC
                """, (self.bot_id,))

                db_positions = c.fetchall()

                if not db_positions:
                    conn.close()
                    time.sleep(60)
                    continue

                # Get actual positions from Hyperliquid
                user_state = self.info.user_state(self.account.address)
                hl_positions = user_state.get("assetPositions", [])

                # Build set of open tickers on Hyperliquid
                open_tickers = set()
                for pos in hl_positions:
                    size = float(pos["position"]["szi"])
                    if size != 0:
                        open_tickers.add(pos["position"]["coin"])

                # Check each DB position
                for signal_id, ticker, entry_price, position_size in db_positions:
                    ticker_clean = ticker.upper().replace("USDT", "").replace("PERP", "")

                    # If position exists in DB but NOT on Hyperliquid, it's a ghost
                    if ticker_clean not in open_tickers:
                        logging.warning(f"[{self.bot_id}] 👻 GHOST POSITION DETECTED: {ticker_clean} (ID: {signal_id})")

                        # Try to get PnL from recent fills
                        pnl_info = self._get_pnl_from_fills(ticker_clean, entry_price, position_size)

                        if pnl_info:
                            pnl_percent, closed_pnl, close_price = pnl_info

                            # Update with PnL data
                            c.execute("""
                                UPDATE signals
                                SET status = 'closed',
                                    pnl_percent_actual = ?,
                                    notes = COALESCE(notes, '') || ' | Auto-closed by reconciliation. Actual PnL: ' || ? || '%'
                                WHERE id = ?
                            """, (pnl_percent, f"{pnl_percent:.2f}", signal_id))

                            logging.info(f"   ✅ Reconciled {ticker_clean}: status='closed' | "
                                       f"Entry: ${float(entry_price):.4f} | Close: ${close_price:.4f} | "
                                       f"PnL: {pnl_percent:.2f}% (${closed_pnl:.2f})")
                        else:
                            # No PnL data available, just mark as closed
                            c.execute("""
                                UPDATE signals
                                SET status = 'closed',
                                    notes = COALESCE(notes, '') || ' | Auto-closed by reconciliation (PnL unavailable)'
                                WHERE id = ?
                            """, (signal_id,))

                            logging.info(f"   ✅ Reconciled {ticker_clean}: status='closed' (PnL data unavailable)")

                # Fallback: Check for missed TP1 fills that should have triggered breakeven
                self._check_missed_breakeven(c)

                conn.commit()
                conn.close()

                time.sleep(60)  # Run every 60 seconds

            except Exception as e:
                logging.error(f"[{self.bot_id}] Position Reconciliation Error: {e}")
                time.sleep(60)

    def _get_pnl_from_fills(self, ticker, entry_price, position_size):
        """
        Try to retrieve PnL data from recent fills for a closed position.

        Args:
            ticker: Symbol (e.g., 'ETH')
            entry_price: Entry price from database
            position_size: Position size from database

        Returns:
            Tuple of (pnl_percent, closed_pnl, close_price) or None if not found
        """
        try:
            fills = self.info.user_fills(self.account.address)

            # Look for closing fills for this ticker (most recent 100 fills)
            for fill in reversed(fills[-100:]):
                if fill['coin'] == ticker and 'Close' in fill.get('dir', ''):
                    closed_pnl = float(fill.get('closedPnl', 0.0))
                    close_price = float(fill.get('px', 0.0))

                    if closed_pnl != 0.0:
                        # Calculate PnL percentage
                        position_value = float(entry_price) * float(position_size)
                        if position_value > 0:
                            pnl_percent = (closed_pnl / position_value) * 100
                            return (pnl_percent, closed_pnl, close_price)

            return None

        except Exception as e:
            logging.warning(f"[{self.bot_id}] Could not fetch PnL from fills for {ticker}: {e}")
            return None

    def _check_missed_breakeven(self, cursor):
        """
        Fallback check: Detect if any open positions missed their TP1 fill detection.
        Query Hyperliquid fills to verify if TP1 was filled but BE not triggered.

        This catches cases where the Fill Monitor missed the TP1 fill due to:
        - API outages (502 errors)
        - Service restarts
        - Timestamp filtering gaps

        Called from run_position_reconciliation() every 60 seconds.
        """
        enable_breakeven = os.getenv('ENABLE_BREAKEVEN_SL', 'True').lower() == 'true'
        if not enable_breakeven:
            return

        # Query positions with status='filled' and sl_moved_to_be=0 (BE not yet triggered)
        cursor.execute("""
            SELECT id, symbol, direction, entry_1, order_id_tp1, order_id_sl, position_size_actual
            FROM signals
            WHERE bot_name = ?
            AND status = 'filled'
            AND sl_moved_to_be = 0
            AND order_id_tp1 IS NOT NULL
        """, (self.bot_id,))

        positions_without_be = cursor.fetchall()

        if not positions_without_be:
            return

        # Get recent fills from Hyperliquid
        try:
            fills = self.info.user_fills(self.account.address)
        except Exception as e:
            logging.warning(f"[{self.bot_id}] Could not fetch fills for BE check: {e}")
            return

        # Build set of filled order IDs for fast lookup
        fill_oids = {f['oid'] for f in fills}

        # Check each position for missed TP1 fill
        for row in positions_without_be:
            signal_id, ticker, direction, entry_price, tp1_oid, sl_oid, position_size = row

            # Check if TP1 order was filled but we missed detecting it
            if tp1_oid and tp1_oid in fill_oids:
                logging.warning(f"[{self.bot_id}] 🔄 RECONCILIATION: Missed TP1 fill detected for {ticker} (Signal {signal_id})")
                logging.info(f"[{self.bot_id}]    Triggering fallback breakeven for {ticker}...")

                try:
                    self._move_sl_to_breakeven(
                        signal_id, ticker, direction, entry_price,
                        sl_oid, position_size, cursor
                    )
                except Exception as e:
                    logging.error(f"[{self.bot_id}] ❌ Fallback breakeven failed for {ticker} (Signal {signal_id}): {e}")
                    # Continue processing other positions
