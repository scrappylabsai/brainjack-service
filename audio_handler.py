"""
Audio return handler for BrainJack agent.

Calls fleet TTS to synthesize speech, then sends MP3 audio
back to the iOS client over the existing WebSocket connection.
"""

import asyncio
import base64
import json
import os
from urllib.request import Request, urlopen
from urllib.error import URLError

# TTS endpoint — unified-tts proxy on Mother (OpenAI-compatible)
# Override via BRAINJACK_TTS_URL env var
_TTS_URLS = [
    os.environ.get("BRAINJACK_TTS_URL", "http://192.168.4.139:8765"),
    "http://100.95.104.47:8765",   # Mother Tailscale fallback
    "http://192.168.4.110:8765",   # Zhaan LAN
    "http://100.84.39.82:8765",    # Zhaan Tailscale
]

_DEFAULT_VOICE = os.environ.get("BRAINJACK_TTS_VOICE", "ryan")


def _fetch_tts_sync(text: str, voice: str) -> bytes | None:
    """Synchronous TTS fetch with failover. Returns MP3 bytes or None."""
    payload = json.dumps({"input": text, "voice": voice}).encode()

    for base_url in _TTS_URLS:
        url = f"{base_url}/v1/audio/speech"
        try:
            req = Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return resp.read()
        except (URLError, TimeoutError, OSError):
            continue

    return None


async def handle_speak(text: str, voice: str | None, websocket) -> None:
    """Synthesize speech via fleet TTS and send MP3 back over WebSocket.

    Runs the HTTP fetch in a thread to avoid blocking the event loop.
    """
    if not text.strip():
        await websocket.send(json.dumps({"ok": False, "error": "empty text"}))
        return

    voice = voice or _DEFAULT_VOICE

    # Ack immediately so client knows we're working on it (prevents timeout)
    await websocket.send(json.dumps({"cmd": "audio_pending", "text": text[:80]}))

    # Run sync HTTP in threadpool
    loop = asyncio.get_running_loop()
    mp3_data = await loop.run_in_executor(None, _fetch_tts_sync, text, voice)

    if mp3_data is None:
        await websocket.send(json.dumps({
            "cmd": "audio_error",
            "error": "TTS unavailable — all endpoints failed",
        }))
        return

    # Send audio back as base64-encoded MP3
    audio_b64 = base64.b64encode(mp3_data).decode("ascii")
    await websocket.send(json.dumps({
        "cmd": "audio",
        "format": "mp3",
        "data": audio_b64,
        "size": len(mp3_data),
    }))
