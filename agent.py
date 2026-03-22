#!/usr/bin/env python3
"""BrainJack Network Agent — WebSocket HID injection daemon.

Receives the same JSON commands as the ESP32 BLE/serial protocol
and injects text/keys at the active cursor via xdotool (Linux X11),
ydotool (Linux Wayland), or osascript (macOS).

Protocol:
    {"cmd":"type","text":"hello world"}
    {"cmd":"key","key":"Return"}
    {"cmd":"combo","keys":"ctrl+c"}
    {"cmd":"status"}
    {"cmd":"auth","token":"..."}  (first-message auth mode)

Security:
    - Token auth (query string or first-message handshake)
    - TLS via stdlib ssl
    - Per-IP rate limiting (token bucket)
    - Audit logging (JSON lines, never logs keystroke content)
"""

import asyncio
import argparse
import hmac
import json
import logging
import logging.handlers
import os
import platform
import shutil
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import websockets

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_dotenv(path: Path) -> None:
    """Minimal .env loader — no dependencies."""
    if not path.is_file():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val


def load_config(cli_args: argparse.Namespace) -> dict:
    """Load config: .env file → env vars → CLI overrides."""
    agent_dir = Path(__file__).resolve().parent
    _load_dotenv(agent_dir / ".env")

    token_raw = os.environ.get("BRAINJACK_TOKEN", "").strip()
    auth_enabled = bool(token_raw) and token_raw.lower() != "off"

    cfg = {
        "token": token_raw if auth_enabled else None,
        "host": cli_args.host or os.environ.get("BRAINJACK_HOST", "0.0.0.0"),
        "port": cli_args.port or int(os.environ.get("BRAINJACK_PORT", "9898")),
        "tls_cert": cli_args.tls_cert or os.environ.get("BRAINJACK_TLS_CERT", ""),
        "tls_key": cli_args.tls_key or os.environ.get("BRAINJACK_TLS_KEY", ""),
        "behind_proxy": os.environ.get("BRAINJACK_BEHIND_PROXY", "false").lower() == "true",
        "rate_limit": int(os.environ.get("BRAINJACK_RATE_LIMIT", "30")),
        "rate_window": int(os.environ.get("BRAINJACK_RATE_WINDOW", "10")),
        "rate_burst": int(os.environ.get("BRAINJACK_RATE_BURST", "5")),
        "audit_log": os.environ.get("BRAINJACK_AUDIT_LOG", ""),
        "audit_max_bytes": int(os.environ.get("BRAINJACK_AUDIT_MAX_BYTES", "10485760")),
        "audit_backup_count": int(os.environ.get("BRAINJACK_AUDIT_BACKUP_COUNT", "5")),
    }

    # Proxy mode overrides
    if cfg["behind_proxy"]:
        cfg["host"] = "127.0.0.1"
        cfg["tls_cert"] = ""
        cfg["tls_key"] = ""

    return cfg

# ---------------------------------------------------------------------------
# Audit logger
# ---------------------------------------------------------------------------

_audit_logger: logging.Logger | None = None


def setup_audit_logger(cfg: dict) -> None:
    global _audit_logger
    _audit_logger = logging.getLogger("brainjack.audit")
    _audit_logger.setLevel(logging.INFO)
    _audit_logger.propagate = False

    formatter = logging.Formatter("%(message)s")

    # Always log to stderr
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(formatter)
    _audit_logger.addHandler(sh)

    # Optional file handler
    if cfg["audit_log"]:
        fh = logging.handlers.RotatingFileHandler(
            cfg["audit_log"],
            maxBytes=cfg["audit_max_bytes"],
            backupCount=cfg["audit_backup_count"],
        )
        fh.setFormatter(formatter)
        _audit_logger.addHandler(fh)


def audit(event: str, peer: str, **extra) -> None:
    """Emit one JSON audit line. NEVER include keystroke text content."""
    if _audit_logger is None:
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "peer": peer,
        **extra,
    }
    _audit_logger.info(json.dumps(record, separators=(",", ":")))

# ---------------------------------------------------------------------------
# Rate limiter (token bucket per IP)
# ---------------------------------------------------------------------------

@dataclass
class TokenBucket:
    rate: float          # tokens per second
    burst: float         # max tokens
    tokens: float = -1.0  # sentinel, filled on first use
    last: float = field(default_factory=time.monotonic)

    def __post_init__(self):
        if self.tokens < 0:
            self.tokens = self.burst  # start full

    def allow(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last
        self.last = now
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


_buckets: dict[str, TokenBucket] = {}


def check_rate_limit(ip: str, cfg: dict) -> bool:
    """Returns True if allowed, False if rate limited."""
    if ip not in _buckets:
        rate = cfg["rate_limit"] / cfg["rate_window"]
        _buckets[ip] = TokenBucket(rate=rate, burst=float(cfg["rate_burst"] + cfg["rate_limit"]))
    return _buckets[ip].allow()


def cleanup_bucket(ip: str) -> None:
    _buckets.pop(ip, None)

# ---------------------------------------------------------------------------
# TLS
# ---------------------------------------------------------------------------

def build_ssl_context(cfg: dict) -> ssl.SSLContext | None:
    cert = cfg["tls_cert"]
    key = cfg["tls_key"]
    if not cert or not key:
        return None
    if not Path(cert).is_file():
        print(f"ERROR: TLS cert not found: {cert}", file=sys.stderr)
        sys.exit(1)
    if not Path(key).is_file():
        print(f"ERROR: TLS key not found: {key}", file=sys.stderr)
        sys.exit(1)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _get_client_ip(websocket, cfg: dict) -> str:
    """Get client IP, respecting X-Forwarded-For in proxy mode."""
    if cfg["behind_proxy"]:
        xff = websocket.request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
    addr = websocket.remote_address
    return addr[0] if addr else "unknown"


def _check_token(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided.encode(), expected.encode())


async def authenticate(websocket, cfg: dict) -> bool:
    """Handle auth. Returns True if client is authorized to send commands."""
    token = cfg["token"]
    if token is None:
        return True  # Auth disabled

    peer = _get_client_ip(websocket, cfg)

    # Check query string first (zero-iOS-change migration path)
    qs = parse_qs(urlparse(websocket.request.path).query)
    qs_tokens = qs.get("token", [])
    if qs_tokens and _check_token(qs_tokens[0], token):
        audit("auth_ok", peer, method="query_string")
        return True

    # First-message handshake with 5s timeout
    try:
        msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
    except (asyncio.TimeoutError, websockets.ConnectionClosed):
        audit("auth_fail", peer, reason="timeout")
        await websocket.close(1008, "auth timeout")
        return False

    try:
        data = json.loads(msg)
    except json.JSONDecodeError:
        audit("auth_fail", peer, reason="invalid_json")
        await websocket.close(1008, "invalid auth message")
        return False

    if data.get("cmd") == "auth" and _check_token(data.get("token", ""), token):
        audit("auth_ok", peer, method="handshake")
        await websocket.send(json.dumps({"ok": True, "authed": True}))
        return True

    audit("auth_fail", peer, reason="bad_token")
    await websocket.close(1008, "authentication failed")
    return False

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def detect_platform() -> str:
    if platform.system() == "Darwin":
        return "macos"
    if platform.system() == "Windows":
        return "windows"
    if platform.system() == "Linux":
        if os.environ.get("WAYLAND_DISPLAY"):
            return "linux-wayland"
        return "linux-x11"
    return "unknown"

PLATFORM = detect_platform()

# Lazy-load Windows backend (only on Windows)
_win_backend = None
if PLATFORM == "windows":
    from backend_windows import (
        inject_text as _win_inject_text,
        inject_key as _win_inject_key,
        inject_combo as _win_inject_combo,
        get_context_extra as _win_get_context_extra,
    )

# ---------------------------------------------------------------------------
# Key name mapping (BrainJack firmware names → xdotool/ydotool/osascript)
# ---------------------------------------------------------------------------

XDOTOOL_KEYS = {
    "ENTER": "Return", "RETURN": "Return",
    "TAB": "Tab", "ESCAPE": "Escape", "ESC": "Escape",
    "BACKSPACE": "BackSpace", "DELETE": "Delete",
    "SPACE": "space",
    "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
    "HOME": "Home", "END": "End",
    "PAGEUP": "Prior", "PAGEDOWN": "Next",
    "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4",
    "F5": "F5", "F6": "F6", "F7": "F7", "F8": "F8",
    "F9": "F9", "F10": "F10", "F11": "F11", "F12": "F12",
    "CAPSLOCK": "Caps_Lock", "INSERT": "Insert",
    "PRINTSCREEN": "Print",
}

# ydotool uses Linux input event key codes (KEY_*)
YDOTOOL_KEYS = {
    "ENTER": 28, "RETURN": 28,
    "TAB": 15, "ESCAPE": 1, "ESC": 1,
    "BACKSPACE": 14, "DELETE": 111,
    "SPACE": 57,
    "UP": 103, "DOWN": 108, "LEFT": 105, "RIGHT": 106,
    "HOME": 102, "END": 107,
    "PAGEUP": 104, "PAGEDOWN": 109,
    "F1": 59, "F2": 60, "F3": 61, "F4": 62,
    "F5": 63, "F6": 64, "F7": 65, "F8": 66,
    "F9": 67, "F10": 68, "F11": 87, "F12": 88,
    "CAPSLOCK": 58, "INSERT": 110,
    "PRINTSCREEN": 99,
    # Single chars (common ones)
    "A": 30, "B": 48, "C": 46, "D": 32, "E": 18, "F": 33,
    "G": 34, "H": 35, "I": 23, "J": 36, "K": 37, "L": 38,
    "M": 50, "N": 49, "O": 24, "P": 25, "Q": 16, "R": 19,
    "S": 31, "T": 20, "U": 22, "V": 47, "W": 17, "X": 45,
    "Y": 21, "Z": 44,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6,
    "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "-": 12, "=": 13, "[": 26, "]": 27, "\\": 43,
    ";": 39, "'": 40, "`": 41, ",": 51, ".": 52, "/": 53,
}

YDOTOOL_MODIFIERS = {
    "ctrl": 29, "control": 29,      # KEY_LEFTCTRL
    "alt": 56, "option": 56,        # KEY_LEFTALT
    "shift": 42,                     # KEY_LEFTSHIFT
    "cmd": 125, "gui": 125,         # KEY_LEFTMETA
    "meta": 125, "super": 125,
}

# osascript key codes for special keys
OSASCRIPT_KEYCODES = {
    "ENTER": 36, "RETURN": 36,
    "TAB": 48, "ESCAPE": 53, "ESC": 53,
    "BACKSPACE": 51, "DELETE": 117,
    "SPACE": 49,
    "UP": 126, "DOWN": 125, "LEFT": 123, "RIGHT": 124,
    "HOME": 115, "END": 119,
    "PAGEUP": 116, "PAGEDOWN": 121,
    "F1": 122, "F2": 120, "F3": 99, "F4": 118,
    "F5": 96, "F6": 97, "F7": 98, "F8": 100,
    "F9": 101, "F10": 109, "F11": 103, "F12": 111,
}

OSASCRIPT_MODIFIERS = {
    "ctrl": "control down",
    "alt": "option down",
    "shift": "shift down",
    "cmd": "command down", "gui": "command down", "meta": "command down",
    "super": "command down",
}

XDOTOOL_MODIFIERS = {
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "option": "alt",
    "shift": "shift",
    "cmd": "super", "gui": "super", "meta": "super", "super": "super",
}

# ---------------------------------------------------------------------------
# Text injection
# ---------------------------------------------------------------------------

def inject_text(text: str) -> dict:
    if PLATFORM == "windows":
        return _win_inject_text(text)

    if PLATFORM == "linux-x11":
        r = subprocess.run(
            ["xdotool", "type", "--delay", "12", "--clearmodifiers", "--", text],
            capture_output=True, text=True, timeout=10,
        )
        return {"ok": r.returncode == 0, "error": r.stderr.strip() or None}

    if PLATFORM == "linux-wayland":
        r = subprocess.run(
            ["ydotool", "type", "--key-delay", "12", "--", text],
            capture_output=True, text=True, timeout=10,
        )
        return {"ok": r.returncode == 0, "error": r.stderr.strip() or None}

    if PLATFORM == "macos":
        parts = text.split("\n")
        for i, part in enumerate(parts):
            if part:
                subprocess.run(["pbcopy"], input=part.encode(), check=True, timeout=5)
                subprocess.run(
                    ["osascript", "-e",
                     'tell application "System Events" to keystroke "v" using command down'],
                    capture_output=True, text=True, timeout=5,
                )
            if i < len(parts) - 1:
                subprocess.run(
                    ["osascript", "-e",
                     'tell application "System Events" to key code 36'],
                    capture_output=True, text=True, timeout=5,
                )
        return {"ok": True}

    return {"ok": False, "error": f"unsupported platform: {PLATFORM}"}

# ---------------------------------------------------------------------------
# Key injection
# ---------------------------------------------------------------------------

def _resolve_xdotool_key(name: str) -> str:
    upper = name.upper()
    if upper in XDOTOOL_KEYS:
        return XDOTOOL_KEYS[upper]
    return name

def _resolve_ydotool_key(name: str) -> int | None:
    upper = name.upper()
    if upper in YDOTOOL_KEYS:
        return YDOTOOL_KEYS[upper]
    if len(name) == 1 and name.upper() in YDOTOOL_KEYS:
        return YDOTOOL_KEYS[name.upper()]
    return None

def inject_key(key: str) -> dict:
    if PLATFORM == "windows":
        return _win_inject_key(key)

    if PLATFORM == "linux-x11":
        xkey = _resolve_xdotool_key(key)
        r = subprocess.run(
            ["xdotool", "key", "--clearmodifiers", xkey],
            capture_output=True, text=True, timeout=5,
        )
        return {"ok": r.returncode == 0, "error": r.stderr.strip() or None}

    if PLATFORM == "linux-wayland":
        code = _resolve_ydotool_key(key)
        if code is None:
            return {"ok": False, "error": f"unknown key: {key}"}
        r = subprocess.run(
            ["ydotool", "key", f"{code}:1", f"{code}:0"],
            capture_output=True, text=True, timeout=5,
        )
        return {"ok": r.returncode == 0, "error": r.stderr.strip() or None}

    if PLATFORM == "macos":
        upper = key.upper()
        if upper in OSASCRIPT_KEYCODES:
            code = OSASCRIPT_KEYCODES[upper]
            r = subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to key code {code}'],
                capture_output=True, text=True, timeout=5,
            )
            return {"ok": r.returncode == 0, "error": r.stderr.strip() or None}
        escaped = key.replace("\\", "\\\\").replace('"', '\\"')
        r = subprocess.run(
            ["osascript", "-e",
             f'tell application "System Events" to keystroke "{escaped}"'],
            capture_output=True, text=True, timeout=5,
        )
        return {"ok": r.returncode == 0, "error": r.stderr.strip() or None}

    return {"ok": False, "error": f"unsupported platform: {PLATFORM}"}

# ---------------------------------------------------------------------------
# Combo injection (e.g. "ctrl+c", "cmd+shift+s")
# ---------------------------------------------------------------------------

def inject_combo(keys: str) -> dict:
    if PLATFORM == "windows":
        return _win_inject_combo(keys)

    parts = [p.strip() for p in keys.lower().split("+")]
    if not parts:
        return {"ok": False, "error": "empty combo"}

    if PLATFORM == "linux-x11":
        resolved = []
        for p in parts:
            if p in XDOTOOL_MODIFIERS:
                resolved.append(XDOTOOL_MODIFIERS[p])
            else:
                resolved.append(_resolve_xdotool_key(p))
        combo_str = "+".join(resolved)
        r = subprocess.run(
            ["xdotool", "key", "--clearmodifiers", combo_str],
            capture_output=True, text=True, timeout=5,
        )
        return {"ok": r.returncode == 0, "error": r.stderr.strip() or None}

    if PLATFORM == "linux-wayland":
        *mods, main_key = parts
        events = []
        for m in mods:
            code = YDOTOOL_MODIFIERS.get(m)
            if code:
                events.append(f"{code}:1")
        main_code = _resolve_ydotool_key(main_key)
        if main_code is None:
            return {"ok": False, "error": f"unknown key: {main_key}"}
        events.append(f"{main_code}:1")
        events.append(f"{main_code}:0")
        for m in reversed(mods):
            code = YDOTOOL_MODIFIERS.get(m)
            if code:
                events.append(f"{code}:0")
        r = subprocess.run(
            ["ydotool", "key"] + events,
            capture_output=True, text=True, timeout=5,
        )
        return {"ok": r.returncode == 0, "error": r.stderr.strip() or None}

    if PLATFORM == "macos":
        *mods, main_key = parts
        using_parts = []
        for m in mods:
            if m in OSASCRIPT_MODIFIERS:
                using_parts.append(OSASCRIPT_MODIFIERS[m])

        upper = main_key.upper()
        using_clause = ", ".join(using_parts)
        using = f" using {{{using_clause}}}" if using_parts else ""

        if upper in OSASCRIPT_KEYCODES:
            code = OSASCRIPT_KEYCODES[upper]
            script = f'tell application "System Events" to key code {code}{using}'
        else:
            escaped = main_key.replace("\\", "\\\\").replace('"', '\\"')
            script = f'tell application "System Events" to keystroke "{escaped}"{using}'

        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        return {"ok": r.returncode == 0, "error": r.stderr.strip() or None}

    return {"ok": False, "error": f"unsupported platform: {PLATFORM}"}

# ---------------------------------------------------------------------------
# Context (active window info)
# ---------------------------------------------------------------------------

def get_context() -> dict:
    hostname = socket.gethostname()
    info = {
        "device": hostname,
        "os": PLATFORM,
        "hostname": hostname,
    }

    if PLATFORM == "windows":
        info.update(_win_get_context_extra())

    elif PLATFORM == "linux-x11":
        info["display"] = os.environ.get("DISPLAY", ":0")
        try:
            r = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0:
                info["active_window"] = r.stdout.strip()
        except Exception:
            pass

    elif PLATFORM == "linux-wayland":
        info["display"] = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        try:
            r = subprocess.run(
                ["kdotool", "getactivewindow"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0:
                win_id = r.stdout.strip()
                r2 = subprocess.run(
                    ["kdotool", "getwindowname", win_id],
                    capture_output=True, text=True, timeout=3,
                )
                if r2.returncode == 0:
                    info["active_window"] = r2.stdout.strip()
        except FileNotFoundError:
            pass

    elif PLATFORM == "macos":
        try:
            r = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get name of first '
                 'application process whose frontmost is true'],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0:
                info["active_window"] = r.stdout.strip()
        except Exception:
            pass

    return info

# ---------------------------------------------------------------------------
# Command dispatcher
# ---------------------------------------------------------------------------

def handle_command(data: dict) -> dict:
    cmd = data.get("cmd", "")

    if cmd == "type":
        text = data.get("text", "")
        if not text:
            return {"ok": False, "error": "missing text"}
        return inject_text(text)

    if cmd == "key":
        key = data.get("key", "")
        if not key:
            return {"ok": False, "error": "missing key"}
        return inject_key(key)

    if cmd == "combo":
        keys = data.get("keys", "")
        if not keys:
            return {"ok": False, "error": "missing keys"}
        return inject_combo(keys)

    if cmd == "status":
        return get_context()

    return {"ok": False, "error": f"unknown cmd: {cmd}"}

# ---------------------------------------------------------------------------
# WebSocket server
# ---------------------------------------------------------------------------

async def ws_handler(websocket, cfg: dict):
    peer = _get_client_ip(websocket, cfg)
    audit("connect", peer)

    # Auth gate
    if not await authenticate(websocket, cfg):
        cleanup_bucket(peer)
        return

    try:
        async for message in websocket:
            # Rate limit check
            if not check_rate_limit(peer, cfg):
                audit("rate_limit", peer)
                await websocket.send(json.dumps({"ok": False, "error": "rate limited"}))
                continue

            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"ok": False, "error": "invalid JSON"}))
                continue

            cmd = data.get("cmd", "")
            audit("cmd", peer, cmd=cmd)

            result = handle_command(data)
            await websocket.send(json.dumps(result))
    except websockets.ConnectionClosed:
        pass
    finally:
        cleanup_bucket(peer)
        audit("disconnect", peer)


async def main(cfg: dict):
    # Sanity checks
    if PLATFORM == "linux-x11" and not shutil.which("xdotool"):
        print("ERROR: xdotool not found. Install: sudo pacman -S xdotool")
        sys.exit(1)
    if PLATFORM == "linux-wayland" and not shutil.which("ydotool"):
        print("ERROR: ydotool not found. Install: sudo pacman -S ydotool")
        sys.exit(1)
    if PLATFORM == "macos" and not shutil.which("osascript"):
        print("ERROR: osascript not found (should be built-in on macOS)")
        sys.exit(1)
    # Windows uses ctypes (stdlib) — no external tools needed

    setup_audit_logger(cfg)
    ssl_ctx = build_ssl_context(cfg)

    proto = "wss" if ssl_ctx else "ws"
    host, port = cfg["host"], cfg["port"]
    print(f"[brainjack] Platform: {PLATFORM}")
    print(f"[brainjack] Listening on {proto}://{host}:{port}")
    print(f"[brainjack] Auth: {'enabled' if cfg['token'] else 'disabled'}")
    print(f"[brainjack] TLS: {'enabled' if ssl_ctx else 'disabled'}")
    print(f"[brainjack] Rate limit: {cfg['rate_limit']}/{cfg['rate_window']}s burst={cfg['rate_burst']}")
    if cfg["behind_proxy"]:
        print("[brainjack] Proxy mode: trusting X-Forwarded-For")

    async def ios_compat(connection, request):
        """iOS URLSessionWebSocketTask sends Connection: keep-alive instead of
        Upgrade. Patch it before the websockets library rejects the handshake."""
        conn = request.headers.get("Connection", "")
        if "upgrade" not in conn.lower():
            if request.headers.get("Upgrade", "").lower() == "websocket":
                request.headers["Connection"] = "Upgrade"

    handler = lambda ws: ws_handler(ws, cfg)
    async with websockets.serve(handler, host, port, ssl=ssl_ctx,
                                process_request=ios_compat):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BrainJack Network Agent")
    parser.add_argument("--host", default="", help="Bind address")
    parser.add_argument("--port", type=int, default=0, help="Port")
    parser.add_argument("--tls-cert", default="", help="TLS certificate path")
    parser.add_argument("--tls-key", default="", help="TLS private key path")
    args = parser.parse_args()
    cfg = load_config(args)
    asyncio.run(main(cfg))
