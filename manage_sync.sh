#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  Upwork → CRM Sync Service Manager
# ═══════════════════════════════════════════════════════════════
# Usage:
#   ./manage_sync.sh status    - Check if service is running
#   ./manage_sync.sh start     - Start the service
#   ./manage_sync.sh stop      - Stop the service
#   ./manage_sync.sh restart   - Restart the service
#   ./manage_sync.sh logs      - View today's sync logs
#   ./manage_sync.sh run       - Run sync manually (once)

PLIST="$HOME/Library/LaunchAgents/com.wsoftpro.upwork-crm-sync.plist"
LABEL="com.wsoftpro.upwork-crm-sync"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
VENV="$SCRIPT_DIR/venv/bin/python3"

case "${1:-status}" in
    status)
        echo "═══════════════════════════════════════════"
        echo "  📋 Upwork → CRM Sync Service Status"
        echo "═══════════════════════════════════════════"
        if launchctl list | grep -q "$LABEL"; then
            PID=$(launchctl list | grep "$LABEL" | awk '{print $1}')
            EXIT=$(launchctl list | grep "$LABEL" | awk '{print $2}')
            echo "  ✅ Service: LOADED"
            echo "  🔢 PID: $PID"
            echo "  📊 Last exit: $EXIT"
        else
            echo "  ❌ Service: NOT LOADED"
        fi
        echo ""
        echo "  ⏱️  Interval: Every 20 minutes"
        echo "  📂 Logs: $LOG_DIR"
        
        # Show last sync time
        TODAY=$(date +%Y%m%d)
        LOG_FILE="$LOG_DIR/sync_${TODAY}.log"
        if [ -f "$LOG_FILE" ]; then
            LAST=$(grep "SYNC COMPLETE\|UPWORK → CRM AUTO SYNC" "$LOG_FILE" | tail -1)
            echo "  📅 Last activity: $LAST"
            CREATED=$(grep "Created:" "$LOG_FILE" | tail -1)
            if [ -n "$CREATED" ]; then
                echo "  $CREATED"
            fi
        fi
        
        # Show synced count
        SYNCED="$SCRIPT_DIR/synced_jobs.json"
        if [ -f "$SYNCED" ]; then
            COUNT=$(python3 -c "import json; print(len(json.load(open('$SYNCED'))))" 2>/dev/null)
            echo "  📊 Total synced jobs: $COUNT"
        fi
        echo "═══════════════════════════════════════════"
        ;;
    start)
        echo "▶️  Starting sync service..."
        launchctl load "$PLIST" 2>/dev/null
        echo "✅ Started!"
        ;;
    stop)
        echo "⏹️  Stopping sync service..."
        launchctl unload "$PLIST" 2>/dev/null
        echo "✅ Stopped!"
        ;;
    restart)
        echo "🔄 Restarting sync service..."
        launchctl unload "$PLIST" 2>/dev/null
        sleep 1
        launchctl load "$PLIST" 2>/dev/null
        echo "✅ Restarted!"
        ;;
    logs)
        TODAY=$(date +%Y%m%d)
        LOG_FILE="$LOG_DIR/sync_${TODAY}.log"
        if [ -f "$LOG_FILE" ]; then
            echo "📄 Today's sync log ($LOG_FILE):"
            echo "──────────────────────────────────────────"
            tail -50 "$LOG_FILE"
        else
            echo "📭 No logs for today yet."
        fi
        ;;
    run)
        echo "🚀 Running sync manually..."
        cd "$SCRIPT_DIR" && "$VENV" auto_sync.py --query "IT"
        ;;
    *)
        echo "Usage: $0 {status|start|stop|restart|logs|run}"
        exit 1
        ;;
esac
