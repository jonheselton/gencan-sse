#!/bin/bash
# setup_service.sh - Setup and launch the GenCan SSE daemon as a macOS Launch Agent.
set -e

# Determine the absolute path of the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
    SERVER_ARGS="--dev --host 0.0.0.0"
    OUT_LOG="service-dev.log"
    ERR_LOG="service-dev.err"
    echo "=== GenCan SSE Service Setup (DEV Mode) ==="
else
    PLIST_NAME="com.gencan.sse.plist"
    PLIST_LABEL="com.gencan.sse"
    SERVER_ARGS="--host 0.0.0.0"
    OUT_LOG="service.log"
    ERR_LOG="service.err"
    echo "=== GenCan SSE Service Setup (Production Mode) ==="
fi

# 1. Verify virtual environment exists
if [ ! -f "$PROJECT_DIR/.venv/bin/gencan-server" ]; then
    echo "Error: Virtual environment or gencan-server executable not found at $PROJECT_DIR/.venv/bin/gencan-server." >&2
    echo "Please ensure the project is installed in the virtual environment (.venv)." >&2
    exit 1
fi

# 2. Create the logs directory if it doesn't exist
echo "Creating log directory at $LOG_DIR..."
mkdir -p "$LOG_DIR"

# 3. Generate the Launch Agent plist file with absolute paths
echo "Generating launchd plist at $LAUNCH_AGENTS_DIR/$PLIST_NAME..."
cat <<EOF > "$LAUNCH_AGENTS_DIR/$PLIST_NAME"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-c</string>
        <string>source \$HOME/.zshrc; exec $PROJECT_DIR/.venv/bin/gencan-server $SERVER_ARGS</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/$OUT_LOG</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/$ERR_LOG</string>
</dict>
</plist>
EOF

# 4. Set appropriate file permissions (LaunchAgents plist should be 644)
chmod 644 "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

# 5. Load the service
echo "Loading service via launchctl..."
# Unload first to ensure any running instance/older plist is replaced and stopped
launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_NAME" 2>/dev/null || true
launchctl load "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo "--------------------------------------------------"
echo "GenCan SSE service has been installed and started!"
echo "It is configured to run automatically when you log in."
echo ""
echo "Verify status:"
echo "  launchctl list | grep $PLIST_LABEL"
echo ""
echo "View logs:"
echo "  tail -f $LOG_DIR/$OUT_LOG"
echo "  tail -f $LOG_DIR/$ERR_LOG"
echo "--------------------------------------------------"
