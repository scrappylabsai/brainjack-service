<p align="center">
  <h1 align="center">BrainJack</h1>
  <p align="center"><strong>Voice in. Keystrokes out. On any computer.</strong></p>
</p>

<p align="center">
  <a href="https://testflight.apple.com/join/z8H86Qfj"><img src="https://img.shields.io/badge/iOS_App-TestFlight-blue?logo=apple&logoColor=white" alt="TestFlight"></a>
  <a href="https://brainjack.ai"><img src="https://img.shields.io/badge/website-brainjack.ai-orange" alt="Website"></a>
  <a href="https://discord.gg/ekRv2zJCHT"><img src="https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://brainjack.ai/dongle"><img src="https://img.shields.io/badge/dongle-order_now-e84393" alt="Order Dongle"></a>
  <a href="https://github.com/scrappylabsai/brainjack-service/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-green" alt="Platform">
</p>

---

Speak into your phone. Keystrokes appear on your computer. Not clipboard paste. Not dictation. **Real keystrokes** injected at the OS level — terminal, code editor, AI agent, any app.

Works two ways:

| | **Install the Service** | **Use the USB Dongle** |
|---|---|---|
| **What** | Free software on your computer | Plug-and-play USB device |
| **Install on target?** | Yes (this repo) | **Nothing.** It's a standard keyboard. |
| **Best for** | Developers, self-hosters, BYOK crowd | Everyone else. Corporate machines. Air-gapped systems. |
| **How it works** | Phone → WiFi → Service → OS keystrokes | Phone → WiFi/BLE → Dongle → USB HID keystrokes |

**Both paths require the [BrainJack iOS app](https://testflight.apple.com/join/z8H86Qfj)** — that's where your voice lives.

---

## Get Started

### Step 1: Get the App

**[Download from TestFlight](https://testflight.apple.com/join/z8H86Qfj)** — free during beta, all features unlocked.

### Step 2: Choose Your Path

<details open>
<summary><strong>Path A: macOS App (recommended for Mac)</strong> — drag to Applications</summary>

**[Download BrainJack.dmg](https://stuff.loser.com/public/BrainJack.dmg)** — a native menubar app that handles everything.

1. Open the DMG, drag BrainJack to Applications
2. Launch it — first run automatically sets up Python, venv, and dependencies
3. Scan the QR code with the iOS app to connect
4. Grant Accessibility permission when prompted (optional — needed for keystroke injection)

BrainJack lives in your menubar. It auto-starts on login, shows connection status, and lets you restart the service or re-display the QR code anytime.

</details>

<details>
<summary><strong>Path B: Terminal Install (macOS / Linux / advanced)</strong> — 30 seconds</summary>

```bash
# One-liner install (macOS / Linux)
curl -fsSL https://brainjack.ai/get | bash

# Or clone and install manually
git clone https://github.com/scrappylabsai/brainjack-service.git
cd brainjack-service
./install.sh
```

The installer creates a venv, installs one dependency (`websockets`), generates an auth token, starts the service, and shows a QR code. Scan it with the app. Done.

**macOS**: Grant Accessibility permission to "BrainJack" in System Settings → Privacy & Security → Accessibility.

**Windows**: `powershell -ExecutionPolicy Bypass -File install.ps1`

</details>

<details>
<summary><strong>Path C: Use the USB Dongle (everyone)</strong> — plug and play</summary>

The BrainJack dongle is a pre-flashed USB device that appears as a standard keyboard. Plug it into any computer. The target machine thinks someone is typing on a keyboard.

- No software to install on the target
- No drivers, no admin rights
- Works on BIOS, login screens, air-gapped machines, KVMs
- Works with anything that has USB — since 1995

Your phone connects to the dongle over WiFi or Bluetooth. You speak, the dongle types.

**[Order a dongle →](https://brainjack.ai/dongle)**

</details>

### Step 3: Talk

Open the app. Connect to your computer (QR scan or manual IP). Start speaking.

---

## Who Is This For?

### Developers and AI Agent Users
You live in Claude Code, Cursor, terminals. You want to talk instead of type. BrainJack speaks into whatever has focus — your IDE, your terminal, your AI agent. Agent mode translates natural speech into keyboard actions.

### Corporate Workers (AI is Blocked)
Your company locked down ChatGPT, Copilot, browser extensions — all of it. But they can't block a USB keyboard.

The BrainJack dongle IS a keyboard. IT sees a standard HID device, same as any Logitech or Dell. No network traffic from the work PC, no software process, no extension to flag. **The AI lives on your phone. Your work PC just sees a keyboard.**

### Accessibility
Voice control that works with every app, not just ones that support it. Real keystrokes at the OS level means BrainJack works where platform accessibility tools don't.

### Makers and Robotics
Control anything that accepts text input — robots, IoT devices, Raspberry Pi, Jetson. BrainJack turns your voice into keystrokes on any target with USB or a network connection.

---

## How It's Different

| | **BrainJack** | **Dictation Apps** |
|---|---|---|
| **What it does** | Voice → keystrokes (control) | Voice → text (input) |
| **Works with** | Any app, any OS, terminals, agents, BIOS | Text fields only |
| **Privacy** | 100% local possible. BYOK everything. | Cloud-only, sends data to third parties |
| **Hardware option** | USB dongle — zero software on target | None |
| **Linux** | Yes | Usually no |
| **Offline** | Yes (local ASR + LLM) | No |
| **Setup** | 30 seconds | Account + download + cloud dependency |

---

## BYOK — Bring Your Own Everything

Nothing is locked in. Your ASR server. Your LLM. Your hardware. Your network.

| Component | What you bring | Examples |
|-----------|---------------|----------|
| **ASR** | Any OpenAI-compatible endpoint | Whisper.cpp, Qwen-ASR, Faster Whisper |
| **LLM** | Any OpenAI-compatible endpoint | Ollama, vLLM, Claude, GPT |
| **Target** | Any OS with the service or dongle | macOS, Windows, Linux, headless servers |
| **Connection** | WiFi, BLE, or USB HID | LAN WebSocket, Bluetooth, BrainJack dongle |

Your data never leaves your network unless you want it to.

---

## Features

- **Cross-platform keystrokes** — SendInput (Windows), CGEvents (macOS), xdotool/ydotool (Linux)
- **Agent mode** — LLM translates speech into keyboard actions, app navigation, shell commands
- **Command sheets** — macro palettes for Vim, tmux, VS Code, shell
- **Live mode** — continuous listening, auto-send
- **Multi-device** — add all your machines, switch with a tap
- **Token auth** — HMAC with constant-time comparison
- **TLS** — self-signed or bring your own certs
- **Rate limiting** — per-IP token bucket
- **Audit logging** — JSON lines, never logs keystroke content
- **Zero bloat** — single Python file, one dependency, ~10MB RAM

---

## Detailed Install Guides

<details>
<summary><strong>macOS</strong></summary>

### Prerequisites

| Requirement | Check | Install |
|-------------|-------|---------|
| Python 3.10+ | `python3 --version` | `brew install python` or [python.org](https://python.org) |
| Git | `git --version` | `brew install git` or Xcode CLI Tools |

### Install

```bash
git clone https://github.com/scrappylabsai/brainjack-service.git
cd brainjack-service
./install.sh
```

The installer creates a venv, installs `websockets`, generates an auth token, installs a launchd agent (auto-starts on login), and displays a QR code for phone pairing.

### Grant Accessibility Permission (Required)

1. **System Settings → Privacy & Security → Accessibility**
2. Click **+**, add **BrainJack**
3. Toggle **on**

Without this, the service connects but keystrokes silently fail.

### Verify

```bash
./docs/verify-macos.sh    # All 10 checks should PASS
```

### Service Management

```bash
launchctl list com.brainjack.agent              # Status
launchctl unload ~/Library/LaunchAgents/com.brainjack.agent.plist  # Stop
launchctl load ~/Library/LaunchAgents/com.brainjack.agent.plist    # Start
cat ~/brainjack-service/brainjack.log           # Logs
```

</details>

<details>
<summary><strong>Windows</strong></summary>

### Prerequisites

| Requirement | Check | Install |
|-------------|-------|---------|
| Python 3.10+ | `python --version` | [python.org](https://python.org) or `winget install Python.Python.3.13` |
| Git | `git --version` | [git-scm.com](https://git-scm.com) or `winget install Git.Git` |

No extra tools needed. BrainJack uses the native Win32 `SendInput` API.

### Install

```powershell
git clone https://github.com/scrappylabsai/brainjack-service.git
cd brainjack-service
powershell -ExecutionPolicy Bypass -File install.ps1
```

Adds a firewall rule for port 9898, creates a Startup folder auto-launcher, and starts immediately.

### With TLS

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -TLS
```

### Service Management

```powershell
taskkill /F /IM pythonw.exe          # Stop
.\Start-BrainJack.bat               # Start (Desktop shortcut)
.\install.ps1 -Uninstall            # Remove everything
```

</details>

<details>
<summary><strong>Linux</strong></summary>

### Prerequisites

| Requirement | Check | Install |
|-------------|-------|---------|
| Python 3.10+ | `python3 --version` | Your package manager |
| xdotool (X11) | `which xdotool` | `sudo apt install xdotool` |
| ydotool (Wayland) | `which ydotool` | `sudo apt install ydotool` |

The installer auto-detects X11 vs Wayland.

**Wayland**: `sudo usermod -aG input $USER` then re-login.

### Install

```bash
git clone https://github.com/scrappylabsai/brainjack-service.git
cd brainjack-service
./install.sh
```

### Service Management

```bash
systemctl --user status brainjack-agent      # Status
systemctl --user restart brainjack-agent     # Restart
journalctl --user -u brainjack-agent -f      # Logs
systemctl --user enable brainjack-agent      # Enable on boot
```

</details>

<details>
<summary><strong>Agent-Friendly Quick Start</strong></summary>

If you're using an AI coding agent, paste this and let it handle everything:

```bash
python3 --version   # need 3.10+
git clone https://github.com/scrappylabsai/brainjack-service.git
cd brainjack-service
./install.sh
# macOS: grant Accessibility to "BrainJack" in System Settings
./docs/verify-macos.sh
cat .env | grep BRAINJACK_TOKEN
# Get the iOS app: https://testflight.apple.com/join/z8H86Qfj
```

</details>

---

## Configuration

All config via `.env` or environment variables:

```bash
BRAINJACK_TOKEN=your-secret-token    # Auth (empty = disabled)
BRAINJACK_HOST=0.0.0.0              # Bind address
BRAINJACK_PORT=9898                 # Port
BRAINJACK_TLS_CERT=                 # TLS cert path
BRAINJACK_TLS_KEY=                  # TLS key path
BRAINJACK_BEHIND_PROXY=false        # Reverse proxy mode
BRAINJACK_RATE_LIMIT=30             # Commands per window
BRAINJACK_RATE_WINDOW=10            # Window (seconds)
```

---

## Protocol

JSON over WebSocket. Simple.

```json
{"cmd": "type", "text": "git status"}           // Type text
{"cmd": "key", "key": "Return"}                 // Single key
{"cmd": "combo", "keys": "ctrl+c"}              // Key combo
{"cmd": "status"}                                // Active window info
```

Auth: `ws://host:9898?token=YOUR_TOKEN` or `{"cmd": "auth", "token": "..."}` as first message.

---

## Ecosystem

| Component | What |
|-----------|------|
| **[BrainJack Service](https://github.com/scrappylabsai/brainjack-service)** | This repo — keystroke injection daemon |
| **[BrainJack iOS App](https://testflight.apple.com/join/z8H86Qfj)** | Voice control with ASR, agent mode, multi-device |
| **[BrainJack Dongle](https://brainjack.ai/dongle)** | USB dongle — zero software on target, order now |
| **[brainjack.ai](https://brainjack.ai)** | Website, interactive demo, setup guide |

---

## Talk to Us

We're a small team and we build what people need. Custom firmware, workflow integrations, accessibility adaptations, enterprise setups — if you have an idea, we want to hear it.

- **[Discord](https://discord.gg/ekRv2zJCHT)** — community, setup help, beta feedback
- **[GitHub Discussions](https://github.com/scrappylabsai/brainjack-service/discussions)** — feature requests, show off your setup, get help
- **Email** — [brian@scrappylabs.ai](mailto:brian@scrappylabs.ai) — direct line, real human, fast reply
- **Beta testers** — [join on TestFlight](https://testflight.apple.com/join/z8H86Qfj) and tell us what's broken or missing

BrainJack is built by people who use it every day. Your feedback shapes what ships next.

---

## License

[Apache License 2.0](LICENSE)

---

<p align="center">
  Built by <a href="https://scrappylabs.ai">ScrappyLabs</a> · <a href="https://brainjack.ai">brainjack.ai</a> · <a href="https://brainjack.ai/demo">Interactive Demo</a>
</p>
