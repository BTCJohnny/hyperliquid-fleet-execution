# System Monitoring & Troubleshooting Quick Reference

## Log Viewer Tool

The interactive log viewer provides easy access to all system logs:

```bash
# Interactive menu (recommended for beginners)
python test/view_logs.py

# Quick commands
python test/view_logs.py --status           # Check all log files status
python test/view_logs.py --errors           # Show only errors/warnings
python test/view_logs.py --bot Alpha        # Filter by bot name
python test/view_logs.py --tail -f          # Follow all logs in real-time
python test/view_logs.py --service fleet    # View specific service log
```

## Configuration Audit

Validate entire system configuration and identify issues:

```bash
# Run comprehensive configuration audit
python test/audit_config.py

# Verbose mode (show all success messages)
python test/audit_config.py --verbose
```

The audit checks:
- Environment files (.env) and required variables
- Telegram services status (running/stopped)
- Parser capabilities (entry/exit parsing)
- Database schema and recent signals
- Log file locations and permissions

## Signal Flow Tracer

Trace a signal through the entire pipeline (Telegram → Parser → DB → Fleet → Hyperliquid):

```bash
# Trace specific signal ID
python test/trace_signal.py --signal-id 7

# Trace all signals for a symbol
python test/trace_signal.py --symbol POL

# Trace signals for specific bot
python test/trace_signal.py --bot Alpha

# Show all recent signals
python test/trace_signal.py --all --recent 10
```

The tracer shows:
- Database insertion timestamp
- Parser log entries
- Fleet execution logs
- Success/failure analysis
- Related exit signals (for entries)

## Signal Reconciliation

Compare telegram signals, database records, and Hyperliquid positions:

```bash
# Full reconciliation report for AlphaCryptoSignal bot
python test/reconcile_alpha_signals.py

# Run tests
python test/test_reconcile_alpha.py
```

The reconciliation report identifies 4 types of mismatches:
1. **Telegram→Database**: Signals logged but not in database
2. **Database→Execution**: Signals in DB but not executed (status='pending' or 'failed')
3. **Parameter Accuracy**: Executed with wrong size/price
4. **Orphan Positions**: Hyperliquid positions with no matching signal

## Service Status Checks

### Check if services are running:
```bash
# Launchd services
launchctl list | grep telegram
launchctl list | grep fleet

# Process status
ps aux | grep telegram_signals_to_sqlite | grep -v grep
ps aux | grep telegram_forwarder | grep -v grep
ps aux | grep fleet_runner | grep -v grep
```

### Restart services:
```bash
# Telegram parser
launchctl unload ~/Library/LaunchAgents/com.telegram.signals.plist
launchctl load ~/Library/LaunchAgents/com.telegram.signals.plist

# Telegram forwarder
launchctl unload ~/Library/LaunchAgents/com.telegram.forwarder.plist
launchctl load ~/Library/LaunchAgents/com.telegram.forwarder.plist

# Fleet runner (if running as service)
launchctl unload ~/Library/LaunchAgents/com.fleet.runner.plist
launchctl load ~/Library/LaunchAgents/com.fleet.runner.plist
```

## Log File Locations

All logs are in: `/Users/johnny_main/Developer/data/logs/`

| File | Purpose |
|------|---------|
| `fleet_launchd.err` | Fleet runner execution (all 3 bots) |
| `telegram_signals_sqlite.log` | Parser stdout (signal ingestion) |
| `telegram_signals_sqlite_error.log` | Parser stderr |
| `telegram_forwarder.log` | Forwarder stdout |
| `telegram_forwarder_error.log` | Forwarder stderr |

### Quick log access:
```bash
# Tail logs
tail -f /Users/johnny_main/Developer/data/logs/fleet_launchd.err
tail -f /Users/johnny_main/Developer/data/logs/telegram_signals_sqlite.log

# Search for specific bot
grep "AlphaCryptoSignal" /Users/johnny_main/Developer/data/logs/fleet_launchd.err

# Search for errors
grep -E "(ERROR|FAILED|❌)" /Users/johnny_main/Developer/data/logs/fleet_launchd.err
```

## Admin Controls

### Query positions and status:
```bash
# Check Alpha bot positions
python admin_controls.py "Alpha" POSITIONS
python admin_controls.py "Alpha" STATUS
python admin_controls.py "Alpha" ORDERS

# Check all bots
python admin_controls.py ALL POSITIONS
python admin_controls.py ALL STATUS
```

### Control commands:
```bash
# Pause/Resume trading
python admin_controls.py "Alpha" PAUSE
python admin_controls.py "Alpha" RESUME

# Emergency: Close all positions
python admin_controls.py "Alpha" CLOSE_ALL
python admin_controls.py ALL CLOSE_ALL
```

## Emergency Procedures

### 1. Nuke Account (Cancel all orders + Close all positions)
```bash
# Specific bot
python nuke_account.py "AlphaCryptoSignal"

# All bots
python nuke_account.py ALL
```

### 2. Database Issues
```bash
# Check database status
python test/check_db_status.py

# Query specific bot signals
sqlite3 /Users/johnny_main/Developer/data/signals/signals.db \
  "SELECT * FROM signals WHERE bot_name='AlphaCryptoSignal' ORDER BY created_at DESC LIMIT 10"

# Check for pending signals
sqlite3 /Users/johnny_main/Developer/data/signals/signals.db \
  "SELECT COUNT(*) FROM signals WHERE status='pending'"
```

### 3. Service Not Starting
```bash
# Check launchd status
launchctl print gui/$(id -u)/com.telegram.signals

# Check if log directory is writable
ls -la /Users/johnny_main/Developer/data/logs/

# Manually test service
cd /Users/johnny_main/Developer/projects/telegram_forwarder
/opt/anaconda3/bin/python telegram_signals_to_sqlite.py
```

## Common Issues & Solutions

### Issue: Parser logs not appearing
**Solution:**
1. Check service is running: `launchctl list | grep telegram.signals`
2. Restart service (see above)
3. Check error log: `cat /Users/johnny_main/Developer/data/logs/telegram_signals_sqlite_error.log`

### Issue: Signals in database but not executing
**Solution:**
1. Check fleet is running: `ps aux | grep fleet_runner.py`
2. Check bot_id matches: `python test/reconcile_alpha_signals.py`
3. Review failed signals: `python test/view_logs.py --errors`

### Issue: Position exists but no signal in database
**Solution:**
1. Check for manual trades on Hyperliquid
2. Run reconciliation: `python test/reconcile_alpha_signals.py`
3. Verify wallet address: `python admin_controls.py "Alpha" STATUS`

### Issue: Execution with wrong parameters
**Solution:**
1. Check risk settings in `fleet_runner.py` FLEET_CONFIG
2. Verify max_leverage not capping size
3. Review precision rounding in logs: `grep "Sending Order" /Users/johnny_main/Developer/data/logs/fleet_launchd.err`

## Performance Analytics

### PnL Dashboard:
```bash
python pnl_dashboard.py
```

Shows per-bot performance metrics, win/loss ratios, and return percentages.

## Monitoring Best Practices

1. **Daily Health Check:**
   ```bash
   python test/view_logs.py --status
   python test/view_logs.py --errors
   python admin_controls.py ALL STATUS
   ```

2. **Weekly Reconciliation:**
   ```bash
   python test/reconcile_alpha_signals.py
   ```

3. **Real-time Monitoring:**
   ```bash
   python test/view_logs.py --tail -f
   ```

4. **Before Trading Day:**
   - Verify services running: `launchctl list | grep telegram`
   - Check log file timestamps are recent
   - Run connection test: `python test/connection_test.py`

5. **After Significant Changes:**
   - Restart all services
   - Run full test suite
   - Monitor logs for first few signals

## Configuration Files

- Fleet config: `fleet_runner.py` → `FLEET_CONFIG`
- Environment variables: `.env`
- Launchd services: `~/Library/LaunchAgents/com.telegram.*.plist`
- External parser: `/Users/johnny_main/Developer/projects/telegram_forwarder/telegram_signals_to_sqlite.py`

## Network & Environment

- **Hyperliquid Network:** Testnet (IS_MAINNET=False in .env)
- **Database:** SQLite at `/Users/johnny_main/Developer/data/signals/signals.db`
- **Python:** Uses /opt/anaconda3/bin/python (via venv for fleet)
- **Working Directory:** `/Users/johnny_main/Developer/projects/telegram_trading_bots/hyper_v1`
