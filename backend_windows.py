"""BrainJack Windows backend — keystroke injection via ctypes SendInput.

Uses the Win32 SendInput API directly through ctypes. No external
dependencies beyond the Python standard library.

Only imported on Windows (platform.system() == "Windows").
"""

import ctypes
import ctypes.wintypes
import time

# ---------------------------------------------------------------------------
# Win32 constants
# ---------------------------------------------------------------------------

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_EXTENDEDKEY = 0x0001

# Virtual key codes
VK_RETURN = 0x0D
VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_BACK = 0x08
VK_DELETE = 0x2E
VK_SPACE = 0x20
VK_UP = 0x26
VK_DOWN = 0x28
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_HOME = 0x24
VK_END = 0x23
VK_PRIOR = 0x21   # Page Up
VK_NEXT = 0x22    # Page Down
VK_INSERT = 0x2D
VK_CAPITAL = 0x14  # Caps Lock
VK_SNAPSHOT = 0x2C  # Print Screen
VK_F1 = 0x70
VK_F2 = 0x71
VK_F3 = 0x72
VK_F4 = 0x73
VK_F5 = 0x74
VK_F6 = 0x75
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78
VK_F10 = 0x79
VK_F11 = 0x7A
VK_F12 = 0x7B

# Modifier VKs
VK_CONTROL = 0x11
VK_MENU = 0x12     # Alt
VK_SHIFT = 0x10
VK_LWIN = 0x5B

# ---------------------------------------------------------------------------
# Key name mappings (BrainJack firmware names -> VK codes)
# ---------------------------------------------------------------------------

VK_MAP = {
    "ENTER": VK_RETURN, "RETURN": VK_RETURN,
    "TAB": VK_TAB, "ESCAPE": VK_ESCAPE, "ESC": VK_ESCAPE,
    "BACKSPACE": VK_BACK, "DELETE": VK_DELETE,
    "SPACE": VK_SPACE,
    "UP": VK_UP, "DOWN": VK_DOWN, "LEFT": VK_LEFT, "RIGHT": VK_RIGHT,
    "HOME": VK_HOME, "END": VK_END,
    "PAGEUP": VK_PRIOR, "PAGEDOWN": VK_NEXT,
    "INSERT": VK_INSERT, "CAPSLOCK": VK_CAPITAL,
    "PRINTSCREEN": VK_SNAPSHOT,
    "F1": VK_F1, "F2": VK_F2, "F3": VK_F3, "F4": VK_F4,
    "F5": VK_F5, "F6": VK_F6, "F7": VK_F7, "F8": VK_F8,
    "F9": VK_F9, "F10": VK_F10, "F11": VK_F11, "F12": VK_F12,
}

# Keys that need KEYEVENTF_EXTENDEDKEY
EXTENDED_KEYS = {
    VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT,
    VK_HOME, VK_END, VK_PRIOR, VK_NEXT,
    VK_INSERT, VK_DELETE, VK_SNAPSHOT,
    VK_LWIN,
}

MODIFIER_MAP = {
    "ctrl": VK_CONTROL, "control": VK_CONTROL,
    "alt": VK_MENU, "option": VK_MENU,
    "shift": VK_SHIFT,
    "cmd": VK_LWIN, "gui": VK_LWIN, "meta": VK_LWIN,
    "super": VK_LWIN, "win": VK_LWIN,
}

# Single character -> VK code (for combo keys)
# VkKeyScanW maps a char to VK + shift state, but for combos we need
# the base VK. Letters A-Z map to 0x41-0x5A, digits 0-9 to 0x30-0x39.
def _char_to_vk(ch: str) -> int | None:
    """Map a single printable character to its virtual key code."""
    c = ch.upper()
    if "A" <= c <= "Z":
        return ord(c)
    if "0" <= c <= "9":
        return ord(c)
    # For other chars, use VkKeyScanW
    try:
        result = ctypes.windll.user32.VkKeyScanW(ord(ch))
        if result == -1:
            return None
        return result & 0xFF  # low byte is VK code
    except Exception:
        return None


# ---------------------------------------------------------------------------
# ctypes structures for SendInput
# ---------------------------------------------------------------------------

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


def _send_input(*inputs: INPUT) -> int:
    """Call SendInput with an array of INPUT structs."""
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    return ctypes.windll.user32.SendInput(n, arr, ctypes.sizeof(INPUT))


def _make_key_input(vk: int, flags: int = 0) -> INPUT:
    """Build an INPUT struct for a single key event."""
    if vk in EXTENDED_KEYS:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    inp.union.ki.dwFlags = flags
    return inp


def _make_unicode_input(char: str, keyup: bool = False) -> INPUT:
    """Build an INPUT struct for a Unicode character event."""
    flags = KEYEVENTF_UNICODE
    if keyup:
        flags |= KEYEVENTF_KEYUP
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = 0
    inp.union.ki.wScan = ord(char)
    inp.union.ki.dwFlags = flags
    return inp


# ---------------------------------------------------------------------------
# Public API (matches the inject_* signature pattern in agent.py)
# ---------------------------------------------------------------------------

def inject_text(text: str) -> dict:
    """Type text using Unicode SendInput events."""
    try:
        for char in text:
            if char == "\n":
                # Send Enter key press + release
                _send_input(
                    _make_key_input(VK_RETURN),
                    _make_key_input(VK_RETURN, KEYEVENTF_KEYUP),
                )
            else:
                _send_input(
                    _make_unicode_input(char),
                    _make_unicode_input(char, keyup=True),
                )
            time.sleep(0.012)  # 12ms delay, matching other backends
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def inject_key(key: str) -> dict:
    """Press and release a single named key."""
    try:
        upper = key.upper()
        vk = VK_MAP.get(upper)
        if vk is None:
            # Try single character
            if len(key) == 1:
                vk = _char_to_vk(key)
            if vk is None:
                return {"ok": False, "error": f"unknown key: {key}"}
        _send_input(
            _make_key_input(vk),
            _make_key_input(vk, KEYEVENTF_KEYUP),
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def inject_combo(keys: str) -> dict:
    """Press a key combination like 'ctrl+c' or 'alt+shift+tab'."""
    parts = [p.strip() for p in keys.lower().split("+")]
    if not parts:
        return {"ok": False, "error": "empty combo"}

    try:
        *mods, main_key = parts

        # Resolve modifier VKs
        mod_vks = []
        for m in mods:
            vk = MODIFIER_MAP.get(m)
            if vk is None:
                return {"ok": False, "error": f"unknown modifier: {m}"}
            mod_vks.append(vk)

        # Resolve main key
        upper = main_key.upper()
        main_vk = VK_MAP.get(upper)
        if main_vk is None:
            if len(main_key) == 1:
                main_vk = _char_to_vk(main_key)
            if main_vk is None:
                # Check if it's actually a modifier used as the main key
                main_vk = MODIFIER_MAP.get(main_key)
            if main_vk is None:
                return {"ok": False, "error": f"unknown key: {main_key}"}

        # Press modifiers down
        inputs = []
        for vk in mod_vks:
            inputs.append(_make_key_input(vk))

        # Press and release main key
        inputs.append(_make_key_input(main_vk))
        inputs.append(_make_key_input(main_vk, KEYEVENTF_KEYUP))

        # Release modifiers in reverse order
        for vk in reversed(mod_vks):
            inputs.append(_make_key_input(vk, KEYEVENTF_KEYUP))

        _send_input(*inputs)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_context_extra() -> dict:
    """Return Windows-specific context info for the status command."""
    info = {}
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                info["active_window"] = buf.value
    except Exception:
        pass
    return info
