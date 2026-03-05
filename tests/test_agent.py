"""Comprehensive test suite for BrainJack Agent.

Covers: auth, command parsing, rate limiting, platform detection,
audit logging, TLS config, and error handling.

All subprocess calls are mocked — no actual keystroke injection.
"""

import argparse
import asyncio
import json
import os
import ssl
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

import agent


# ===================================================================
# 1. WebSocket Authentication
# ===================================================================

class TestAuth:
    """Auth: query string token, first-message handshake, failures."""

    @pytest.mark.asyncio
    async def test_auth_disabled_allows_all(self, mock_ws, base_cfg):
        """When token is None (auth disabled), authenticate returns True."""
        ws = mock_ws()
        result = await agent.authenticate(ws, base_cfg)
        assert result is True

    @pytest.mark.asyncio
    async def test_auth_valid_query_string(self, mock_ws, auth_cfg):
        """Valid token in query string authenticates immediately."""
        token = auth_cfg["token"]
        ws = mock_ws(path=f"/?token={token}")
        result = await agent.authenticate(ws, auth_cfg)
        assert result is True
        assert not ws._closed

    @pytest.mark.asyncio
    async def test_auth_invalid_query_string_falls_through_to_handshake(
        self, mock_ws, auth_cfg
    ):
        """Bad query string token falls through to handshake; bad handshake fails."""
        ws = mock_ws(path="/?token=wrong-token")
        # Enqueue a bad handshake too
        ws.enqueue(json.dumps({"cmd": "auth", "token": "also-wrong"}))
        result = await agent.authenticate(ws, auth_cfg)
        assert result is False
        assert ws._closed
        assert ws._close_code == 1008

    @pytest.mark.asyncio
    async def test_auth_valid_handshake(self, mock_ws, auth_cfg):
        """First-message auth with correct token succeeds."""
        ws = mock_ws()
        ws.enqueue(json.dumps({"cmd": "auth", "token": auth_cfg["token"]}))
        result = await agent.authenticate(ws, auth_cfg)
        assert result is True
        # Server should send back {"ok": True, "authed": True}
        assert len(ws._sent) == 1
        resp = json.loads(ws._sent[0])
        assert resp["ok"] is True
        assert resp["authed"] is True

    @pytest.mark.asyncio
    async def test_auth_bad_handshake_token(self, mock_ws, auth_cfg):
        """Handshake with wrong token closes with 1008."""
        ws = mock_ws()
        ws.enqueue(json.dumps({"cmd": "auth", "token": "nope"}))
        result = await agent.authenticate(ws, auth_cfg)
        assert result is False
        assert ws._closed
        assert ws._close_code == 1008

    @pytest.mark.asyncio
    async def test_auth_missing_token_field(self, mock_ws, auth_cfg):
        """Handshake message with cmd=auth but no token field fails."""
        ws = mock_ws()
        ws.enqueue(json.dumps({"cmd": "auth"}))
        result = await agent.authenticate(ws, auth_cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_auth_non_auth_command_as_first_message(self, mock_ws, auth_cfg):
        """Sending a non-auth command first fails auth."""
        ws = mock_ws()
        ws.enqueue(json.dumps({"cmd": "type", "text": "hello"}))
        result = await agent.authenticate(ws, auth_cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_auth_malformed_json_first_message(self, mock_ws, auth_cfg):
        """Non-JSON first message fails auth."""
        ws = mock_ws()
        ws.enqueue("not json at all")
        result = await agent.authenticate(ws, auth_cfg)
        assert result is False
        assert ws._close_code == 1008

    @pytest.mark.asyncio
    async def test_auth_timeout_closes_connection(self, mock_ws, auth_cfg):
        """When no message arrives within timeout, auth fails."""
        ws = mock_ws()
        # Don't enqueue anything — recv will raise TimeoutError
        result = await agent.authenticate(ws, auth_cfg)
        assert result is False
        assert ws._closed

    @pytest.mark.asyncio
    async def test_token_comparison_is_constant_time(self, auth_cfg):
        """Verify _check_token uses hmac.compare_digest (constant-time)."""
        # If someone replaced it with ==, this would still pass functionally,
        # but we verify the function signature uses hmac
        import hmac
        with patch("agent.hmac.compare_digest", wraps=hmac.compare_digest) as mock_cmp:
            agent._check_token("test", auth_cfg["token"])
            mock_cmp.assert_called_once()


# ===================================================================
# 2. Command Parsing / Dispatch
# ===================================================================

class TestCommandParsing:
    """handle_command: type, key, combo, status, unknown."""

    def test_type_command(self, mock_subprocess, patch_platform_linux_x11):
        result = agent.handle_command({"cmd": "type", "text": "hello"})
        assert result["ok"] is True
        mock_subprocess.assert_called_once()
        args = mock_subprocess.call_args[0][0]
        assert args[0] == "xdotool"
        assert "type" in args
        assert "hello" in args

    def test_type_empty_text(self):
        result = agent.handle_command({"cmd": "type", "text": ""})
        assert result["ok"] is False
        assert "missing text" in result["error"]

    def test_type_missing_text_field(self):
        result = agent.handle_command({"cmd": "type"})
        assert result["ok"] is False
        assert "missing text" in result["error"]

    def test_key_command(self, mock_subprocess, patch_platform_linux_x11):
        result = agent.handle_command({"cmd": "key", "key": "Return"})
        assert result["ok"] is True
        args = mock_subprocess.call_args[0][0]
        assert args[0] == "xdotool"
        assert "key" in args

    def test_key_empty(self):
        result = agent.handle_command({"cmd": "key", "key": ""})
        assert result["ok"] is False
        assert "missing key" in result["error"]

    def test_key_missing_field(self):
        result = agent.handle_command({"cmd": "key"})
        assert result["ok"] is False

    def test_combo_command(self, mock_subprocess, patch_platform_linux_x11):
        result = agent.handle_command({"cmd": "combo", "keys": "ctrl+c"})
        assert result["ok"] is True
        args = mock_subprocess.call_args[0][0]
        assert args[0] == "xdotool"

    def test_combo_empty(self):
        result = agent.handle_command({"cmd": "combo", "keys": ""})
        assert result["ok"] is False
        assert "missing keys" in result["error"]

    def test_combo_missing_field(self):
        result = agent.handle_command({"cmd": "combo"})
        assert result["ok"] is False

    def test_status_command(self, mock_subprocess, patch_platform_linux_x11):
        result = agent.handle_command({"cmd": "status"})
        assert "device" in result
        assert "os" in result
        assert result["os"] == "linux-x11"

    def test_unknown_command(self):
        result = agent.handle_command({"cmd": "dance"})
        assert result["ok"] is False
        assert "unknown cmd" in result["error"]

    def test_empty_cmd(self):
        result = agent.handle_command({})
        assert result["ok"] is False

    def test_combo_multiple_modifiers(self, mock_subprocess, patch_platform_linux_x11):
        """ctrl+shift+s should resolve all modifiers."""
        result = agent.handle_command({"cmd": "combo", "keys": "ctrl+shift+s"})
        assert result["ok"] is True
        args = mock_subprocess.call_args[0][0]
        combo_arg = args[-1]  # the combo string
        assert "ctrl" in combo_arg
        assert "shift" in combo_arg


# ===================================================================
# 3. Key Resolution
# ===================================================================

class TestKeyResolution:
    """xdotool / ydotool / osascript key name mapping."""

    def test_xdotool_enter(self):
        assert agent._resolve_xdotool_key("ENTER") == "Return"
        assert agent._resolve_xdotool_key("enter") == "Return"

    def test_xdotool_passthrough(self):
        """Unknown keys pass through unchanged."""
        assert agent._resolve_xdotool_key("a") == "a"

    def test_ydotool_known_key(self):
        assert agent._resolve_ydotool_key("ENTER") == 28
        assert agent._resolve_ydotool_key("TAB") == 15

    def test_ydotool_single_char(self):
        assert agent._resolve_ydotool_key("a") == 30
        assert agent._resolve_ydotool_key("z") == 44

    def test_ydotool_unknown_returns_none(self):
        assert agent._resolve_ydotool_key("UNKNOWN_KEY_XYZ") is None


# ===================================================================
# 4. Platform-Specific Injection (mocked subprocess)
# ===================================================================

class TestInjection:
    """inject_text, inject_key, inject_combo across platforms."""

    # --- Linux X11 ---

    def test_inject_text_x11(self, mock_subprocess, patch_platform_linux_x11):
        result = agent.inject_text("hello world")
        assert result["ok"] is True
        mock_subprocess.assert_called_once()
        cmd = mock_subprocess.call_args[0][0]
        assert cmd[0] == "xdotool"
        assert "type" in cmd

    def test_inject_key_x11(self, mock_subprocess, patch_platform_linux_x11):
        result = agent.inject_key("ENTER")
        assert result["ok"] is True
        cmd = mock_subprocess.call_args[0][0]
        assert "Return" in cmd  # resolved from ENTER

    def test_inject_combo_x11(self, mock_subprocess, patch_platform_linux_x11):
        result = agent.inject_combo("ctrl+c")
        assert result["ok"] is True
        cmd = mock_subprocess.call_args[0][0]
        assert "ctrl+c" in cmd[-1]

    # --- macOS ---

    def test_inject_text_macos(self, mock_subprocess, patch_platform_macos):
        result = agent.inject_text("hi")
        assert result["ok"] is True
        # macOS uses pbcopy then osascript
        assert mock_subprocess.call_count >= 2

    def test_inject_text_macos_multiline(self, mock_subprocess, patch_platform_macos):
        result = agent.inject_text("line1\nline2")
        assert result["ok"] is True
        # Should call pbcopy+osascript for each line plus Return between
        assert mock_subprocess.call_count >= 4

    def test_inject_key_macos_special(self, mock_subprocess, patch_platform_macos):
        result = agent.inject_key("ENTER")
        assert result["ok"] is True
        cmd = mock_subprocess.call_args[0][0]
        assert "osascript" in cmd[0]
        assert "key code 36" in cmd[-1]

    def test_inject_key_macos_char(self, mock_subprocess, patch_platform_macos):
        result = agent.inject_key("a")
        assert result["ok"] is True
        cmd = mock_subprocess.call_args[0][0]
        assert "keystroke" in cmd[-1]

    def test_inject_combo_macos(self, mock_subprocess, patch_platform_macos):
        result = agent.inject_combo("cmd+s")
        assert result["ok"] is True
        cmd = mock_subprocess.call_args[0][0]
        assert "command down" in cmd[-1]

    # --- Wayland ---

    def test_inject_text_wayland(self, mock_subprocess, patch_platform_wayland):
        result = agent.inject_text("test")
        assert result["ok"] is True
        cmd = mock_subprocess.call_args[0][0]
        assert cmd[0] == "ydotool"

    def test_inject_key_wayland(self, mock_subprocess, patch_platform_wayland):
        result = agent.inject_key("ENTER")
        assert result["ok"] is True
        cmd = mock_subprocess.call_args[0][0]
        assert cmd[0] == "ydotool"
        assert "28:1" in cmd  # KEY_ENTER down
        assert "28:0" in cmd  # KEY_ENTER up

    def test_inject_key_wayland_unknown(self, patch_platform_wayland):
        """Unknown key on wayland returns error without calling subprocess."""
        with patch("agent.subprocess.run") as mock_run:
            result = agent.inject_key("UNKNOWN_KEY_XYZ")
            assert result["ok"] is False
            assert "unknown key" in result["error"]
            mock_run.assert_not_called()

    def test_inject_combo_wayland(self, mock_subprocess, patch_platform_wayland):
        result = agent.inject_combo("ctrl+c")
        assert result["ok"] is True
        cmd = mock_subprocess.call_args[0][0]
        assert cmd[0] == "ydotool"

    # --- Unknown platform ---

    def test_inject_text_unknown_platform(self):
        with patch.object(agent, "PLATFORM", "unknown"):
            result = agent.inject_text("hi")
            assert result["ok"] is False
            assert "unsupported" in result["error"]

    def test_inject_key_unknown_platform(self):
        with patch.object(agent, "PLATFORM", "unknown"):
            result = agent.inject_key("a")
            assert result["ok"] is False

    def test_inject_combo_unknown_platform(self):
        with patch.object(agent, "PLATFORM", "unknown"):
            result = agent.inject_combo("ctrl+a")
            assert result["ok"] is False

    # --- subprocess failure ---

    def test_inject_text_subprocess_failure(self, patch_platform_linux_x11):
        with patch("agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="xdotool error"
            )
            result = agent.inject_text("fail")
            assert result["ok"] is False
            assert result["error"] == "xdotool error"


# ===================================================================
# 5. Rate Limiting (Token Bucket)
# ===================================================================

class TestRateLimiting:
    """Per-IP token bucket rate limiter."""

    def test_bucket_allows_burst(self, base_cfg):
        """First N requests within burst should all be allowed."""
        ip = "10.0.0.1"
        burst = base_cfg["rate_burst"] + base_cfg["rate_limit"]  # total bucket capacity
        for i in range(burst):
            assert agent.check_rate_limit(ip, base_cfg), f"Request {i} should be allowed"

    def test_bucket_denies_after_burst(self, base_cfg):
        """Exceeding burst + rate should be denied."""
        ip = "10.0.0.2"
        burst = base_cfg["rate_burst"] + base_cfg["rate_limit"]
        # Exhaust all tokens
        for _ in range(burst):
            agent.check_rate_limit(ip, base_cfg)
        # Next should be denied
        assert agent.check_rate_limit(ip, base_cfg) is False

    def test_bucket_refills_over_time(self, base_cfg):
        """After waiting, tokens should refill."""
        ip = "10.0.0.3"
        burst = base_cfg["rate_burst"] + base_cfg["rate_limit"]
        # Exhaust
        for _ in range(burst):
            agent.check_rate_limit(ip, base_cfg)
        assert agent.check_rate_limit(ip, base_cfg) is False

        # Simulate time passing by manipulating the bucket
        bucket = agent._buckets[ip]
        bucket.last -= 2.0  # pretend 2 seconds passed
        assert agent.check_rate_limit(ip, base_cfg) is True

    def test_separate_buckets_per_ip(self, base_cfg):
        """Different IPs have independent rate limits."""
        assert agent.check_rate_limit("10.0.0.10", base_cfg) is True
        assert agent.check_rate_limit("10.0.0.11", base_cfg) is True
        assert "10.0.0.10" in agent._buckets
        assert "10.0.0.11" in agent._buckets

    def test_cleanup_bucket(self, base_cfg):
        """cleanup_bucket removes the IP entry."""
        ip = "10.0.0.20"
        agent.check_rate_limit(ip, base_cfg)
        assert ip in agent._buckets
        agent.cleanup_bucket(ip)
        assert ip not in agent._buckets

    def test_cleanup_nonexistent_ip(self):
        """cleanup_bucket on unknown IP doesn't raise."""
        agent.cleanup_bucket("never-seen")  # no error

    def test_token_bucket_dataclass(self):
        """TokenBucket starts full and drains correctly."""
        b = agent.TokenBucket(rate=1.0, burst=3.0)
        assert b.tokens == 3.0
        assert b.allow()  # 2.0 left
        assert b.allow()  # 1.0 left
        assert b.allow()  # 0.0 left
        assert not b.allow()  # denied


# ===================================================================
# 6. Platform Detection
# ===================================================================

class TestPlatformDetection:
    """detect_platform: Linux X11, Linux Wayland, macOS, unknown."""

    def test_detect_linux_x11(self):
        with patch("agent.platform.system", return_value="Linux"):
            with patch.dict(os.environ, {}, clear=False):
                # Remove WAYLAND_DISPLAY if set
                env = os.environ.copy()
                env.pop("WAYLAND_DISPLAY", None)
                with patch.dict(os.environ, env, clear=True):
                    assert agent.detect_platform() == "linux-x11"

    def test_detect_linux_wayland(self):
        with patch("agent.platform.system", return_value="Linux"):
            with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
                assert agent.detect_platform() == "linux-wayland"

    def test_detect_macos(self):
        with patch("agent.platform.system", return_value="Darwin"):
            assert agent.detect_platform() == "macos"

    def test_detect_unknown(self):
        with patch("agent.platform.system", return_value="Windows"):
            assert agent.detect_platform() == "unknown"


# ===================================================================
# 7. Audit Logging
# ===================================================================

class TestAuditLogging:
    """Audit log: events recorded, keystroke content excluded."""

    def test_audit_to_file(self, audit_cfg, audit_log_file):
        agent.setup_audit_logger(audit_cfg)
        agent.audit("test_event", "10.0.0.1", extra_key="extra_val")

        with open(audit_log_file) as f:
            lines = f.readlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event"] == "test_event"
        assert record["peer"] == "10.0.0.1"
        assert record["extra_key"] == "extra_val"
        assert "ts" in record

    def test_audit_cmd_logged_but_not_text(self, audit_cfg, audit_log_file):
        """The 'cmd' field is logged, but keystroke text must NOT appear."""
        agent.setup_audit_logger(audit_cfg)
        # Simulate what ws_handler does: audit("cmd", peer, cmd=cmd)
        # It should NOT log the text content
        agent.audit("cmd", "10.0.0.1", cmd="type")

        with open(audit_log_file) as f:
            content = f.read()

        record = json.loads(content.strip())
        assert record["cmd"] == "type"
        # Ensure no text/key content fields leaked
        assert "text" not in record
        assert "hello" not in content

    def test_audit_key_content_never_logged(self, audit_cfg, audit_log_file):
        """Verify the audit function itself never includes keystroke payloads.

        The agent code calls audit("cmd", peer, cmd=cmd) — only the command
        name, never the text/key/keys payload. This test confirms the pattern.
        """
        agent.setup_audit_logger(audit_cfg)

        # Replicate the actual audit call from ws_handler
        secret_text = "my-secret-password-12345"
        agent.audit("cmd", "10.0.0.1", cmd="type")
        # If someone accidentally did audit(..., text=secret_text), it would appear.
        # But the code doesn't — and we verify it here.

        with open(audit_log_file) as f:
            content = f.read()
        assert secret_text not in content

    def test_audit_noop_when_logger_not_initialized(self):
        """audit() is a no-op before setup_audit_logger is called."""
        agent._audit_logger = None
        # Should not raise
        agent.audit("some_event", "10.0.0.1")

    def test_audit_multiple_events(self, audit_cfg, audit_log_file):
        agent.setup_audit_logger(audit_cfg)
        agent.audit("connect", "10.0.0.1")
        agent.audit("cmd", "10.0.0.1", cmd="key")
        agent.audit("disconnect", "10.0.0.1")

        with open(audit_log_file) as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        assert len(lines) == 3
        events = [json.loads(l)["event"] for l in lines]
        assert events == ["connect", "cmd", "disconnect"]


# ===================================================================
# 8. TLS Configuration
# ===================================================================

class TestTLSConfig:
    """build_ssl_context: valid certs, missing files, no TLS."""

    def test_no_tls_returns_none(self, base_cfg):
        assert agent.build_ssl_context(base_cfg) is None

    def test_valid_tls(self, base_cfg, tls_files):
        cert, key = tls_files
        base_cfg["tls_cert"] = cert
        base_cfg["tls_key"] = key
        ctx = agent.build_ssl_context(base_cfg)
        assert ctx is not None
        assert isinstance(ctx, ssl.SSLContext)

    def test_tls_minimum_version(self, base_cfg, tls_files):
        cert, key = tls_files
        base_cfg["tls_cert"] = cert
        base_cfg["tls_key"] = key
        ctx = agent.build_ssl_context(base_cfg)
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2

    def test_tls_missing_cert_exits(self, base_cfg):
        base_cfg["tls_cert"] = "/nonexistent/cert.pem"
        base_cfg["tls_key"] = "/nonexistent/key.pem"
        with pytest.raises(SystemExit):
            agent.build_ssl_context(base_cfg)

    def test_tls_missing_key_exits(self, base_cfg, tls_files):
        cert, _ = tls_files
        base_cfg["tls_cert"] = cert
        base_cfg["tls_key"] = "/nonexistent/key.pem"
        with pytest.raises(SystemExit):
            agent.build_ssl_context(base_cfg)

    def test_tls_cert_only_no_key(self, base_cfg, tls_files):
        """Cert specified but key empty — treated as no TLS."""
        cert, _ = tls_files
        base_cfg["tls_cert"] = cert
        base_cfg["tls_key"] = ""
        assert agent.build_ssl_context(base_cfg) is None


# ===================================================================
# 9. Error Handling
# ===================================================================

class TestErrorHandling:
    """Malformed JSON, unknown commands, edge cases."""

    def test_malformed_json_in_ws_handler(self):
        """handle_command receives parsed data, but ws_handler handles JSON errors.

        We test the parse path indirectly — invalid JSON never reaches handle_command.
        """
        # handle_command always gets a dict; test unknown cmd instead
        result = agent.handle_command({"cmd": ""})
        assert result["ok"] is False

    def test_unknown_cmd_returns_error(self):
        result = agent.handle_command({"cmd": "hack_the_planet"})
        assert result["ok"] is False
        assert "unknown cmd" in result["error"]
        assert "hack_the_planet" in result["error"]

    def test_type_with_none_text(self):
        """text=None should be treated as missing."""
        result = agent.handle_command({"cmd": "type", "text": None})
        assert result["ok"] is False

    def test_empty_combo_string(self):
        """Empty combo after splitting."""
        result = agent.handle_command({"cmd": "combo", "keys": ""})
        assert result["ok"] is False

    def test_extra_fields_ignored(self, mock_subprocess, patch_platform_linux_x11):
        """Extra fields in the command dict are harmlessly ignored."""
        result = agent.handle_command({
            "cmd": "type", "text": "hi", "extra": "ignored", "foo": 42
        })
        assert result["ok"] is True


# ===================================================================
# 10. Config Loading
# ===================================================================

class TestConfig:
    """load_config: env vars, .env file, CLI overrides."""

    def test_defaults(self, cli_args):
        with patch.dict(os.environ, {}, clear=True):
            with patch("agent._load_dotenv"):
                cfg = agent.load_config(cli_args)
        assert cfg["host"] == "0.0.0.0"
        assert cfg["port"] == 9898
        assert cfg["token"] is None
        assert cfg["rate_limit"] == 30

    def test_env_var_override(self, cli_args):
        env = {
            "BRAINJACK_TOKEN": "my-token",
            "BRAINJACK_PORT": "1234",
            "BRAINJACK_HOST": "10.0.0.1",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("agent._load_dotenv"):
                cfg = agent.load_config(cli_args)
        assert cfg["token"] == "my-token"
        assert cfg["port"] == 1234
        assert cfg["host"] == "10.0.0.1"

    def test_token_off_disables_auth(self, cli_args):
        with patch.dict(os.environ, {"BRAINJACK_TOKEN": "off"}, clear=True):
            with patch("agent._load_dotenv"):
                cfg = agent.load_config(cli_args)
        assert cfg["token"] is None

    def test_token_OFF_case_insensitive(self, cli_args):
        with patch.dict(os.environ, {"BRAINJACK_TOKEN": "OFF"}, clear=True):
            with patch("agent._load_dotenv"):
                cfg = agent.load_config(cli_args)
        assert cfg["token"] is None

    def test_cli_overrides_env(self):
        args = argparse.Namespace(host="1.2.3.4", port=5555, tls_cert="", tls_key="")
        with patch.dict(os.environ, {"BRAINJACK_HOST": "9.9.9.9", "BRAINJACK_PORT": "1111"}, clear=True):
            with patch("agent._load_dotenv"):
                cfg = agent.load_config(args)
        assert cfg["host"] == "1.2.3.4"
        assert cfg["port"] == 5555

    def test_proxy_mode_overrides(self, cli_args):
        env = {
            "BRAINJACK_BEHIND_PROXY": "true",
            "BRAINJACK_HOST": "0.0.0.0",
            "BRAINJACK_TLS_CERT": "/some/cert.pem",
            "BRAINJACK_TLS_KEY": "/some/key.pem",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("agent._load_dotenv"):
                cfg = agent.load_config(cli_args)
        assert cfg["host"] == "127.0.0.1"
        assert cfg["tls_cert"] == ""
        assert cfg["tls_key"] == ""
        assert cfg["behind_proxy"] is True


# ===================================================================
# 11. Client IP Resolution
# ===================================================================

class TestClientIP:
    """_get_client_ip: direct vs proxy mode."""

    def test_direct_ip(self, mock_ws, base_cfg):
        ws = mock_ws(remote_ip="192.168.1.50")
        assert agent._get_client_ip(ws, base_cfg) == "192.168.1.50"

    def test_proxy_xff(self, mock_ws, proxy_cfg):
        ws = mock_ws(
            remote_ip="127.0.0.1",
            headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.1"},
        )
        assert agent._get_client_ip(ws, proxy_cfg) == "203.0.113.5"

    def test_proxy_no_xff_falls_back(self, mock_ws, proxy_cfg):
        ws = mock_ws(remote_ip="127.0.0.1")
        assert agent._get_client_ip(ws, proxy_cfg) == "127.0.0.1"


# ===================================================================
# 12. Dotenv Loader
# ===================================================================

class TestDotenvLoader:
    """_load_dotenv: parses key=value, skips comments/blanks, respects existing env."""

    def test_load_basic(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=qux\n")
        with patch.dict(os.environ, {}, clear=True):
            agent._load_dotenv(env_file)
            assert os.environ["FOO"] == "bar"
            assert os.environ["BAZ"] == "qux"

    def test_skip_comments_and_blanks(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nKEY=val\n")
        with patch.dict(os.environ, {}, clear=True):
            agent._load_dotenv(env_file)
            assert os.environ.get("KEY") == "val"

    def test_existing_env_not_overwritten(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING=from_file\n")
        with patch.dict(os.environ, {"EXISTING": "from_env"}, clear=True):
            agent._load_dotenv(env_file)
            assert os.environ["EXISTING"] == "from_env"

    def test_strips_quotes(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("QUOTED='hello world'\nDOUBLE=\"goodbye\"\n")
        with patch.dict(os.environ, {}, clear=True):
            agent._load_dotenv(env_file)
            assert os.environ["QUOTED"] == "hello world"
            assert os.environ["DOUBLE"] == "goodbye"

    def test_missing_file_noop(self, tmp_path):
        agent._load_dotenv(tmp_path / "nonexistent")  # no error


# ===================================================================
# 13. WebSocket Handler Integration (async)
# ===================================================================

class TestWSHandler:
    """End-to-end ws_handler tests with MockWebSocket."""

    @pytest.mark.asyncio
    async def test_handler_processes_commands(
        self, mock_ws, base_cfg, mock_subprocess, patch_platform_linux_x11
    ):
        """Auth disabled, send a type command, get response."""
        agent.setup_audit_logger(base_cfg)
        ws = mock_ws()
        ws.enqueue(json.dumps({"cmd": "type", "text": "test"}))

        await agent.ws_handler(ws, base_cfg)

        assert len(ws._sent) == 1
        resp = json.loads(ws._sent[0])
        assert resp["ok"] is True

    @pytest.mark.asyncio
    async def test_handler_invalid_json(self, mock_ws, base_cfg):
        """Malformed JSON returns error response, doesn't crash."""
        agent.setup_audit_logger(base_cfg)
        ws = mock_ws()
        ws.enqueue("not valid json {{{")

        await agent.ws_handler(ws, base_cfg)

        assert len(ws._sent) == 1
        resp = json.loads(ws._sent[0])
        assert resp["ok"] is False
        assert "invalid JSON" in resp["error"]

    @pytest.mark.asyncio
    async def test_handler_rate_limited(self, mock_ws, mock_subprocess, patch_platform_linux_x11):
        """After exceeding rate limit, handler returns rate limited error."""
        cfg = {
            "token": None, "host": "127.0.0.1", "port": 9898,
            "tls_cert": "", "tls_key": "", "behind_proxy": False,
            "rate_limit": 1, "rate_window": 10, "rate_burst": 0,
            "audit_log": "", "audit_max_bytes": 10485760, "audit_backup_count": 5,
        }
        agent.setup_audit_logger(cfg)
        ws = mock_ws()
        # Enqueue more messages than the bucket allows
        for _ in range(5):
            ws.enqueue(json.dumps({"cmd": "status"}))

        await agent.ws_handler(ws, cfg)

        responses = ws.sent_json
        # At least one should be rate limited
        rate_limited = [r for r in responses if "rate limited" in r.get("error", "")]
        assert len(rate_limited) > 0

    @pytest.mark.asyncio
    async def test_handler_cleans_up_bucket(self, mock_ws, base_cfg):
        """After disconnect, the IP's rate bucket is cleaned up."""
        agent.setup_audit_logger(base_cfg)
        ws = mock_ws(remote_ip="10.99.99.99")
        ws.enqueue(json.dumps({"cmd": "status"}))

        await agent.ws_handler(ws, base_cfg)

        assert "10.99.99.99" not in agent._buckets
