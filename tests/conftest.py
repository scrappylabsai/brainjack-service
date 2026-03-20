"""Shared fixtures for BrainJack Service tests."""

import argparse
import asyncio
import json
import logging
import os
import ssl
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Ensure agent module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cli_args():
    """Minimal CLI args namespace (no overrides)."""
    return argparse.Namespace(host="", port=0, tls_cert="", tls_key="")


@pytest.fixture
def base_cfg():
    """Default config dict with auth disabled."""
    return {
        "token": None,
        "host": "127.0.0.1",
        "port": 9898,
        "tls_cert": "",
        "tls_key": "",
        "behind_proxy": False,
        "rate_limit": 30,
        "rate_window": 10,
        "rate_burst": 5,
        "audit_log": "",
        "audit_max_bytes": 10485760,
        "audit_backup_count": 5,
    }


@pytest.fixture
def auth_cfg(base_cfg):
    """Config with auth enabled."""
    base_cfg["token"] = "test-secret-token-12345"
    return base_cfg


@pytest.fixture
def proxy_cfg(auth_cfg):
    """Config with proxy mode enabled."""
    auth_cfg["behind_proxy"] = True
    auth_cfg["host"] = "127.0.0.1"
    return auth_cfg


# ---------------------------------------------------------------------------
# Rate limiter cleanup
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_rate_buckets():
    """Clear per-IP rate limit buckets between tests."""
    agent._buckets.clear()
    yield
    agent._buckets.clear()


# ---------------------------------------------------------------------------
# Audit logger fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def audit_log_file(tmp_path):
    """Provide a temp file path for audit log output."""
    return str(tmp_path / "audit.jsonl")


@pytest.fixture
def audit_cfg(base_cfg, audit_log_file):
    """Config with file-based audit logging enabled."""
    base_cfg["audit_log"] = audit_log_file
    return base_cfg


@pytest.fixture(autouse=True)
def reset_audit_logger():
    """Reset the global audit logger between tests."""
    agent._audit_logger = None
    yield
    agent._audit_logger = None


# ---------------------------------------------------------------------------
# Mock WebSocket
# ---------------------------------------------------------------------------

class MockWebSocket:
    """Fake WebSocket with controllable request/headers and message queue."""

    def __init__(self, remote_ip="192.168.1.100", path="/", headers=None):
        self.remote_address = (remote_ip, 54321)
        self._messages = asyncio.Queue()
        self._sent = []
        self._closed = False
        self._close_code = None
        self._close_reason = None

        # Build a request-like object
        _headers = headers or {}
        self.request = MagicMock()
        self.request.path = path
        self.request.headers = MagicMock()
        self.request.headers.get = lambda key, default="": _headers.get(key, default)

    def enqueue(self, message: str):
        """Stage a message to be received by the server."""
        self._messages.put_nowait(message)

    async def recv(self):
        try:
            return self._messages.get_nowait()
        except asyncio.QueueEmpty:
            raise asyncio.TimeoutError("no message queued")

    async def send(self, data):
        self._sent.append(data)

    async def close(self, code=1000, reason=""):
        self._closed = True
        self._close_code = code
        self._close_reason = reason

    @property
    def sent_json(self):
        """All sent messages parsed as JSON."""
        return [json.loads(m) for m in self._sent]

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return self._messages.get_nowait()
        except asyncio.QueueEmpty:
            raise StopAsyncIteration


@pytest.fixture
def mock_ws():
    """Factory for MockWebSocket instances."""
    def _make(**kwargs):
        return MockWebSocket(**kwargs)
    return _make


# ---------------------------------------------------------------------------
# TLS cert/key fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tls_files(tmp_path):
    """Generate a self-signed cert+key pair for TLS tests."""
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"

    # Use openssl to generate a self-signed cert
    import subprocess
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key_path), "-out", str(cert_path),
            "-days", "1", "-nodes",
            "-subj", "/CN=brainjack-test",
        ],
        capture_output=True, check=True,
    )
    return str(cert_path), str(key_path)


# ---------------------------------------------------------------------------
# Platform patching helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def patch_platform_linux_x11():
    """Patch PLATFORM to linux-x11."""
    with patch.object(agent, "PLATFORM", "linux-x11"):
        yield


@pytest.fixture
def patch_platform_macos():
    """Patch PLATFORM to macos."""
    with patch.object(agent, "PLATFORM", "macos"):
        yield


@pytest.fixture
def patch_platform_wayland():
    """Patch PLATFORM to linux-wayland."""
    with patch.object(agent, "PLATFORM", "linux-wayland"):
        yield


@pytest.fixture
def mock_subprocess():
    """Patch subprocess.run to capture calls without executing."""
    with patch("agent.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        yield mock_run
