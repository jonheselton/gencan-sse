#!/bin/bash
# uninstall_service.sh - Unload and remove the GenCan SSE Launch Agent and all associated artifacts.
set -e

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.gencan.sse.plist"
LOG_DIR="$HOME/Library/Logs/gencan-sse"

echo "=== GenCan SSE Service Uninstall & Cleanup ==="

# 1. Unload the service if it's loaded
if launchctl list 2>/dev/null | grep -q "com.gencan.sse"; then
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

# 3. Clean up log directory and files
if [ -d "$LOG_DIR" ]; then
    echo "Removing logs and log directory: $LOG_DIR"
    rm -rf "$LOG_DIR"
else
    echo "No log directory found at $LOG_DIR."
fi

echo "--------------------------------------------------"
echo "GenCan SSE service has been uninstalled successfully!"
echo "All system service artifacts have been cleaned up."
echo "--------------------------------------------------"
