#!/usr/bin/env bash
# BrainJack Agent — cross-platform installer.
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
    echo "[brainjack] Generated auth token: $TOKEN"
    echo "[brainjack] Token saved to .env — share with clients for auth."
else
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
        # Update .env with cert paths
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

# --- Service install ---
if [ "$OS" = "Darwin" ]; then
    echo "[brainjack] Installing macOS LaunchAgent..."
    PLIST_SRC="$DIR/com.brainjack.agent.plist"
    PLIST_DST="$HOME/Library/LaunchAgents/com.brainjack.agent.plist"

    # Substitute placeholder with actual path
    sed "s|AGENT_DIR_PLACEHOLDER|$DIR|g" "$PLIST_SRC" > "$PLIST_DST"

    # Unload if already loaded, then load
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    echo "[brainjack] LaunchAgent installed. Check: launchctl list com.brainjack.agent"
else
    echo "[brainjack] Installing systemd user service..."
    mkdir -p ~/.config/systemd/user
    cp "$DIR/brainjack-agent.service" ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now brainjack-agent.service
    echo "[brainjack] Systemd service installed. Check: systemctl --user status brainjack-agent"
fi

echo "[brainjack] Done."
