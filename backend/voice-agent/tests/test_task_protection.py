"""Tests for ECS Task Scale-in Protection client."""

import os

# Set env vars before imports
os.environ.setdefault("AWS_REGION", "us-east-1")

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

try:
    import aiohttp
except ImportError:
    pytest.skip(
        "aiohttp not available (container-only dependency)", allow_module_level=True
    )

from app.task_protection import TaskProtection, PROTECTION_EXPIRY_MINUTES, MAX_RETRIES


class TestTaskProtectionAvailability:
    """Tests for ECS Agent API availability detection."""

    def test_not_available_without_env(self):
        """Protection is unavailable when ECS_AGENT_URI not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ECS_AGENT_URI", None)
            tp = TaskProtection()
            assert tp.is_available is False

    def test_available_with_env(self):
        """Protection is available when ECS_AGENT_URI is set."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()
            assert tp.is_available is True

    def test_not_protected_initially(self):
        """Task starts unprotected."""
        tp = TaskProtection()
        assert tp.is_protected is False


class TestSetProtected:
    """Tests for set_protected() method."""

    @pytest.mark.asyncio
    async def test_noop_when_unavailable(self):
        """Returns False and doesn't make API calls when unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ECS_AGENT_URI", None)
            tp = TaskProtection()
            result = await tp.set_protected(True)
            assert result is False
            assert tp.is_protected is False

    @pytest.mark.asyncio
    async def test_noop_when_already_in_desired_state(self):
        """Skips API call when protection is already in desired state."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()
            tp._protected = True  # Already protected
            result = await tp.set_protected(True)
            assert result is True  # Returns True (already in state)

    @pytest.mark.asyncio
    async def test_enable_protection(self):
        """Enables protection via ECS Agent API."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()

            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock(spec=aiohttp.ClientSession)
            mock_session.put = MagicMock(return_value=mock_resp)
            mock_session.closed = False
            tp._session = mock_session

            result = await tp.set_protected(True)
            assert result is True
            assert tp.is_protected is True

            # Verify the API call
            mock_session.put.assert_called_once()
            call_args = mock_session.put.call_args
            assert "/task-protection/v1/state" in call_args[0][0]
            payload = call_args[1]["json"]
            assert payload["ProtectionEnabled"] is True
            assert payload["ExpiresInMinutes"] == PROTECTION_EXPIRY_MINUTES

    @pytest.mark.asyncio
    async def test_disable_protection(self):
        """Disables protection via ECS Agent API."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()
            tp._protected = True  # Start protected

            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock(spec=aiohttp.ClientSession)
            mock_session.put = MagicMock(return_value=mock_resp)
            mock_session.closed = False
            tp._session = mock_session

            result = await tp.set_protected(False)
            assert result is True
            assert tp.is_protected is False

            # Verify no ExpiresInMinutes when disabling
            payload = mock_session.put.call_args[1]["json"]
            assert payload["ProtectionEnabled"] is False
            assert "ExpiresInMinutes" not in payload

    @pytest.mark.asyncio
    async def test_api_error_returns_false(self):
        """Returns False on non-200 API response."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()

            mock_resp = AsyncMock()
            mock_resp.status = 400
            mock_resp.text = AsyncMock(return_value="Bad Request")
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock(spec=aiohttp.ClientSession)
            mock_session.put = MagicMock(return_value=mock_resp)
            mock_session.closed = False
            tp._session = mock_session

            result = await tp.set_protected(True, retry=False)
            assert result is False
            assert tp.is_protected is False

    @pytest.mark.asyncio
    async def test_network_error_returns_false(self):
        """Returns False on network exception."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()

            mock_session = AsyncMock(spec=aiohttp.ClientSession)
            mock_session.put = MagicMock(
                side_effect=aiohttp.ClientError("Connection refused")
            )
            mock_session.closed = False
            tp._session = mock_session

            result = await tp.set_protected(True, retry=False)
            assert result is False
            assert tp.is_protected is False

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        """Retries with backoff on API failure."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()

            # First two calls fail, third succeeds
            mock_resp_fail = AsyncMock()
            mock_resp_fail.status = 500
            mock_resp_fail.text = AsyncMock(return_value="Internal Error")
            mock_resp_fail.__aenter__ = AsyncMock(return_value=mock_resp_fail)
            mock_resp_fail.__aexit__ = AsyncMock(return_value=None)

            mock_resp_success = AsyncMock()
            mock_resp_success.status = 200
            mock_resp_success.__aenter__ = AsyncMock(return_value=mock_resp_success)
            mock_resp_success.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock(spec=aiohttp.ClientSession)
            mock_session.put = MagicMock(
                side_effect=[mock_resp_fail, mock_resp_fail, mock_resp_success]
            )
            mock_session.closed = False
            tp._session = mock_session

            result = await tp.set_protected(True, retry=True)
            assert result is True
            assert tp.is_protected is True
            assert mock_session.put.call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        """Returns False after all retries exhausted."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()

            mock_resp = AsyncMock()
            mock_resp.status = 500
            mock_resp.text = AsyncMock(return_value="Internal Error")
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock(spec=aiohttp.ClientSession)
            mock_session.put = MagicMock(return_value=mock_resp)
            mock_session.closed = False
            tp._session = mock_session

            result = await tp.set_protected(True, retry=True)
            assert result is False
            assert tp.is_protected is False
            assert mock_session.put.call_count == MAX_RETRIES


class TestRenewIfProtected:
    """Tests for renew_if_protected() method."""

    @pytest.mark.asyncio
    async def test_noop_when_not_protected(self):
        """Skips renewal when not currently protected."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()
            tp._protected = False
            result = await tp.renew_if_protected()
            assert result is False

    @pytest.mark.asyncio
    async def test_noop_when_unavailable(self):
        """Skips renewal when ECS Agent not available."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ECS_AGENT_URI", None)
            tp = TaskProtection()
            tp._protected = True
            result = await tp.renew_if_protected()
            assert result is False

    @pytest.mark.asyncio
    async def test_renews_when_protected(self):
        """Renews protection with ExpiresInMinutes."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()
            tp._protected = True

            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock(spec=aiohttp.ClientSession)
            mock_session.put = MagicMock(return_value=mock_resp)
            mock_session.closed = False
            tp._session = mock_session

            result = await tp.renew_if_protected()
            assert result is True

            payload = mock_session.put.call_args[1]["json"]
            assert payload["ProtectionEnabled"] is True
            assert payload["ExpiresInMinutes"] == PROTECTION_EXPIRY_MINUTES

    @pytest.mark.asyncio
    async def test_renewal_failure(self):
        """Returns False on renewal failure without changing state."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()
            tp._protected = True

            mock_resp = AsyncMock()
            mock_resp.status = 500
            mock_resp.text = AsyncMock(return_value="Error")
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock(spec=aiohttp.ClientSession)
            mock_session.put = MagicMock(return_value=mock_resp)
            mock_session.closed = False
            tp._session = mock_session

            result = await tp.renew_if_protected()
            assert result is False
            # Protection state should NOT change on renewal failure
            assert tp.is_protected is True


class TestSessionReuse:
    """Tests for HTTP session lifecycle."""

    @pytest.mark.asyncio
    async def test_creates_session_on_first_call(self):
        """Creates aiohttp session lazily on first API call."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()
            assert tp._session is None

            with patch("app.task_protection.aiohttp.ClientSession") as MockSession:
                mock_session_instance = AsyncMock()
                mock_session_instance.closed = False
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
                mock_resp.__aexit__ = AsyncMock(return_value=None)
                mock_session_instance.put = MagicMock(return_value=mock_resp)
                MockSession.return_value = mock_session_instance

                await tp.set_protected(True)
                MockSession.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_closes_session(self):
        """close() properly closes the HTTP session."""
        with patch.dict(os.environ, {"ECS_AGENT_URI": "http://localhost:51678"}):
            tp = TaskProtection()
            mock_session = AsyncMock(spec=aiohttp.ClientSession)
            mock_session.closed = False
            tp._session = mock_session

            await tp.close()
            mock_session.close.assert_called_once()
            assert tp._session is None

    @pytest.mark.asyncio
    async def test_close_noop_when_no_session(self):
        """close() is safe to call when no session exists."""
        tp = TaskProtection()
        await tp.close()  # Should not raise
