#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# BrainJack — One-line installer for macOS & Linux
#
#   curl -fsSL https://brainjack.ai/get | bash
#
# Downloads the agent, creates a venv, generates an auth token,
# installs a background service, and opens a QR code for pairing.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

# ── Branding ─────────────────────────────────────────────────
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

INSTALL_DIR="$HOME/.brainjack"
REPO="scrappylabsai/brainjack-agent"
BRANCH="main"
MIN_PYTHON="3.10"

banner() {
    echo ""
    echo -e "${BOLD}  ██████╗ ██████╗  █████╗ ██╗███╗   ██╗     ██╗ █████╗  ██████╗██╗  ██╗${NC}"
    echo -e "${BOLD}  ██╔══██╗██╔══██╗██╔══██╗██║████╗  ██║     ██║██╔══██╗██╔════╝██║ ██╔╝${NC}"
    echo -e "${BOLD}  ██████╔╝██████╔╝███████║██║██╔██╗ ██║     ██║███████║██║     █████╔╝ ${NC}"
    echo -e "${BOLD}  ██╔══██╗██╔══██╗██╔══██║██║██║╚██╗██║██   ██║██╔══██║██║     ██╔═██╗ ${NC}"
    echo -e "${BOLD}  ██████╔╝██║  ██║██║  ██║██║██║ ╚████║╚█████╔╝██║  ██║╚██████╗██║  ██╗${NC}"
    echo -e "${BOLD}  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝ ╚════╝ ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝${NC}"
    echo -e "${DIM}  Voice goes in, keystrokes come out.${NC}"
    echo ""
}

step()  { echo -e "  ${GREEN}▸${NC} ${BOLD}$1${NC}"; }
info()  { echo -e "  ${DIM}  $1${NC}"; }
warn()  { echo -e "  ${YELLOW}!${NC} $1"; }
fail()  { echo -e "  ${RED}✗${NC} $1"; exit 1; }
ok()    { echo -e "  ${GREEN}✓${NC} $1"; }

# ── Pre-flight checks ───────────────────────────────────────
banner

OS="$(uname -s)"
ARCH="$(uname -m)"

if [ "$OS" = "Darwin" ]; then
    PLATFORM="macOS"
elif [ "$OS" = "Linux" ]; then
    PLATFORM="Linux"
else
    fail "Unsupported OS: $OS. For Windows, use: irm brainjack.ai/install.ps1 | iex"
fi

step "Detected $PLATFORM ($ARCH)"

# Check Python
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        if [ -n "$VER" ]; then
            MAJOR=$(echo "$VER" | cut -d. -f1)
            MINOR=$(echo "$VER" | cut -d. -f2)
            if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ]; then
                PYTHON="$cmd"
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python 3.10+ required. Install it first:
      macOS:  brew install python
      Linux:  sudo apt install python3  (or your distro's package manager)"
fi

ok "Python: $($PYTHON --version 2>&1)"

# Check curl or wget
DOWNLOADER=""
if command -v curl &>/dev/null; then
    DOWNLOADER="curl"
elif command -v wget &>/dev/null; then
    DOWNLOADER="wget"
else
    fail "curl or wget required. Install one first."
fi

# ── Download agent ───────────────────────────────────────────
step "Installing to $INSTALL_DIR"

mkdir -p "$INSTALL_DIR"

# Files we need from the repo
FILES="agent.py requirements.txt .env.template com.brainjack.agent.plist brainjack-agent.service .gitignore"
BASE_URL="https://raw.githubusercontent.com/$REPO/$BRANCH"

download() {
    local url="$1"
    local dest="$2"
    if [ "$DOWNLOADER" = "curl" ]; then
        curl -fsSL "$url" -o "$dest"
    else
        wget -q "$url" -O "$dest"
    fi
}

for file in $FILES; do
    download "$BASE_URL/$file" "$INSTALL_DIR/$file" 2>/dev/null || true
done

# Verify the critical file downloaded
if [ ! -f "$INSTALL_DIR/agent.py" ]; then
    fail "Download failed. Check your internet connection and try again."
fi

ok "Downloaded"

# ── Python venv ──────────────────────────────────────────────
step "Setting up Python environment"

"$PYTHON" -m venv "$INSTALL_DIR/.venv" 2>/dev/null || {
    # Some systems need ensurepip
    "$PYTHON" -m venv --without-pip "$INSTALL_DIR/.venv"
    download "https://bootstrap.pypa.io/get-pip.py" "/tmp/get-pip.py"
    "$INSTALL_DIR/.venv/bin/python" /tmp/get-pip.py -q
    rm -f /tmp/get-pip.py
}

"$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt" 2>/dev/null

ok "Dependencies installed (websockets)"

# ── Configuration ────────────────────────────────────────────
step "Generating configuration"

if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.template" "$INSTALL_DIR/.env"
fi

# Generate token if not set
CURRENT_TOKEN=$(grep '^BRAINJACK_TOKEN=' "$INSTALL_DIR/.env" 2>/dev/null | sed 's/^BRAINJACK_TOKEN=//' || true)
if [ -z "$CURRENT_TOKEN" ]; then
    TOKEN=$("$PYTHON" -c "import secrets; print(secrets.token_urlsafe(32))")
    if [ "$OS" = "Darwin" ]; then
        sed -i '' "s|^BRAINJACK_TOKEN=.*|BRAINJACK_TOKEN=$TOKEN|" "$INSTALL_DIR/.env"
    else
        sed -i "s|^BRAINJACK_TOKEN=.*|BRAINJACK_TOKEN=$TOKEN|" "$INSTALL_DIR/.env"
    fi
else
    TOKEN="$CURRENT_TOKEN"
fi

ok "Auth token generated"

# ── Input injection tools (Linux only) ───────────────────────
if [ "$OS" = "Linux" ]; then
    if [ -n "${WAYLAND_DISPLAY:-}" ]; then
        if ! command -v ydotool &>/dev/null; then
            warn "ydotool not found — install it for Wayland keystroke injection:"
            info "sudo apt install ydotool  OR  sudo pacman -S ydotool"
        fi
    else
        if ! command -v xdotool &>/dev/null; then
            warn "xdotool not found — install it for X11 keystroke injection:"
            info "sudo apt install xdotool  OR  sudo pacman -S xdotool"
        fi
    fi
fi

# ── Install background service ───────────────────────────────
step "Installing background service"

if [ "$OS" = "Darwin" ]; then
    PLIST_DST="$HOME/Library/LaunchAgents/com.brainjack.agent.plist"
    sed "s|AGENT_DIR_PLACEHOLDER|$INSTALL_DIR|g" "$INSTALL_DIR/com.brainjack.agent.plist" > "$PLIST_DST"
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    ok "macOS LaunchAgent installed (auto-starts on login)"
else
    mkdir -p ~/.config/systemd/user
    # Rewrite the service file for the install location
    cat > ~/.config/systemd/user/brainjack-agent.service <<UNIT
[Unit]
Description=BrainJack Service
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/agent.py
Restart=always
RestartSec=5
EnvironmentFile=$INSTALL_DIR/.env

[Install]
WantedBy=default.target
UNIT
    systemctl --user daemon-reload
    systemctl --user enable --now brainjack-agent.service 2>/dev/null
    ok "systemd user service installed (auto-starts on login)"
fi

# ── Verify it's running ──────────────────────────────────────
sleep 1
PORT=$(grep '^BRAINJACK_PORT=' "$INSTALL_DIR/.env" | sed 's/^BRAINJACK_PORT=//' || echo "9898")
PORT="${PORT:-9898}"

RUNNING=false
for i in 1 2 3; do
    if "$INSTALL_DIR/.venv/bin/python" -c "
import asyncio, websockets, json
async def t():
    async with websockets.connect('ws://127.0.0.1:$PORT?token=$TOKEN') as ws:
        await ws.send(json.dumps({'cmd':'status'}))
        r = json.loads(await ws.recv())
        print(r.get('hostname',''))
asyncio.run(t())
" &>/dev/null; then
        RUNNING=true
        break
    fi
    sleep 1
done

if [ "$RUNNING" = true ]; then
    ok "Service running on port $PORT"
else
    warn "Agent may still be starting. Check logs:"
    if [ "$OS" = "Darwin" ]; then
        info "tail -f $INSTALL_DIR/brainjack.log"
    else
        info "journalctl --user -u brainjack-agent -f"
    fi
fi

# ── macOS: Accessibility permission ──────────────────────────
if [ "$OS" = "Darwin" ]; then
    echo ""
    step "Accessibility Permission (required for keystroke injection)"
    echo ""
    echo -e "  ${YELLOW}macOS requires you to grant Accessibility permission.${NC}"
    echo -e "  ${YELLOW}Without this, the agent connects but keystrokes won't type.${NC}"
    echo ""
    echo -e "  ${BOLD}1.${NC} System Settings will open to the right page"
    echo -e "  ${BOLD}2.${NC} Click the ${BOLD}+${NC} button (unlock if needed)"
    echo -e "  ${BOLD}3.${NC} Press ${BOLD}Cmd+Shift+G${NC} and paste this path:"
    echo ""

    # Find the actual Python.app path (resolve venv symlinks)
    PYTHON_REAL=$("$INSTALL_DIR/.venv/bin/python" -c "import sys, os; print(os.path.realpath(sys.executable))" 2>/dev/null)
    PYTHON_APP=$(echo "$PYTHON_REAL" | sed 's|/bin/python[0-9.]*|/Resources/Python.app|' 2>/dev/null || true)
    if [ -d "$PYTHON_APP" ]; then
        echo -e "     ${GREEN}$PYTHON_APP${NC}"
    else
        # Fallback: show the framework directory
        PYTHON_FW=$(echo "$PYTHON_REAL" | sed 's|/bin/python[0-9.]*$||')
        echo -e "     ${GREEN}$PYTHON_FW${NC}"
    fi

    echo ""
    echo -e "  ${BOLD}4.${NC} Toggle it ${GREEN}ON${NC}"
    echo ""

    # Open System Settings
    open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" 2>/dev/null || true
fi

# ── Get local IP ─────────────────────────────────────────────
if [ "$OS" = "Darwin" ]; then
    LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "YOUR_IP")
else
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "YOUR_IP")
fi

# ── Generate QR code page ────────────────────────────────────
HOSTNAME_SHORT=$(hostname -s 2>/dev/null || hostname)
QR_HTML="/tmp/brainjack-setup-$HOSTNAME_SHORT.html"

cat > "$QR_HTML" << 'QREOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BrainJack — Scan to Connect</title>
<script src="https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    min-height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    background: #0F1419; color: #F0F4F8;
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', system-ui, sans-serif;
  }
  .card {
    background: #1A2332; border: 1px solid #374151; border-radius: 20px;
    padding: 48px; text-align: center; max-width: 440px;
    box-shadow: 0 12px 40px rgba(0,0,0,0.5);
  }
  h1 { font-size: 28px; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 4px; }
  .subtitle { font-size: 15px; color: #8899AA; margin-bottom: 28px; }
  #qr-container {
    background: #fff; border-radius: 12px; padding: 20px;
    display: inline-block; margin-bottom: 28px;
  }
  #qr-container canvas { display: block; }
  .info {
    text-align: left; font-size: 14px; color: #8899AA; line-height: 2;
    border-top: 1px solid #374151; padding-top: 20px;
  }
  .info strong { color: #F0F4F8; }
  .token {
    font-family: 'SF Mono', 'JetBrains Mono', monospace; font-size: 12px;
    background: #0F1419; padding: 3px 8px; border-radius: 4px;
    word-break: break-all; display: inline-block; margin-top: 2px;
  }
  .badge {
    display: inline-block; background: #1a3a1a; color: #4ade80;
    font-size: 12px; font-weight: 600; padding: 2px 10px;
    border-radius: 8px; margin-left: 6px;
  }
  .step-hint {
    margin-top: 24px; padding: 16px; background: #0F1419;
    border: 1px solid #374151; border-radius: 10px;
    font-size: 13px; color: #8899AA; text-align: left;
  }
  .step-hint strong { color: #3B82F6; }
  .check { color: #22C55E; }
</style>
</head>
<body>
<div class="card">
  <h1>BrainJack</h1>
  <p class="subtitle">Scan with the BrainJack app to connect</p>
  <div id="qr-container"></div>
  <div class="info">
    <strong>Device:</strong> <span id="d-name"></span> <span class="badge" id="d-os"></span><br>
    <strong>Address:</strong> <span id="d-addr"></span><br>
    <strong>Token:</strong> <span class="token" id="d-token"></span>
  </div>
  <div class="step-hint">
    <strong>Next:</strong> Open BrainJack on your iPhone &rarr; tap <strong>+</strong> &rarr; <strong>Scan QR Code</strong><br>
    <span class="check">&#10003;</span> Service installed &nbsp;
    <span class="check">&#10003;</span> Service running &nbsp;
    <span id="accessibility-status"></span>
  </div>
</div>
<script>
QREOF

# Inject the device-specific values
cat >> "$QR_HTML" << EOF
var deviceData = {
  brainjack: true,
  name: "$HOSTNAME_SHORT",
  ip: "$LOCAL_IP",
  port: $PORT,
  token: "$TOKEN",
  os: "$( [ "$OS" = "Darwin" ] && echo "macos" || echo "linux" )"
};
EOF

cat >> "$QR_HTML" << 'QREOF2'
// Render device info
document.getElementById('d-name').textContent = deviceData.name;
document.getElementById('d-os').textContent = deviceData.os === 'macos' ? 'macOS' : 'Linux';
document.getElementById('d-addr').textContent = deviceData.ip + ':' + deviceData.port;
document.getElementById('d-token').textContent = deviceData.token;

var accStatus = document.getElementById('accessibility-status');
if (deviceData.os === 'macos') {
  accStatus.textContent = '⚠ Grant Accessibility permission';
  accStatus.style.color = '#F59E0B';
} else {
  accStatus.textContent = '✓ Ready';
  accStatus.className = 'check';
}

// Generate QR
var qr = qrcode(0, 'L');
qr.addData(JSON.stringify(deviceData));
qr.make();

var size = qr.getModuleCount();
var scale = 8;
var canvas = document.createElement('canvas');
canvas.width = size * scale;
canvas.height = size * scale;
var ctx = canvas.getContext('2d');
ctx.fillStyle = '#ffffff';
ctx.fillRect(0, 0, canvas.width, canvas.height);
ctx.fillStyle = '#0F1419';
for (var row = 0; row < size; row++) {
  for (var col = 0; col < size; col++) {
    if (qr.isDark(row, col)) {
      ctx.fillRect(col * scale, row * scale, scale, scale);
    }
  }
}
document.getElementById('qr-container').appendChild(canvas);
</script>
</body>
</html>
QREOF2

# Open QR page
if [ "$OS" = "Darwin" ]; then
    open "$QR_HTML" 2>/dev/null || true
elif command -v xdg-open &>/dev/null; then
    xdg-open "$QR_HTML" 2>/dev/null || true
fi

# ── Summary ──────────────────────────────────────────────────
echo ""
echo -e "  ─────────────────────────────────────────────────"
echo -e "  ${GREEN}${BOLD}BrainJack installed successfully.${NC}"
echo -e "  ─────────────────────────────────────────────────"
echo ""
echo -e "  ${BOLD}Location:${NC}    $INSTALL_DIR"
echo -e "  ${BOLD}Address:${NC}     ws://$LOCAL_IP:$PORT"
echo -e "  ${BOLD}Auth Token:${NC}  $TOKEN"
echo ""
echo -e "  ${BOLD}Connect from your phone:${NC}"
echo -e "  1. Open the BrainJack app"
echo -e "  2. Tap ${BOLD}+${NC} → ${BOLD}Scan QR Code${NC}"
echo -e "  3. Point at the QR code in your browser"
echo ""
if [ "$OS" = "Darwin" ]; then
    echo -e "  ${BOLD}Manage:${NC}"
    echo -e "    Stop:     launchctl unload ~/Library/LaunchAgents/com.brainjack.agent.plist"
    echo -e "    Start:    launchctl load ~/Library/LaunchAgents/com.brainjack.agent.plist"
    echo -e "    Logs:     tail -f ~/.brainjack/brainjack.log"
    echo -e "    Uninstall: curl -fsSL brainjack.ai/uninstall | bash"
else
    echo -e "  ${BOLD}Manage:${NC}"
    echo -e "    Status:   systemctl --user status brainjack-agent"
    echo -e "    Restart:  systemctl --user restart brainjack-agent"
    echo -e "    Logs:     journalctl --user -u brainjack-agent -f"
fi
echo ""
echo -e "  ${DIM}brainjack.ai${NC}"
echo ""
