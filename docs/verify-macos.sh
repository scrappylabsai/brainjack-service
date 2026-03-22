#!/usr/bin/env bash
# BrainJack macOS Install Verification
# Run this after install to verify everything works.
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}PASS${NC} $1"; }
fail() { echo -e "${RED}FAIL${NC} $1"; }
warn() { echo -e "${YELLOW}WARN${NC} $1"; }

echo "=== BrainJack macOS Verification ==="
echo ""

DIR="$(cd "$(dirname "$0")/.." && pwd)"

# 1. Python
if command -v python3 &>/dev/null; then
    pass "Python3: $(python3 --version 2>&1)"
else
    fail "Python3 not found"
fi

# 2. Venv exists
if [ -f "$DIR/.venv/bin/python" ]; then
    pass "Venv: $DIR/.venv/bin/python"
else
    fail "Venv not found at $DIR/.venv/"
fi

# 3. websockets installed
if "$DIR/.venv/bin/python" -c "import websockets" 2>/dev/null; then
    VER=$("$DIR/.venv/bin/python" -c "import websockets; print(websockets.__version__)" 2>/dev/null)
    pass "websockets: $VER"
else
    fail "websockets not installed in venv"
fi

# 4. qrcode installed
if "$DIR/.venv/bin/python" -c "import qrcode" 2>/dev/null; then
    VER=$("$DIR/.venv/bin/pip" show qrcode 2>/dev/null | grep "^Version:" | cut -d" " -f2)
    pass "qrcode: $VER"
else
    warn "qrcode not installed (QR pairing won't work, manual setup still works)"
fi

# 5. .env exists with token
if [ -f "$DIR/.env" ]; then
    TOKEN=$(grep '^BRAINJACK_TOKEN=' "$DIR/.env" | sed 's/^BRAINJACK_TOKEN=//')
    if [ -n "$TOKEN" ] && [ "$TOKEN" != "off" ]; then
        pass "Auth token: ${TOKEN:0:8}...${TOKEN: -4} (${#TOKEN} chars)"
    else
        warn "Auth token is empty or disabled"
    fi
else
    fail ".env file not found"
fi

# 6. BrainJack.app exists
if [ -d "$DIR/BrainJack.app" ]; then
    BUNDLE_ID=$(/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$DIR/BrainJack.app/Contents/Info.plist" 2>/dev/null || echo "unknown")
    pass "BrainJack.app: $BUNDLE_ID"
else
    fail "BrainJack.app not found — run install.sh to create it"
fi

# 7. launchd agent
if launchctl list com.brainjack.agent &>/dev/null; then
    PID=$(launchctl list com.brainjack.agent 2>/dev/null | grep '"PID"' | grep -o '[0-9]*' || echo "none")
    if [ "$PID" != "none" ] && [ -n "$PID" ]; then
        pass "launchd agent: running (PID $PID)"
    else
        warn "launchd agent: loaded but not running"
    fi
else
    fail "launchd agent not loaded"
fi

# 8. Port 9898 listening
PORT=$(grep '^BRAINJACK_PORT=' "$DIR/.env" 2>/dev/null | sed 's/^BRAINJACK_PORT=//' || echo "9898")
PORT=${PORT:-9898}
if lsof -iTCP:"$PORT" -sTCP:LISTEN &>/dev/null; then
    pass "Port $PORT: listening"
else
    fail "Port $PORT: not listening"
fi

# 9. Quartz CGEvent support
CG_RESULT=$("$DIR/.venv/bin/python" -c "
try:
    from Quartz import CGEventCreateKeyboardEvent, kCGHIDEventTap
    e = CGEventCreateKeyboardEvent(None, 0, True)
    print('OK' if e else 'DENIED')
except ImportError:
    print('NO_QUARTZ')
except Exception:
    print('DENIED')
" 2>/dev/null)
if [ "$CG_RESULT" = "OK" ]; then
    pass "Accessibility: granted (CGEvents)"
elif [ "$CG_RESULT" = "NO_QUARTZ" ]; then
    warn "pyobjc-framework-Quartz not installed — falling back to osascript"
else
    fail "Accessibility: NOT granted — add BrainJack.app in System Settings > Privacy & Security > Accessibility"
fi

# 10. WebSocket connectivity (self-test)
if [ -n "${TOKEN:-}" ]; then
    RESP=$("$DIR/.venv/bin/python" -c "
import asyncio, websockets, json
async def t():
    try:
        async with websockets.connect('ws://127.0.0.1:$PORT?token=$TOKEN') as ws:
            await ws.send(json.dumps({'cmd':'status'}))
            r = json.loads(await ws.recv())
            print(r.get('device','?') + '|' + r.get('os','?'))
    except Exception as e:
        print('ERR|' + str(e))
asyncio.run(t())
" 2>/dev/null)
    DEVICE=$(echo "$RESP" | cut -d'|' -f1)
    DEVOS=$(echo "$RESP" | cut -d'|' -f2)
    if [ "$DEVOS" = "macos" ]; then
        pass "WebSocket: connected to $DEVICE ($DEVOS)"
    else
        fail "WebSocket: unexpected response: $RESP"
    fi
else
    warn "WebSocket: skipped (no token)"
fi

echo ""
echo "=== Verification Complete ==="
