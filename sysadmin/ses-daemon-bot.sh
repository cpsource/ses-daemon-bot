#!/bin/bash
#
# ses-daemon-bot management script
# Usage: ses-daemon-bot.sh {start|stop|restart|status|logs}
#

set -e

# Configuration
DAEMON_NAME="ses-daemon-bot"
DAEMON_DIR="/home/ubuntu/ses-daemon-bot"
DAEMON_SCRIPT="main.py"
PYTHON="/home/ubuntu/mnt/myproject/bin/python3"
CONFIG_FILE="/home/ubuntu/.env"
LOG_FILE="/var/log/ses-daemon-bot.log"
PID_FILE="/var/run/ses-daemon-bot.pid"
POLL_INTERVAL=60

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# S3 bucket for email history
SES_BUCKET="frflashy-ses-incoming"

usage() {
    echo "Usage: $0 {start|stop|restart|status|logs|test-creds|test-ses|history}"
    echo ""
    echo "Commands:"
    echo "  start       Start the daemon"
    echo "  stop        Stop the daemon"
    echo "  restart     Restart the daemon"
    echo "  status      Show daemon status"
    echo "  logs        Tail the log file"
    echo "  test-creds  Validate credentials"
    echo "  test-ses    Test SES/S3 connection (read emails)"
    echo "  history     List processed emails from S3"
    exit 1
}

get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    else
        echo ""
    fi
}

is_running() {
    local pid=$(get_pid)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

do_start() {
    if is_running; then
        echo -e "${YELLOW}$DAEMON_NAME is already running (PID: $(get_pid))${NC}"
        exit 0
    fi

    echo -n "Starting $DAEMON_NAME... "

    # Ensure log directory exists
    sudo touch "$LOG_FILE" 2>/dev/null || true
    sudo chown ubuntu:ubuntu "$LOG_FILE" 2>/dev/null || true

    # Start the daemon
    cd "$DAEMON_DIR"
    $PYTHON "$DAEMON_SCRIPT" \
        --daemon \
        --config "$CONFIG_FILE" \
        --log-file "$LOG_FILE" \
        --pid-file "$PID_FILE" \
        --interval "$POLL_INTERVAL"

    # Wait a moment and check if it started
    sleep 1
    if is_running; then
        echo -e "${GREEN}OK${NC} (PID: $(get_pid))"
    else
        echo -e "${RED}FAILED${NC}"
        echo "Check log file: $LOG_FILE"
        exit 1
    fi
}

do_stop() {
    if ! is_running; then
        echo -e "${YELLOW}$DAEMON_NAME is not running${NC}"
        # Clean up stale PID file
        rm -f "$PID_FILE" 2>/dev/null || true
        exit 0
    fi

    local pid=$(get_pid)
    echo -n "Stopping $DAEMON_NAME (PID: $pid)... "

    # Send SIGTERM for graceful shutdown
    kill -TERM "$pid" 2>/dev/null

    # Wait for process to exit (max 10 seconds)
    local count=0
    while is_running && [ $count -lt 10 ]; do
        sleep 1
        count=$((count + 1))
    done

    if is_running; then
        # Force kill if still running
        echo -n "forcing... "
        kill -KILL "$pid" 2>/dev/null
        sleep 1
    fi

    if is_running; then
        echo -e "${RED}FAILED${NC}"
        exit 1
    else
        echo -e "${GREEN}OK${NC}"
        rm -f "$PID_FILE" 2>/dev/null || true
    fi
}

do_restart() {
    do_stop
    sleep 1
    do_start
}

do_status() {
    if is_running; then
        local pid=$(get_pid)
        echo -e "${GREEN}$DAEMON_NAME is running${NC} (PID: $pid)"
        echo ""
        echo "Process info:"
        ps -p "$pid" -o pid,ppid,user,%cpu,%mem,etime,cmd --no-headers 2>/dev/null || true
        echo ""
        echo "Log file: $LOG_FILE"
        echo "PID file: $PID_FILE"
        echo "Config:   $CONFIG_FILE"
    else
        echo -e "${RED}$DAEMON_NAME is not running${NC}"
        if [ -f "$PID_FILE" ]; then
            echo "(stale PID file exists: $PID_FILE)"
        fi
        exit 1
    fi
}

do_logs() {
    if [ -f "$LOG_FILE" ]; then
        echo "Tailing $LOG_FILE (Ctrl+C to exit)..."
        echo "----------------------------------------"
        tail -f "$LOG_FILE"
    else
        echo "Log file not found: $LOG_FILE"
        exit 1
    fi
}

do_test_creds() {
    echo "Testing credentials..."
    cd "$DAEMON_DIR"
    $PYTHON "$DAEMON_SCRIPT" --config "$CONFIG_FILE" --test-creds
}

do_test_ses() {
    echo "Testing SES/S3 connection..."
    cd "$DAEMON_DIR"
    $PYTHON "$DAEMON_SCRIPT" --config "$CONFIG_FILE" --test-ses
}

do_history() {
    local key="${1:-}"

    if [ -n "$key" ]; then
        # Show specific email - try processed, then pending, then failed
        for prefix in processed emails failed; do
            if aws s3 ls "s3://${SES_BUCKET}/${prefix}/${key}" >/dev/null 2>&1; then
                echo "Email: s3://${SES_BUCKET}/${prefix}/${key}"
                echo "----------------------------------------"
                aws s3 cp "s3://${SES_BUCKET}/${prefix}/${key}" -
                return 0
            fi
        done
        echo "Email not found: $key"
        return 1
    fi

    echo "Processed emails in S3:"
    echo "----------------------------------------"
    aws s3 ls "s3://${SES_BUCKET}/processed/" --human-readable
    echo ""
    echo "Pending emails:"
    aws s3 ls "s3://${SES_BUCKET}/emails/" --human-readable 2>/dev/null || echo "  (none)"
    echo ""
    echo "Failed emails:"
    aws s3 ls "s3://${SES_BUCKET}/failed/" --human-readable 2>/dev/null || echo "  (none)"
    echo ""
    echo "To view an email: $0 history <key>"
}

# Main
case "${1:-}" in
    start)
        do_start
        ;;
    stop)
        do_stop
        ;;
    restart)
        do_restart
        ;;
    status)
        do_status
        ;;
    logs)
        do_logs
        ;;
    test-creds)
        do_test_creds
        ;;
    test-ses)
        do_test_ses
        ;;
    history)
        do_history "${2:-}"
        ;;
    *)
        usage
        ;;
esac

exit 0
