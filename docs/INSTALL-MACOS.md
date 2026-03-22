# BrainJack Agent -- macOS Install Guide

> Tested on macOS 15 (Sequoia) and macOS 26 (Tahoe), Apple Silicon (M-series) and Intel.

## Prerequisites

- **Python 3.10+** (Homebrew recommended: `brew install python`)
- **Git** (`brew install git` or Xcode command line tools)

## Install

```bash
git clone https://github.com/scrappylabsai/brainjack-service.git
cd brainjack-service
./install.sh
```

The installer will:

1. Create a Python virtual environment (`.venv/`)
2. Install the single dependency (`websockets`)
3. Generate a `.env` file with a unique auth token
4. Install a **launchd** agent that starts automatically on login

Your auth token is printed at the end -- copy it into the BrainJack iOS app under **Settings > Device > Auth Token**.

### With TLS (optional)

```bash
./install.sh --tls
```

Generates a self-signed certificate in `certs/` and configures the agent to use it. Useful if the agent is exposed beyond your local network.

## Grant Accessibility Permission

macOS requires explicit permission for any app that types keystrokes. **Without this, the agent connects but keystrokes won't be injected** (text still works via clipboard paste).

1. Open **System Settings** > **Privacy & Security** > **Accessibility**

   Or run:
   ```bash
   open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
   ```

2. Click the **+** button (you may need to unlock with your password)

3. Navigate to `~/brainjack-service/` and select **BrainJack.app**

4. Toggle **BrainJack.app** ON in the Accessibility list

5. Restart the agent:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.brainjack.agent.plist
   launchctl load ~/Library/LaunchAgents/com.brainjack.agent.plist
   ```

### Verify Accessibility Works

```bash
cd ~/brainjack-service
./docs/verify-macos.sh
```

Check line 9 — it should say `PASS Accessibility: granted (CGEvents)`. If it says FAIL, repeat the steps above.

## Service Management

```bash
# Check status
launchctl list com.brainjack.agent

# View logs
tail -f ~/brainjack-service/brainjack.log

# Stop
launchctl unload ~/Library/LaunchAgents/com.brainjack.agent.plist

# Start
launchctl load ~/Library/LaunchAgents/com.brainjack.agent.plist

# Restart (stop + start)
launchctl unload ~/Library/LaunchAgents/com.brainjack.agent.plist && \
launchctl load ~/Library/LaunchAgents/com.brainjack.agent.plist
```

The agent starts automatically on login via launchd (`KeepAlive = true`).

## Connect from the iOS App

1. Open BrainJack on your iPhone
2. Tap **+** to add a device
3. Enter:
   - **Name**: your Mac's name (e.g., "Work Mac")
   - **OS**: macOS
   - **WiFi IP**: `YOUR_MAC_IP:9898`
   - **Auth Token**: the token from install (find it with `grep BRAINJACK_TOKEN ~/brainjack-service/.env`)
4. Tap **Connect**

The connection indicator should turn green. Speak into the mic -- your words appear wherever the cursor is on your Mac.

### QR Code Setup (faster)

Visit [brainjack.ai/setup](https://brainjack.ai/setup), fill in your Mac's IP and token, and scan the generated QR code from the BrainJack app.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Agent not running after reboot | Check `launchctl list com.brainjack.agent` -- PID should be present. If not, re-run `./install.sh` |
| "Not authorized" or keystrokes don't work | Grant Accessibility permission to BrainJack.app (see above) |
| Connection refused on port 9898 | Check firewall: System Settings > Network > Firewall. Add Python or disable for testing |
| Auth fails from iOS app | Verify token matches: `grep BRAINJACK_TOKEN ~/brainjack-service/.env` |
| Agent crashes on Python 3.14+ | Check `~/brainjack-service/brainjack.log` -- if `websockets` import fails, update it: `.venv/bin/pip install -U websockets` |
| Keystrokes go to wrong app | BrainJack types into whatever window has focus. Click the target app first |

## Uninstall

```bash
# Stop and remove the launchd agent
launchctl unload ~/Library/LaunchAgents/com.brainjack.agent.plist
rm ~/Library/LaunchAgents/com.brainjack.agent.plist

# Remove the agent directory
rm -rf ~/brainjack-service

# Remove Accessibility permission
# System Settings > Privacy & Security > Accessibility > remove BrainJack.app
```

## Configuration

All settings are in `~/brainjack-service/.env`. See the main [README](../README.md#configuration) for full reference.

Key settings for macOS:

| Setting | Default | Notes |
|---------|---------|-------|
| `BRAINJACK_HOST` | `0.0.0.0` | Binds all interfaces. Use `127.0.0.1` for local-only |
| `BRAINJACK_PORT` | `9898` | Change if port conflicts |
| `BRAINJACK_TOKEN` | auto-generated | Treat like a password |

## How It Works on macOS

BrainJack uses **Quartz CGEvents** (Accessibility API) for keystroke injection:

- **Text**: clipboard paste via `pbcopy` + CGEvent Cmd+V
- **Keys**: `CGEventCreateKeyboardEvent` with macOS virtual keycodes
- **Combos**: CGEvent key press with modifier flags (Cmd, Ctrl, Shift, Option)

This uses the same low-level API that macOS automation tools like Keyboard Maestro use. It works with any application that accepts keyboard input -- native apps, Electron apps, Terminal, browsers, everything.

On systems without `pyobjc-framework-Quartz`, BrainJack falls back to `osascript` (AppleScript via System Events), which requires a separate Automation permission.
