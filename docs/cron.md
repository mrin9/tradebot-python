# Cron Job Automation Setup

This document provides instructions for setting up and managing the daily trading bot automation on your VPS.

## 1. Automation Script
The central control script is located at:
`scripts/daily_trade_workflow.sh`

### Features:
- **Morning (9:00 AM)**: 
  - Updates Master Instrument database.
  - Syncs Nifty and Options history for the current day.
  - Clears previous session logs (`logs/app.log`).
  - Starts the Live Trading Engine in the background.
- **Afternoon (3:30 PM)**:
  - Stops the Live Trading Engine.
  - Archives the session log to `logs/{date}-trade.log`.
  - Performs EOD Master Instrument and History syncs.

## 2. Scheduling via Cron
To automate these tasks, add the following lines to your crontab.

1. Open crontab editor:
   ```bash
   crontab -e
   ```

2. Add these lines (Update `/path/to/trade-bot-v2` with your actual project path):

```cron
# Trade Bot: Morning Start (Mon-Fri at 9:00 AM)
0 9 * * 1-5 /home/bot/htdocs/www.bazaartrend.com/tradebot/scripts/daily_trade_workflow.sh start >> /home/bot/htdocs/www.bazaartrend.com/tradebot/logs/cron.log 2>&1

# Trade Bot: Afternoon Stop (Mon-Fri at 3:30 PM)
30 15 * * 1-5 /home/bot/htdocs/www.bazaartrend.com/tradebot/scripts/daily_trade_workflow.sh stop >> /home/bot/htdocs/www.bazaartrend.com/tradebot/logs/cron.log 2>&1
```

## 3. Monitoring & Logs
- **Trading Logs**: `logs/app.log` (Current session) or `logs/YYYY-MM-DD-trade.log` (Archived).
- **Process Logs**: `logs/process.log` (System output/errors from the Python process).
- **Automation Logs**: `logs/cron.log` (Output from the shell script execution).

## 4. Manual Control
You can also run the script manually:
```bash
# To start the morning workflow manually
./scripts/daily_trade_workflow.sh start

# To stop it and run EOD syncs manually
./scripts/daily_trade_workflow.sh stop
```
