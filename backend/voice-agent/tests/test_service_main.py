"""
Tests for the Pipecat Voice Pipeline aiohttp service.

Run with: pytest tests/test_service_main.py -v
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from aiohttp import web
    from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
    import structlog  # noqa: F401 - required transitively by app modules
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (aiohttp/structlog)",
        allow_module_level=True,
    )

# Set environment variables before importing app
os.environ["AWS_REGION"] = "us-east-1"
os.environ["VOICE_ID"] = "test-voice-id"


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    @pytest.fixture
    def app(self):
        """Create the aiohttp application with mock pipeline_manager."""
        import app.service_main as sm
        from app.service_main import create_app

        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {
            "status": "healthy",
            "active_sessions": 0,
            "session_ids": [],
        }
        sm.pipeline_manager = mock_manager
        return create_app()

    @pytest.mark.asyncio
    async def test_health_returns_healthy(self, aiohttp_client, app):
        """Test that /health returns healthy status."""
        client = await aiohttp_client(app)
        response = await client.get("/health")

        assert response.status == 200
        data = await response.json()
        assert data["status"] == "healthy"
        assert "active_sessions" in data
        assert "session_ids" in data

    @pytest.mark.asyncio
    async def test_health_shows_zero_sessions_initially(self, aiohttp_client, app):
        """Test that /health shows 0 active sessions on startup."""
        client = await aiohttp_client(app)
        response = await client.get("/health")

        data = await response.json()
        assert data["active_sessions"] == 0
        assert data["session_ids"] == []


class TestStatusEndpoint:
    """Tests for /status endpoint."""

    @pytest.fixture
    def app(self):
        """Create the aiohttp application with mock pipeline_manager."""
        import app.service_main as sm
        from app.service_main import create_app

        mock_manager = MagicMock()
        mock_manager.get_status.return_value = {
            "status": "healthy",
            "active_sessions": 0,
            "session_ids": [],
        }
        sm.pipeline_manager = mock_manager
        return create_app()

    @pytest.mark.asyncio
    async def test_status_returns_healthy(self, aiohttp_client, app):
        """Test that /status returns healthy status."""
        client = await aiohttp_client(app)
        response = await client.get("/status")

        assert response.status == 200
        data = await response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_status_matches_health(self, aiohttp_client, app):
        """Test that /status returns same data as /health."""
        client = await aiohttp_client(app)

        health_response = await client.get("/health")
        status_response = await client.get("/status")

        health_data = await health_response.json()
        status_data = await status_response.json()

        assert health_data == status_data


class TestCallEndpoint:
    """Tests for /call endpoint."""

    @pytest.fixture
    def app(self):
        """Create the aiohttp application with mock pipeline_manager."""
        import app.service_main as sm
        from app.service_main import create_app, PipelineManager

        mock_manager = MagicMock(spec=PipelineManager)
        mock_manager.get_status.return_value = {
            "status": "healthy",
            "active_sessions": 0,
            "session_ids": [],
        }
        mock_manager.start_call = AsyncMock()
        sm.pipeline_manager = mock_manager
        return create_app()

    @pytest.mark.asyncio
    async def test_call_missing_room_url(self, aiohttp_client, app):
        """Test /call rejects request missing room_url."""
        client = await aiohttp_client(app)
        response = await client.post(
            "/call",
            json={
                "room_token": "test-token",
                "session_id": "test-session",
            },
        )

        assert response.status == 400
        data = await response.json()
        assert data["status"] == "error"
        assert "room_url" in data["error"]

    @pytest.mark.asyncio
    async def test_call_missing_room_token(self, aiohttp_client, app):
        """Test /call rejects request missing room_token."""
        client = await aiohttp_client(app)
        response = await client.post(
            "/call",
            json={
                "room_url": "https://test.daily.co/room",
                "session_id": "test-session",
            },
        )

        assert response.status == 400
        data = await response.json()
        assert data["status"] == "error"
        assert "room_token" in data["error"]

    @pytest.mark.asyncio
    async def test_call_missing_session_id(self, aiohttp_client, app):
        """Test /call rejects request missing session_id."""
        client = await aiohttp_client(app)
        response = await client.post(
            "/call",
            json={
                "room_url": "https://test.daily.co/room",
                "room_token": "test-token",
            },
        )

        assert response.status == 400
        data = await response.json()
        assert data["status"] == "error"
        assert "session_id" in data["error"]

    @pytest.mark.asyncio
    async def test_call_missing_all_fields(self, aiohttp_client, app):
        """Test /call rejects empty request."""
        client = await aiohttp_client(app)
        response = await client.post("/call", json={})

        assert response.status == 400
        data = await response.json()
        assert data["status"] == "error"

    @pytest.mark.asyncio
    @patch("app.pipeline_ecs.create_voice_pipeline")
    async def test_call_success(self, mock_pipeline, aiohttp_client, app):
        """Test successful call initiation."""
        import app.service_main as sm

        sm.pipeline_manager.start_call = AsyncMock(
            return_value={
                "status": "started",
                "session_id": "test-session-1",
                "call_id": "call-123",
            }
        )

        client = await aiohttp_client(app)
        response = await client.post(
            "/call",
            json={
                "room_url": "https://test.daily.co/test-room",
                "room_token": "test-token-123",
                "session_id": "test-session-1",
            },
        )

        assert response.status == 200
        data = await response.json()
        assert data["status"] == "started"
        assert data["session_id"] == "test-session-1"
        assert "call_id" in data

    @pytest.mark.asyncio
    @patch("app.pipeline_ecs.create_voice_pipeline")
    async def test_call_with_custom_prompt(self, mock_pipeline, aiohttp_client, app):
        """Test call with custom system prompt."""
        import app.service_main as sm

        sm.pipeline_manager.start_call = AsyncMock(
            return_value={
                "status": "started",
                "session_id": "test-session-2",
                "call_id": "call-456",
            }
        )

        client = await aiohttp_client(app)
        response = await client.post(
            "/call",
            json={
                "room_url": "https://test.daily.co/test-room",
                "room_token": "test-token-123",
                "session_id": "test-session-2",
                "system_prompt": "You are a customer service agent.",
            },
        )

        assert response.status == 200
        data = await response.json()
        assert data["status"] == "started"

    @pytest.mark.asyncio
    @patch("app.pipeline_ecs.create_voice_pipeline")
    async def test_call_with_dialin_settings(self, mock_pipeline, aiohttp_client, app):
        """Test call with dial-in settings."""
        import app.service_main as sm

        sm.pipeline_manager.start_call = AsyncMock(
            return_value={
                "status": "started",
                "session_id": "test-session-3",
                "call_id": "call-789",
            }
        )

        client = await aiohttp_client(app)
        response = await client.post(
            "/call",
            json={
                "room_url": "https://test.daily.co/test-room",
                "room_token": "test-token-123",
                "session_id": "test-session-3",
                "dialin_settings": {
                    "call_id": "dial-123",
                    "call_domain": "test.domain.com",
                    "sip_uri": "sip:test@domain.com",
                },
            },
        )

        assert response.status == 200
        data = await response.json()
        assert data["status"] == "started"


class TestPipelineManager:
    """Tests for PipelineManager class."""

    @pytest.fixture
    def manager(self):
        """Create a fresh PipelineManager instance."""
        from app.service_main import PipelineManager

        mock_config = MagicMock()
        mock_config.providers = MagicMock()
        mock_config.providers.stt_provider = "deepgram"
        mock_config.providers.tts_provider = "cartesia"
        mock_config.voice_id = "test-voice"
        mock_config.system_prompt = "Test prompt"
        mock_config.region = "us-east-1"
        mock_config.environment = "test"
        mock_config.session_table_name = None
        return PipelineManager(config=mock_config)

    def test_initial_status(self, manager):
        """Test initial status shows no sessions."""
        status = manager.get_status()
        assert status["status"] == "healthy"
        assert status["active_sessions"] == 0
        assert status["session_ids"] == []

    @pytest.mark.asyncio
    @patch("app.service_main.create_voice_pipeline")
    @patch("app.service_main.create_metrics_collector")
    async def test_start_call_creates_session(
        self, mock_collector, mock_pipeline, manager
    ):
        """Test that start_call adds session to active_sessions."""
        mock_task = MagicMock()
        mock_transport = MagicMock()
        mock_transport.cleanup = AsyncMock()
        mock_pipeline.return_value = (mock_task, mock_transport)
        mock_collector.return_value = MagicMock()

        result = await manager.start_call(
            room_url="https://test.daily.co/room",
            room_token="token123",
            session_id="session-123",
        )

        assert result["status"] == "started"
        assert result["session_id"] == "session-123"
        assert "call_id" in result

        # Session should be in active_sessions
        assert "session-123" in manager.active_sessions

    @pytest.mark.asyncio
    @patch("app.service_main.create_voice_pipeline")
    @patch("app.service_main.create_metrics_collector")
    async def test_start_call_duplicate_session(
        self, mock_collector, mock_pipeline, manager
    ):
        """Test that duplicate session_id returns error."""
        mock_task = MagicMock()
        mock_transport = MagicMock()
        mock_transport.cleanup = AsyncMock()
        mock_pipeline.return_value = (mock_task, mock_transport)
        mock_collector.return_value = MagicMock()

        # Start first call
        await manager.start_call(
            room_url="https://test.daily.co/room",
            room_token="token123",
            session_id="dup-session",
        )

        # Try to start duplicate
        result = await manager.start_call(
            room_url="https://test.daily.co/room2",
            room_token="token456",
            session_id="dup-session",
        )

        assert result["status"] == "error"
        assert "already active" in result["error"]

    @pytest.mark.asyncio
    @patch("app.service_main.create_voice_pipeline")
    @patch("app.service_main.create_metrics_collector")
    async def test_status_reflects_active_sessions(
        self, mock_collector, mock_pipeline, manager
    ):
        """Test that get_status reflects active session count."""
        mock_task = MagicMock()
        mock_transport = MagicMock()
        mock_transport.cleanup = AsyncMock()
        mock_pipeline.return_value = (mock_task, mock_transport)
        mock_collector.return_value = MagicMock()

        # Start a call
        await manager.start_call(
            room_url="https://test.daily.co/room",
            room_token="token123",
            session_id="status-test-session",
        )

        status = manager.get_status()
        assert status["active_sessions"] == 1
        assert "status-test-session" in status["session_ids"]


class TestErrorCategorization:
    """Tests for error categorization (already tested in test_observability.py but included for completeness)."""

    def test_categorize_stt_error(self):
        """Test STT error categorization."""
        from app.service_main import ErrorCategory, categorize_error

        error = Exception("Deepgram transcription failed")
        assert categorize_error(error) == ErrorCategory.STT

    def test_categorize_llm_error(self):
        """Test LLM error categorization."""
        from app.service_main import ErrorCategory, categorize_error

        error = Exception("Bedrock model invocation failed")
        assert categorize_error(error) == ErrorCategory.LLM

    def test_categorize_tts_error(self):
        """Test TTS error categorization."""
        from app.service_main import ErrorCategory, categorize_error

        error = Exception("Cartesia synthesis error")
        assert categorize_error(error) == ErrorCategory.TTS

    def test_categorize_transport_error(self):
        """Test transport error categorization."""
        from app.service_main import ErrorCategory, categorize_error

        error = Exception("Daily transport connection failed")
        assert categorize_error(error) == ErrorCategory.TRANSPORT

    def test_categorize_config_error(self):
        """Test config error categorization."""
        from app.service_main import ErrorCategory, categorize_error

        error = Exception("Missing required api_key")
        assert categorize_error(error) == ErrorCategory.CONFIG

    def test_categorize_unknown_error(self):
        """Test unknown error categorization."""
        from app.service_main import ErrorCategory, categorize_error

        error = Exception("Something unexpected happened")
        assert categorize_error(error) == ErrorCategory.UNKNOWN


class TestPipelineConfig:
    """Tests for PipelineConfig from pipeline_ecs."""

    def test_pipeline_config_creation(self):
        """Test PipelineConfig dataclass from pipeline_ecs."""
        from app.pipeline_ecs import PipelineConfig

        config = PipelineConfig(
            room_url="https://test.daily.co/room",
            room_token="token123",
            session_id="session123",
            system_prompt="Test prompt",
            voice_id="test-voice",
            aws_region="us-east-1",
        )

        assert config.room_url == "https://test.daily.co/room"
        assert config.session_id == "session123"
        assert config.aws_region == "us-east-1"
        assert config.dialin_settings is None

    def test_pipeline_config_with_dialin(self):
        """Test PipelineConfig with dial-in settings."""
        from app.pipeline_ecs import PipelineConfig, DialinSettings

        dialin = DialinSettings(
            call_id="call-123",
            call_domain="domain.com",
            sip_uri="sip:test@domain.com",
        )

        config = PipelineConfig(
            room_url="https://test.daily.co/room",
            room_token="token123",
            session_id="session123",
            system_prompt="Test prompt",
            voice_id="test-voice",
            aws_region="us-east-1",
            dialin_settings=dialin,
        )

        assert config.dialin_settings is not None
        assert config.dialin_settings.call_id == "call-123"
