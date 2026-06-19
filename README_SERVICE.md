# GenCan SSE: macOS System Service Guide

This document explains how to set up `gencan-server` as a macOS system service (Launch Agent) that runs automatically when you log in, and how to completely remove it and clean up all associated artifacts.

---

## How It Works

macOS uses `launchd` to manage system services and agents.
By installing a property list (`.plist`) file into your user's `~/Library/LaunchAgents` directory, macOS will:
1. Start `gencan-server` immediately when loaded.
2. Start it automatically on user login.
3. Automatically restart/keep the service alive if it crashes (via the `KeepAlive` key).
4. Run inside the project directory so it can access local configurations.
5. Pipe the standard output and standard error logs to standard log files under `~/Library/Logs/gencan-sse/`.

Because `launchd` runs in a clean environment that does not inherit terminal shell profiles, the service wrapper starts under `/bin/zsh` to source your `~/.zshrc` profile, ensuring that your `GEMINI_API_KEY` (or `AI_STUDIO_KEY`) environment variable is correctly loaded.

---

## 1. Quick Setup (Automated)

We have provided a helper script that does everything for you:

```bash
# 1. Make the script executable
chmod +x setup_service.sh

# 2. Run the setup script
./setup_service.sh
```

This will automatically:
- Create the logs folder at `~/Library/Logs/gencan-sse/`.
- Generate the `~/Library/LaunchAgents/com.gencan.sse.plist` file with absolute paths mapped to your project directory.
- Load and start the service.

---

## 2. Managing the Service

Once installed, you can manage the service using the following commands:

### Check Status
Check if the service is loaded and see its PID and exit code:
```bash
launchctl list | grep com.gencan.sse
```

### Stop / Unload the Service
This stops the service and prevents it from running on next login:
```bash
launchctl unload ~/Library/LaunchAgents/com.gencan.sse.plist
```

### Start / Load the Service
If you previously unloaded it, you can load it back:
```bash
launchctl load ~/Library/LaunchAgents/com.gencan.sse.plist
```

### View Service Logs
The stdout and stderr of the service are written to files. You can monitor them in real-time:
```bash
# View standard output logs (FastAPI startup messages, request logs)
tail -f ~/Library/Logs/gencan-sse/service.log

# View errors (python tracebacks, startup failures)
tail -f ~/Library/Logs/gencan-sse/service.err
```

---

## 3. Testing the Running Daemon

To verify that the service is running and properly processing requests, send a test curl request to the daemon:

```bash
curl -X POST http://127.0.0.1:8765/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "GenCan speech engine system service is running successfully!"}'
```

---

## 4. Uninstalling and Cleaning Up

To completely remove the service and all of its artifacts from your system, you can run the automated uninstall script:

```bash
# 1. Make the script executable
chmod +x uninstall_service.sh

# 2. Run the uninstall script
./uninstall_service.sh
```

### Manual Teardown and Cleanup Steps
If you prefer to perform the removal and cleanup manually, execute the following commands in your terminal:

1. **Stop and Unload the Service**:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.gencan.sse.plist 2>/dev/null || true
   ```

2. **Delete the Launch Agent Plist File**:
   ```bash
   rm -f ~/Library/LaunchAgents/com.gencan.sse.plist
   ```

3. **Delete the Log Directory and Files**:
   ```bash
   rm -rf ~/Library/Logs/gencan-sse
   ```

This will leave no trace of the service or its logs on your machine.
