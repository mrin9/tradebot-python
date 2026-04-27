#!/bin/bash

# Configuration
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
VENV_PATH="$PROJECT_DIR/.venv"
PYTHON_CMD="$VENV_PATH/bin/python3"
CLI_PATH="$PROJECT_DIR/apps/cli/main.py"
PID_FILE="$PROJECT_DIR/logs/live_trade.pid"
LOG_FILE="$PROJECT_DIR/logs/app.log"
DATE_STR=$(date +%Y-%m-%d)

# Load Virtual Environment if it exists
if [ -d "$VENV_PATH" ]; then
    source "$VENV_PATH/bin/activate"
else
    echo "Warning: Virtual environment not found at $VENV_PATH. Using system python."
fi

cd "$PROJECT_DIR"

# Check for papertrade flag
PAPERTRADE_ARG=""
for arg in "$@"; do
    if [ "$arg" == "--papertrade" ]; then
        PAPERTRADE_ARG="--papertrade"
        break
    fi
done

case "$1" in
    start)
        echo "[$DATE_STR 09:00] Starting Morning Workflow..."
        if [ -n "$PAPERTRADE_ARG" ]; then
            echo "Running in PAPERTRADE mode."
        fi

        # 1. Update Master Instrument
        $PYTHON_CMD "$CLI_PATH" update-master

        # 2. Sync Nifty and Options Candle
        $PYTHON_CMD "$CLI_PATH" sync-history --date-range "today"

        # 3. Delete logs/app.log
        if [ -f "$LOG_FILE" ]; then
            echo "Removing old log file: $LOG_FILE"
            rm "$LOG_FILE"
        fi

        # 4. Start Live trade
        echo "Starting Live Trade Engine..."
        # We use nohup to keep it running after the shell exits.
        # It auto-stops at 3:30 PM due to internal logic, but we also have a 'stop' command.
        nohup $PYTHON_CMD "$CLI_PATH" live-trade $PAPERTRADE_ARG > "$PROJECT_DIR/logs/process.log" 2>&1 &
        echo $! > "$PID_FILE"
        echo "Live Trade started with PID $(cat $PID_FILE)"
        ;;

    stop)
        echo "[$DATE_STR 15:30] Starting Afternoon Workflow..."

        # 1. Kill or stop the live trade process
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            echo "Stopping Live Trade process (PID: $PID)..."
            kill "$PID" 2>/dev/null
            rm "$PID_FILE"
            sleep 5 # Wait for process to clean up
        else
            echo "PID file not found. Process might not be running or already stopped."
        fi

        # 2. Archive the logs/app.log (Filtered)
        if [ -f "$LOG_FILE" ]; then
            ARCHIVE_LOG="$PROJECT_DIR/logs/$DATE_STR-trade.log"
            echo "Filtering and archiving logs to $ARCHIVE_LOG"
            
            # Extract only trades, heartbeats and session stops
            # Using -E for extended regex to catch multiple patterns
            PATTERNS="HEARTBEAT|Entry|Exit|TARGET|Signal|Break-Even|PYRAMID|Stopped\.|Session Summary saved|Settlement"
            
            # Append only matching lines. If no lines match, nothing is appended.
            grep -E "$PATTERNS" "$LOG_FILE" >> "$ARCHIVE_LOG" 2>/dev/null
            
            # Remove the original app.log
            rm "$LOG_FILE"
        else
            echo "app.log not found, nothing to archive."
        fi

        # 3. Update Master Instrument
        $PYTHON_CMD "$CLI_PATH" update-master

        # 4. Sync Nifty and Options Candle
        $PYTHON_CMD "$CLI_PATH" sync-history --date-range "today"

        # 5. Compact 3-minute ticks into a single daily file
        echo "Compacting daily tick chunks..."
        $PYTHON_CMD "$PROJECT_DIR/scripts/compact_ticks.py"

        echo "Afternoon Workflow Complete."
        ;;

    *)
        echo "Usage: $0 {start|stop} [--papertrade]"
        exit 1
        ;;
esac
