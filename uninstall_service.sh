#!/bin/bash
# uninstall_service.sh - Unload and remove the GenCan SSE Launch Agent and all associated artifacts.
set -e

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/gencan-sse"

# Parse arguments
IS_DEV=false
for arg in "$@"; do
    if [ "$arg" = "--dev" ]; then
        IS_DEV=true
    fi
done

if [ "$IS_DEV" = true ]; then
    PLIST_NAME="com.gencan.sse.dev.plist"
    PLIST_LABEL="com.gencan.sse.dev"
    OUT_LOG="service-dev.log"
    ERR_LOG="service-dev.err"
    echo "=== GenCan SSE Service Uninstall & Cleanup (DEV Mode) ==="
else
    PLIST_NAME="com.gencan.sse.plist"
    PLIST_LABEL="com.gencan.sse"
    OUT_LOG="service.log"
    ERR_LOG="service.err"
    echo "=== GenCan SSE Service Uninstall & Cleanup (Production Mode) ==="
fi

# 1. Unload the service if it's loaded
if launchctl list 2>/dev/null | grep -q "$PLIST_LABEL"; then
    echo "Service is currently running. Unloading..."
    launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_NAME" 2>/dev/null || true
    echo "Service unloaded."
else
    echo "Service is not currently running/loaded."
fi

# 2. Remove the Launch Agent plist file
if [ -f "$LAUNCH_AGENTS_DIR/$PLIST_NAME" ]; then
    echo "Removing launchd plist file: $LAUNCH_AGENTS_DIR/$PLIST_NAME"
    rm "$LAUNCH_AGENTS_DIR/$PLIST_NAME"
else
    echo "No plist file found at $LAUNCH_AGENTS_DIR/$PLIST_NAME."
fi

# 3. Clean up specific log files
if [ -f "$LOG_DIR/$OUT_LOG" ]; then
    echo "Removing log file: $LOG_DIR/$OUT_LOG"
    rm "$LOG_DIR/$OUT_LOG"
fi
if [ -f "$LOG_DIR/$ERR_LOG" ]; then
    echo "Removing log file: $LOG_DIR/$ERR_LOG"
    rm "$LOG_DIR/$ERR_LOG"
fi

# Clean up log directory if it is empty
if [ -d "$LOG_DIR" ] && [ -z "$(ls -A "$LOG_DIR")" ]; then
    echo "Removing empty log directory: $LOG_DIR"
    rmdir "$LOG_DIR"
fi

echo "--------------------------------------------------"
echo "GenCan SSE service has been uninstalled successfully!"
echo "All system service artifacts have been cleaned up."
echo "--------------------------------------------------"
