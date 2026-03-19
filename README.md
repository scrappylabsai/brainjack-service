<p align="center">
  <h1 align="center">BrainJack Agent</h1>
  <p align="center"><strong>Voice goes in, keystrokes come out. On any computer. No software install on the target.</strong></p>
</p>

<p align="center">
  <a href="https://github.com/scrappylabsai/brainjack-agent/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-BSL%201.1-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-green" alt="Platform">
  <img src="https://img.shields.io/badge/WebSocket-wss%3A%2F%2F-purple" alt="WebSocket">
</p>

---

BrainJack Agent is a WebSocket daemon that receives text injection commands over the network and types them into whatever application has focus. Speak into your phone, the words appear on your computer. No clipboard sharing apps, no cloud services, no browser extensions.

It runs as a background service on any Windows, macOS, or Linux machine and accepts commands from the [BrainJack iOS app](https://brainjack.ai), a Flipper Zero running [ShellDrop](https://github.com/scrappylabsai/shelldrop-flipper), or an [ESP32-S3 HID dongle](https://github.com/scrappylabsai/brainjack-hid) -- or anything that can open a WebSocket and send JSON.

## How It Works

```
Phone (voice)  ──>  ASR (on-device)  ──>  WebSocket  ──>  BrainJack Agent  ──>  Keystrokes
                                                              │
                                              SendInput (Windows) │  osascript (macOS)
                                              xdotool (X11)       │  ydotool (Wayland)
```

1. You speak into the BrainJack mobile app (or any WebSocket client)
2. Speech is transcribed on-device (local-first ASR, nothing leaves your network)
3. The transcript is sent as a JSON command over WebSocket
4. The agent injects keystrokes into whatever window has focus

No drivers. No accessibility APIs to configure. No per-app integrations. If it accepts keyboard input, BrainJack can type into it.

## Features

- **Cross-platform injection** -- SendInput (Windows), osascript (macOS), xdotool (X11), ydotool (Wayland)
- **Four command types** -- `type` (text), `key` (single key), `combo` (modifier combos like Ctrl+C), `status` (active window info)
- **Token authentication** -- HMAC-compared bearer tokens via query string or first-message handshake
- **TLS support** -- Native `ssl` module, auto-generates self-signed certs with `--tls`
- **Per-IP rate limiting** -- Token bucket algorithm, configurable burst and window
- **Audit logging** -- JSON lines with rotation, never logs keystroke content
- **Reverse proxy mode** -- Trusts X-Forwarded-For, binds localhost, skips TLS (proxy handles it)
- **Zero dependencies** -- Single `websockets` pip package. That's it.
- **Service files included** -- systemd (Linux) and launchd (macOS), installed automatically

## Quick Start

### Windows

```powershell
git clone https://github.com/scrappylabsai/brainjack-agent.git
cd brainjack-agent

# Install (creates venv, generates auth token, sets up auto-start)
powershell -ExecutionPolicy Bypass -File install.ps1

# Or with TLS:
powershell -ExecutionPolicy Bypass -File install.ps1 -TLS
```

### macOS / Linux

```bash
git clone https://github.com/scrappylabsai/brainjack-agent.git
cd brainjack-agent

# Install (creates venv, generates auth token, installs service)
./install.sh

# Or with TLS:
./install.sh --tls
```

The installer:
1. Creates a Python venv and installs dependencies
2. Generates a secure auth token (saved to `.env`)
3. Sets up auto-start (Startup folder on Windows / launchd on macOS / systemd on Linux)
4. Configures firewall rules (Windows) or installs input tools (Linux)

> **macOS users:** You must grant Accessibility permission for keystroke injection to work. See the [detailed macOS install guide](docs/INSTALL-MACOS.md) for step-by-step instructions, troubleshooting, and a verification script.

After install, the agent is running on port `9898`. The auth token is printed to stdout -- copy it to your client app.

### Manual Start

```bash
# Activate venv
source .venv/bin/activate

# Run directly
python agent.py

# With options
python agent.py --host 0.0.0.0 --port 9898 --tls-cert certs/brainjack.pem --tls-key certs/brainjack-key.pem
```

## Protocol

All commands are JSON over WebSocket. The agent responds with JSON.

### Authentication

```json
// Option 1: Query string
// Connect to ws://localhost:9898?token=YOUR_TOKEN

// Option 2: First message handshake
{"cmd": "auth", "token": "YOUR_TOKEN"}
// Response: {"ok": true, "authed": true}
```

### Commands

```json
// Type text at cursor
{"cmd": "type", "text": "Hello, world!"}

// Press a single key
{"cmd": "key", "key": "Return"}

// Key combo (modifiers + key)
{"cmd": "combo", "keys": "ctrl+c"}
{"cmd": "combo", "keys": "cmd+shift+s"}

// Get status (active window, hostname, platform)
{"cmd": "status"}
// Response: {"device": "myhost", "os": "linux-x11", "active_window": "Terminal"}
```

### Supported Keys

`Return`, `Tab`, `Escape`, `Backspace`, `Delete`, `Space`, arrow keys, `Home`, `End`, `PageUp`, `PageDown`, `F1`-`F12`, `Insert`, `CapsLock`, `PrintScreen`

### Modifiers

`ctrl`, `alt`, `shift`, `cmd`/`gui`/`meta`/`super` (mapped correctly per platform)

## Configuration

All config is via `.env` file or environment variables. CLI flags override both.

```bash
# Auth (leave empty or "off" to disable)
BRAINJACK_TOKEN=your-secret-token

# Network
BRAINJACK_HOST=0.0.0.0
BRAINJACK_PORT=9898

# TLS (paths to PEM files)
BRAINJACK_TLS_CERT=
BRAINJACK_TLS_KEY=

# Reverse proxy mode (binds localhost, trusts XFF, skips TLS)
BRAINJACK_BEHIND_PROXY=false

# Rate limiting
BRAINJACK_RATE_LIMIT=30       # Max commands per window
BRAINJACK_RATE_WINDOW=10      # Window in seconds
BRAINJACK_RATE_BURST=5        # Burst allowance

# Audit logging
BRAINJACK_AUDIT_LOG=           # Path to log file (empty = stderr only)
BRAINJACK_AUDIT_MAX_BYTES=10485760
BRAINJACK_AUDIT_BACKUP_COUNT=5
```

## Architecture

```
agent.py (683 lines, single file)
├── WebSocket server (websockets library)
├── Authentication (HMAC token compare, query string or handshake)
├── Rate limiter (token bucket per IP)
├── Command dispatcher
│   ├── inject_text()   → xdotool type / ydotool type / osascript keystroke
│   ├── inject_key()    → xdotool key / ydotool key / osascript key code
│   ├── inject_combo()  → modifier + key combos per platform
│   └── get_context()   → active window name, hostname, platform
├── Audit logger (JSON lines, rotating file handler)
└── TLS (stdlib ssl, self-signed cert generation via install.sh)
```

The entire agent is a single Python file with one external dependency (`websockets`). Platform detection is automatic. Key name mapping handles the translation between universal names (ENTER, BACKSPACE) and platform-specific representations (xdotool's `Return`, ydotool's keycode `28`, osascript's key code `36`).

## Security Model

- **Token auth** is constant-time compared (HMAC) to prevent timing attacks
- **Audit logs** record connection events and command types but **never log keystroke content**
- **Rate limiting** prevents abuse from any single IP
- **TLS** encrypts the WebSocket connection (self-signed certs generated by installer, or bring your own)
- **Proxy mode** lets you put nginx/caddy/Cloudflare Tunnel in front for proper certs

This is designed for private networks. The agent types keystrokes into your computer -- treat the auth token like a password.

## Platform Requirements

| Platform | Tool | Install |
|----------|------|---------|
| Windows | None | Built-in (Win32 SendInput API via ctypes) |
| macOS | `osascript` | Built-in (requires Accessibility permission) |
| Linux (X11) | `xdotool` | `sudo apt install xdotool` or `sudo pacman -S xdotool` |
| Linux (Wayland) | `ydotool` | `sudo apt install ydotool` or `sudo pacman -S ydotool` |

**macOS note:** System Settings > Privacy & Security > Accessibility -- grant permission to the Python binary (not Terminal). See [docs/INSTALL-MACOS.md](docs/INSTALL-MACOS.md) for the exact path and a verification script (`docs/verify-macos.sh`).

### Windows Notes

No extra tools needed beyond Python 3.10+. The agent uses the native Win32 `SendInput` API via ctypes.

**Why a Startup folder script instead of a Scheduled Task?**

Windows has a quirk: the `SendInput` API can only inject keystrokes into the **interactive desktop** -- the one you see on your monitor. When a process is launched by a Scheduled Task (or via SSH, RDP, or any remote management tool), Windows puts it on a separate, invisible desktop. The process *thinks* it's injecting keystrokes (the API returns success), but nothing appears on screen.

The Startup folder doesn't have this problem. Programs launched from `shell:startup` run in the same desktop session you're looking at, so `SendInput` works as expected.

The installer creates:
- **`brainjack.vbs`** in your Startup folder -- launches the agent hidden (no console window) every time you log in
- **`Start-BrainJack.bat`** on your Desktop -- double-click to start manually if the agent isn't running

**Microsoft Account / Windows Hello:**

If you sign into Windows with a Microsoft account (email + PIN/fingerprint/face), auto-login at boot isn't possible without third-party tools. The agent will start automatically once you log in -- you just need to complete the Windows Hello sign-in first. This is a Windows limitation, not a BrainJack one.

**Firewall:**

The installer adds a firewall rule allowing inbound TCP on port 9898 across all network profiles (Private, Public, Domain). Windows often classifies WiFi networks as "Public" even on your home network, so restricting to Private-only would silently block connections.

## Service Management

```powershell
# Windows
# Start:     Double-click Start-BrainJack.bat on Desktop
# Stop:      taskkill /F /IM pythonw.exe
# Uninstall: .\install.ps1 -Uninstall
```

```bash
# macOS (launchd)
launchctl list com.brainjack.agent
launchctl unload ~/Library/LaunchAgents/com.brainjack.agent.plist
launchctl load ~/Library/LaunchAgents/com.brainjack.agent.plist

# Linux (systemd user service)
systemctl --user status brainjack-agent
systemctl --user restart brainjack-agent
journalctl --user -u brainjack-agent -f
```

## BrainJack Ecosystem

| Component | Description |
|-----------|-------------|
| **[BrainJack Agent](https://github.com/scrappylabsai/brainjack-agent)** | This repo. WebSocket daemon that injects keystrokes. |
| **[BrainJack HID](https://github.com/scrappylabsai/brainjack-hid)** | ESP32-S3 USB dongle. Plugs into any computer, receives text over WiFi, types via native USB HID. No software install on target. |
| **[ShellDrop FAP](https://github.com/scrappylabsai/shelldrop-flipper)** | Flipper Zero app with voice-to-keystroke, fleet commands, and AI input. |
| **[ShellDrop Bridge](https://github.com/scrappylabsai/shelldrop-bridge)** | ESP32-S2 WiFi bridge firmware for the Flipper Zero WiFi Dev Board. |
| **[ShellCast](https://github.com/scrappylabsai/shellcast)** | WebSocket audio relay. Push TTS/audio from servers to phones/speakers. |

## Contributing

PRs welcome. The codebase is intentionally small -- a single-file agent with one dependency. If your change adds a dependency, it better be worth it.

1. Fork the repo
2. Create a feature branch
3. Submit a PR with a clear description of what and why

## License

[Business Source License 1.1](LICENSE) — free for personal and non-commercial use. Converts to Apache 2.0 on 2030-03-09. Commercial use requires a [license from ScrappyLabs](mailto:brian@scrappylabs.ai).

---

Built by [ScrappyLabs](https://scrappylabs.ai) | [brainjack.ai](https://brainjack.ai)
