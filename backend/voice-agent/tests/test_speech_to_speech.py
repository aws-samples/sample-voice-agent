"""Tests for speech-to-speech pipeline mode configuration and factory.

Tests cover:
- PipelineConfig with pipeline_mode field
- ProviderConfig with pipeline_mode field
- Voice mapping for Nova Sonic
- create_voice_pipeline mode dispatching
- create_s2s_service factory

Run with: pytest tests/test_speech_to_speech.py -v
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    import structlog  # noqa: F401 - required transitively by app modules
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (structlog)",
        allow_module_level=True,
    )

os.environ.setdefault("AWS_REGION", "us-east-1")


class TestPipelineConfigMode:
    """Tests for pipeline_mode field on PipelineConfig."""

    def test_default_pipeline_mode_is_cascaded(self):
        """PipelineConfig defaults to cascaded mode."""
        from app.pipeline_ecs import PipelineConfig

        config = PipelineConfig(
            room_url="https://test.daily.co/room",
            room_token="token",
            session_id="sess-1",
            system_prompt="Test",
            voice_id="matthew",
            aws_region="us-east-1",
        )
        assert config.pipeline_mode == "cascaded"

    def test_pipeline_mode_can_be_set(self):
        """PipelineConfig accepts speech-to-speech mode."""
        from app.pipeline_ecs import PipelineConfig

        config = PipelineConfig(
            room_url="https://test.daily.co/room",
            room_token="token",
            session_id="sess-1",
            system_prompt="Test",
            voice_id="matthew",
            aws_region="us-east-1",
            pipeline_mode="speech-to-speech",
        )
        assert config.pipeline_mode == "speech-to-speech"


class TestProviderConfigMode:
    """Tests for pipeline_mode field on ProviderConfig."""

    def test_default_pipeline_mode(self):
        """ProviderConfig defaults to cascaded."""
        from app.services.config_service import ProviderConfig

        config = ProviderConfig()
        assert config.pipeline_mode == "cascaded"

    def test_pipeline_mode_speech_to_speech(self):
        """ProviderConfig accepts speech-to-speech."""
        from app.services.config_service import ProviderConfig

        config = ProviderConfig(pipeline_mode="speech-to-speech")
        assert config.pipeline_mode == "speech-to-speech"


class TestNovaSonicVoiceMapping:
    """Tests for Nova Sonic voice ID resolution."""

    def test_none_returns_default(self):
        """None voice ID returns default matthew."""
        from app.services.factory import _resolve_voice_for_nova_sonic

        assert _resolve_voice_for_nova_sonic(None) == "matthew"

    def test_empty_returns_default(self):
        """Empty voice ID returns default matthew."""
        from app.services.factory import _resolve_voice_for_nova_sonic

        assert _resolve_voice_for_nova_sonic("") == "matthew"

    def test_nova_sonic_name_passthrough(self):
        """Nova Sonic voice names pass through unchanged."""
        from app.services.factory import _resolve_voice_for_nova_sonic

        assert _resolve_voice_for_nova_sonic("matthew") == "matthew"
        assert _resolve_voice_for_nova_sonic("ruth") == "ruth"
        assert _resolve_voice_for_nova_sonic("tiffany") == "tiffany"
        assert _resolve_voice_for_nova_sonic("amy") == "amy"

    def test_cartesia_uuid_maps_to_nova_sonic(self):
        """Cartesia UUIDs map to appropriate Nova Sonic voices."""
        from app.services.factory import _resolve_voice_for_nova_sonic

        # Female Cartesia voice -> ruth
        assert (
            _resolve_voice_for_nova_sonic("79a125e8-cd45-4c13-8a67-188112f4dd22")
            == "ruth"
        )
        # Male Cartesia voice -> matthew
        assert (
            _resolve_voice_for_nova_sonic("a0e99841-438c-4a64-b679-ae501e7d6091")
            == "matthew"
        )

    def test_deepgram_aura_maps_to_nova_sonic(self):
        """Deepgram Aura voice names map to Nova Sonic voices."""
        from app.services.factory import _resolve_voice_for_nova_sonic

        assert _resolve_voice_for_nova_sonic("aura-2-thalia-en") == "ruth"
        assert _resolve_voice_for_nova_sonic("aura-2-arcas-en") == "matthew"

    def test_unknown_voice_returns_default(self):
        """Unknown voice IDs return default."""
        from app.services.factory import _resolve_voice_for_nova_sonic

        assert _resolve_voice_for_nova_sonic("unknown-voice-id") == "matthew"


class TestCreateVoicePipelineDispatch:
    """Tests for create_voice_pipeline mode dispatching."""

    @pytest.mark.asyncio
    @patch("app.pipeline_ecs._create_cascaded_pipeline")
    async def test_cascaded_mode_dispatches_correctly(self, mock_cascaded):
        """Cascaded mode calls _create_cascaded_pipeline."""
        from app.pipeline_ecs import PipelineConfig, create_voice_pipeline

        mock_cascaded.return_value = (MagicMock(), MagicMock())
        config = PipelineConfig(
            room_url="https://test.daily.co/room",
            room_token="token",
            session_id="sess-1",
            system_prompt="Test",
            voice_id="matthew",
            aws_region="us-east-1",
            pipeline_mode="cascaded",
        )

        await create_voice_pipeline(config)
        mock_cascaded.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.pipeline_ecs._create_s2s_pipeline")
    async def test_s2s_mode_dispatches_correctly(self, mock_s2s):
        """Speech-to-speech mode calls _create_s2s_pipeline."""
        from app.pipeline_ecs import PipelineConfig, create_voice_pipeline

        mock_s2s.return_value = (MagicMock(), MagicMock())
        config = PipelineConfig(
            room_url="https://test.daily.co/room",
            room_token="token",
            session_id="sess-1",
            system_prompt="Test",
            voice_id="matthew",
            aws_region="us-east-1",
            pipeline_mode="speech-to-speech",
        )

        await create_voice_pipeline(config)
        mock_s2s.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_mode_raises_error(self):
        """Unknown pipeline mode raises ValueError."""
        from app.pipeline_ecs import PipelineConfig, create_voice_pipeline

        config = PipelineConfig(
            room_url="https://test.daily.co/room",
            room_token="token",
            session_id="sess-1",
            system_prompt="Test",
            voice_id="matthew",
            aws_region="us-east-1",
            pipeline_mode="invalid-mode",
        )

        with pytest.raises(ValueError, match="Unknown pipeline_mode"):
            await create_voice_pipeline(config)
