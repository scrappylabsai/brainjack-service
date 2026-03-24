#!/usr/bin/env bash
# BrainJack Service — cross-platform installer.
# Detects Linux (systemd) vs macOS (launchd), sets up venv, generates
# auth token if missing, optional --tls for self-signed certs.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TLS=false

for arg in "$@"; do
    case "$arg" in
        --tls) TLS=true ;;
        --help|-h)
            echo "Usage: $0 [--tls]"
            echo "  --tls  Generate self-signed TLS certificate"
            exit 0
            ;;
    esac
done

OS="$(uname -s)"
echo "[brainjack] Detected OS: $OS"

# --- Python check ---
if ! command -v python3 &>/dev/null; then
    echo "[brainjack] ERROR: python3 not found."
    if [ "$OS" = "Darwin" ]; then
        echo "[brainjack] Install via: brew install python"
    else
        echo "[brainjack] Install via your package manager (apt, pacman, dnf, etc.)"
    fi
    exit 1
fi

# --- Python venv ---
echo "[brainjack] Creating venv..."
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"

# --- .env setup ---
if [ ! -f "$DIR/.env" ]; then
    echo "[brainjack] Creating .env from template..."
    cp "$DIR/.env.template" "$DIR/.env"
fi

# --- Token generation ---
CURRENT_TOKEN=$(grep '^BRAINJACK_TOKEN=' "$DIR/.env" 2>/dev/null | sed 's/^BRAINJACK_TOKEN=//' || true)
if [ -z "$CURRENT_TOKEN" ]; then
    TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    if [ "$OS" = "Darwin" ]; then
        sed -i '' "s|^BRAINJACK_TOKEN=.*|BRAINJACK_TOKEN=$TOKEN|" "$DIR/.env"
    else
        sed -i "s|^BRAINJACK_TOKEN=.*|BRAINJACK_TOKEN=$TOKEN|" "$DIR/.env"
    fi
    echo "[brainjack] Generated auth token."
else
    TOKEN="$CURRENT_TOKEN"
    echo "[brainjack] Auth token already set."
fi

# --- TLS self-signed cert ---
if [ "$TLS" = true ]; then
    CERT_DIR="$DIR/certs"
    mkdir -p "$CERT_DIR"
    if [ ! -f "$CERT_DIR/brainjack.pem" ]; then
        HOSTNAME=$(hostname)
        echo "[brainjack] Generating self-signed TLS cert for $HOSTNAME..."
        openssl req -x509 -newkey rsa:2048 -nodes \
            -keyout "$CERT_DIR/brainjack-key.pem" \
            -out "$CERT_DIR/brainjack.pem" \
            -days 365 \
            -subj "/CN=$HOSTNAME" \
            -addext "subjectAltName=DNS:$HOSTNAME,DNS:localhost,IP:127.0.0.1" \
            2>/dev/null
        if [ "$OS" = "Darwin" ]; then
            sed -i '' "s|^BRAINJACK_TLS_CERT=.*|BRAINJACK_TLS_CERT=$CERT_DIR/brainjack.pem|" "$DIR/.env"
            sed -i '' "s|^BRAINJACK_TLS_KEY=.*|BRAINJACK_TLS_KEY=$CERT_DIR/brainjack-key.pem|" "$DIR/.env"
        else
            sed -i "s|^BRAINJACK_TLS_CERT=.*|BRAINJACK_TLS_CERT=$CERT_DIR/brainjack.pem|" "$DIR/.env"
            sed -i "s|^BRAINJACK_TLS_KEY=.*|BRAINJACK_TLS_KEY=$CERT_DIR/brainjack-key.pem|" "$DIR/.env"
        fi
        echo "[brainjack] TLS cert created: $CERT_DIR/brainjack.pem"
    else
        echo "[brainjack] TLS cert already exists."
    fi
fi

# --- Input injection tool (Linux only) ---
if [ "$OS" = "Linux" ]; then
    if [ -n "${WAYLAND_DISPLAY:-}" ]; then
        echo "[brainjack] Wayland detected — ensuring ydotool..."
        if ! command -v ydotool &>/dev/null; then
            if command -v pacman &>/dev/null; then
                sudo pacman -S --noconfirm ydotool
            elif command -v apt &>/dev/null; then
                sudo apt install -y ydotool
            else
                echo "WARNING: Install ydotool manually for Wayland support"
            fi
        fi
        if ! groups | grep -q '\binput\b'; then
            echo "[brainjack] Adding $(whoami) to input group (re-login required)..."
            sudo usermod -aG input "$(whoami)"
        fi
        systemctl --user enable --now ydotool.service 2>/dev/null || true
    else
        echo "[brainjack] X11 detected — ensuring xdotool..."
        if ! command -v xdotool &>/dev/null; then
            if command -v pacman &>/dev/null; then
                sudo pacman -S --noconfirm xdotool
            elif command -v apt &>/dev/null; then
                sudo apt install -y xdotool
            else
                echo "WARNING: Install xdotool manually for X11 support"
            fi
        fi
    fi
fi

# --- Detect LAN IP ---
get_lan_ip() {
    if [ "$OS" = "Darwin" ]; then
        for iface in en0 en1 en2; do
            IP=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
            if [ -n "$IP" ]; then echo "$IP"; return; fi
        done
    else
        IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
        if [ -n "$IP" ]; then echo "$IP"; return; fi
    fi
    echo "127.0.0.1"
}

LAN_IP=$(get_lan_ip)
PORT=$(grep '^BRAINJACK_PORT=' "$DIR/.env" 2>/dev/null | sed 's/^BRAINJACK_PORT=//' || echo "9898")
PORT=${PORT:-9898}

# --- Service install ---
if [ "$OS" = "Darwin" ]; then
    # --- Build BrainJack.app wrapper ---
    echo "[brainjack] Building BrainJack.app..."
    rm -rf "$DIR/BrainJack.app"

    # osacompile creates a proper Cocoa app bundle.
    # macOS attributes Accessibility permission to the app, not raw Python.
    osacompile -o "$DIR/BrainJack.app" -e \
        "do shell script \"cd '$DIR' && exec '$DIR/.venv/bin/python' '$DIR/agent.py' >> '$DIR/brainjack.log' 2>&1\""

    # Customize bundle identity
    APLIST="$DIR/BrainJack.app/Contents/Info.plist"
    /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string ai.scrappylabs.brainjack" "$APLIST"
    /usr/libexec/PlistBuddy -c "Set :CFBundleName BrainJack" "$APLIST"
    /usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$APLIST" 2>/dev/null || \
        /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "$APLIST"

    echo "[brainjack] BrainJack.app created."

    # --- Install LaunchAgent ---
    echo "[brainjack] Installing LaunchAgent..."
    PLIST_SRC="$DIR/com.brainjack.agent.plist"
    PLIST_DST="$HOME/Library/LaunchAgents/com.brainjack.agent.plist"

    sed "s|AGENT_DIR_PLACEHOLDER|$DIR|g" "$PLIST_SRC" > "$PLIST_DST"

    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    echo "[brainjack] LaunchAgent installed."

    # --- Accessibility permission (required for CGEvent keystroke injection) ---
    # Test with a CGEvent post — this checks Accessibility, not Automation
    CG_TEST=$("$DIR/.venv/bin/python" -c "
try:
    from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap
    e = CGEventCreateKeyboardEvent(None, 0, True)
    if e is None:
        print('DENIED')
    else:
        print('OK')
except Exception:
    print('NO_QUARTZ')
" 2>/dev/null)

    if [ "$CG_TEST" = "OK" ]; then
        echo "[brainjack] ✓ Accessibility permission granted."
    else
        echo ""
        echo "╔══════════════════════════════════════════════════════════╗"
        echo "║              Accessibility Permission                   ║"
        echo "╠══════════════════════════════════════════════════════════╣"
        echo "║                                                         ║"
        echo "║  BrainJack needs Accessibility permission to type.      ║"
        echo "║                                                         ║"
        echo "║  1. System Settings is opening to Accessibility...      ║"
        echo "║  2. Click the + button (unlock with password if needed) ║"
        echo "║  3. Navigate to: $(echo "$DIR" | sed "s|$HOME|~|")      "
        echo "║  4. Select BrainJack.app → toggle it ON                 ║"
        echo "║                                                         ║"
        echo "║  Skip? BrainJack still works in clipboard-paste mode.   ║"
        echo "║                                                         ║"
        echo "╚══════════════════════════════════════════════════════════╝"
        echo ""

        open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
        sleep 1
        open -R "$DIR/BrainJack.app"

        if [ -t 0 ]; then
            echo "[brainjack] Press ENTER after granting permission (or ENTER to skip)..."
            read -r
            CG_TEST2=$("$DIR/.venv/bin/python" -c "
try:
    from Quartz import CGEventCreateKeyboardEvent
    e = CGEventCreateKeyboardEvent(None, 0, True)
    print('OK' if e else 'DENIED')
except: print('DENIED')
" 2>/dev/null)
            if [ "$CG_TEST2" = "OK" ]; then
                echo "[brainjack] ✓ Accessibility permission granted!"
            else
                echo "[brainjack] ⚠ Accessibility not granted — keystrokes need BrainJack.app added."
                echo "[brainjack] → System Settings > Privacy & Security > Accessibility"
                echo "[brainjack] Typing still works via clipboard paste. Key combos require Accessibility."
            fi
        else
            echo "[brainjack] Non-interactive — grant Accessibility permission manually."
            echo "[brainjack] → System Settings > Privacy & Security > Accessibility > add BrainJack.app"
        fi
    fi
else
    echo "[brainjack] Installing systemd user service..."
    mkdir -p ~/.config/systemd/user
    cp "$DIR/brainjack-agent.service" ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now brainjack-agent.service
    echo "[brainjack] Systemd service installed. Check: systemctl --user status brainjack-agent"
fi

# --- Wait for service to start ---
echo "[brainjack] Waiting for service to start..."
for i in 1 2 3 4 5; do
    if lsof -iTCP:"$PORT" -sTCP:LISTEN &>/dev/null 2>&1 || \
       ss -tln 2>/dev/null | grep -q ":$PORT "; then
        echo "[brainjack] ✓ Service listening on port $PORT"
        break
    fi
    sleep 1
done

# --- QR Code for pairing ---
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║           Scan to pair with BrainJack app               ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

DETECTED_OS="linux"
[ "$OS" = "Darwin" ] && DETECTED_OS="macos"

"$DIR/.venv/bin/python" -c "
import json, sys
try:
    import qrcode
except ImportError:
    print('[brainjack] QR library not available — use manual setup below.')
    sys.exit(0)

data = {
    'brainjack': 1,
    'name': '$(hostname)',
    'ip': '$LAN_IP',
    'port': $PORT,
    'os': '$DETECTED_OS',
    'token': '$TOKEN'
}

qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=1)
qr.add_data(json.dumps(data))
qr.make(fit=True)
qr.print_ascii(invert=True)
print()
print(f'  Device:  {data[\"name\"]}')
print(f'  Address: {data[\"ip\"]}:{data[\"port\"]}')
print(f'  Token:   {data[\"token\"][:8]}...{data[\"token\"][-4:]}')
print()
print('  Open BrainJack on your iPhone → tap + → Scan QR Code')
print()
" 2>/dev/null || true

echo "[brainjack] Manual setup:"
echo "  IP:    $LAN_IP:$PORT"
echo "  Token: $TOKEN"
echo "  Web:   https://brainjack.ai/setup"
echo ""
echo "[brainjack] Done. BrainJack is running."
