"""
Tests for observability metrics module: TurnMetrics, CallMetrics, EMFLogger, MetricsCollector.

Run with: pytest tests/test_observability_metrics.py -v
"""

import asyncio
import json
import pytest

try:
    from pipecat.frames.frames import (
        InputAudioRawFrame,
        LLMFullResponseEndFrame,
        LLMFullResponseStartFrame,
        TextFrame,
        TranscriptionFrame,
        BotStartedSpeakingFrame,
        BotStoppedSpeakingFrame,
        TTSSpeakFrame,
        TTSStartedFrame,
        TTSStoppedFrame,
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
    )
    from pipecat.observers.base_observer import FramePushed
    from pipecat.processors.frame_processor import FrameDirection
    from pipecat.services.llm_service import LLMService
except ImportError:
    pytest.skip(
        "pipecat not available (container-only dependency)", allow_module_level=True
    )

from app.observability import (
    MetricsCollector,
    ConversationObserver,
    AudioQualityObserver,
    TurnMetrics,
    CallMetrics,
    EMFLogger,
    TimingContext,
    create_metrics_collector,
)

from unittest.mock import MagicMock, create_autospec


def extract_emf_lines(output: str) -> list:
    """Extract EMF JSON lines from captured output (filters out structlog lines)."""
    lines = []
    for line in output.strip().split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                parsed = json.loads(line)
                if "_aws" in parsed:
                    lines.append(parsed)
            except json.JSONDecodeError:
                pass
    return lines


class TestTurnMetrics:
    """Tests for TurnMetrics data class."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        turn = TurnMetrics(
            turn_number=1,
            stt_latency_ms=145.2,
            llm_ttfb_ms=312.5,
            llm_total_ms=1240.8,
            tts_ttfb_ms=89.3,
            agent_response_latency_ms=1475.3,
        )
        result = turn.to_dict()
        assert result["turn_number"] == 1
        assert result["stt_latency_ms"] == 145.2
        assert result["llm_ttfb_ms"] == 312.5
        assert result["llm_total_ms"] == 1240.8
        assert result["tts_ttfb_ms"] == 89.3
        assert result["agent_response_latency_ms"] == 1475.3

    def test_to_dict_with_none_values(self):
        """Test conversion with None values."""
        turn = TurnMetrics(turn_number=1, stt_latency_ms=100.0)
        result = turn.to_dict()
        assert result["turn_number"] == 1
        assert result["stt_latency_ms"] == 100.0
        assert result["llm_ttfb_ms"] is None
        assert result["agent_response_latency_ms"] is None

    def test_started_at_default(self):
        """Test that started_at is set by default."""
        turn = TurnMetrics(turn_number=1)
        assert turn.started_at > 0


class TestCallMetrics:
    """Tests for CallMetrics data class."""

    def test_avg_stt_ms(self):
        """Test average STT latency calculation."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        metrics._turn_metrics = [
            TurnMetrics(turn_number=1, stt_latency_ms=100.0),
            TurnMetrics(turn_number=2, stt_latency_ms=200.0),
        ]
        assert metrics.avg_stt_ms == 150.0

    def test_avg_stt_ms_empty(self):
        """Test average STT with no turns."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        assert metrics.avg_stt_ms == 0.0

    def test_avg_stt_ms_with_none_values(self):
        """Test average STT ignores None values."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        metrics._turn_metrics = [
            TurnMetrics(turn_number=1, stt_latency_ms=100.0),
            TurnMetrics(turn_number=2, stt_latency_ms=None),
            TurnMetrics(turn_number=3, stt_latency_ms=200.0),
        ]
        assert metrics.avg_stt_ms == 150.0

    def test_avg_llm_ms(self):
        """Test average LLM total time calculation."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        metrics._turn_metrics = [
            TurnMetrics(turn_number=1, llm_total_ms=1000.0),
            TurnMetrics(turn_number=2, llm_total_ms=2000.0),
        ]
        assert metrics.avg_llm_ms == 1500.0

    def test_avg_agent_response_ms(self):
        """Test average E2E latency calculation."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        metrics._turn_metrics = [
            TurnMetrics(turn_number=1, agent_response_latency_ms=400.0),
            TurnMetrics(turn_number=2, agent_response_latency_ms=600.0),
        ]
        assert metrics.avg_agent_response_ms == 500.0

    def test_duration_seconds(self):
        """Test duration calculation."""
        import time

        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        time.sleep(0.01)  # 10ms
        assert metrics.duration_seconds >= 0.01

    def test_to_dict(self):
        """Test conversion to dictionary."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        metrics.turn_count = 3
        metrics.completion_status = "completed"

        result = metrics.to_dict()
        assert result["call_id"] == "test-123"
        assert result["session_id"] == "session-456"
        assert result["turn_count"] == 3
        assert result["completion_status"] == "completed"

    def test_interruption_count_default(self):
        """Test interruption_count defaults to 0."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        assert metrics.interruption_count == 0

    def test_interruption_count_in_to_dict(self):
        """Test interruption_count is included in to_dict."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        metrics.interruption_count = 5

        result = metrics.to_dict()
        assert result["interruption_count"] == 5


class TestEMFLogger:
    """Tests for EMF log formatting."""

    def test_turn_metrics_format(self, capsys):
        """Test EMF format for turn metrics."""
        emf = EMFLogger(namespace="Test/Metrics", environment="test")
        turn = TurnMetrics(
            turn_number=1,
            stt_latency_ms=145.2,
            agent_response_latency_ms=1475.3,
        )

        emf.emit_turn_metrics("call-123", turn)

        captured = capsys.readouterr()
        log = json.loads(captured.out.strip())

        # Verify EMF structure
        assert "_aws" in log
        assert "CloudWatchMetrics" in log["_aws"]
        assert log["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "Test/Metrics"

        # Verify dimensions
        assert log["Environment"] == "test"
        assert log["CallId"] == "call-123"
        assert log["TurnNumber"] == 1

        # Verify metrics present
        assert log["STTLatency"] == 145.2
        assert log["AgentResponseLatency"] == 1475.3
        assert log["event"] == "turn_metrics"

        # Verify metrics not set are not included
        assert "LLMTimeToFirstByte" not in log

    def test_turn_metrics_with_all_values(self, capsys):
        """Test EMF format with all metrics populated."""
        emf = EMFLogger(namespace="Test/Metrics", environment="test")
        turn = TurnMetrics(
            turn_number=2,
            stt_latency_ms=145.2,
            llm_ttfb_ms=312.5,
            llm_total_ms=1240.8,
            tts_ttfb_ms=89.3,
            agent_response_latency_ms=1475.3,
        )

        emf.emit_turn_metrics("call-123", turn)

        captured = capsys.readouterr()
        log = json.loads(captured.out.strip())

        # Verify all metrics
        assert log["STTLatency"] == 145.2
        assert log["LLMTimeToFirstByte"] == 312.5
        assert log["LLMTotalResponseTime"] == 1240.8
        assert log["TTSTimeToFirstByte"] == 89.3
        assert log["AgentResponseLatency"] == 1475.3

    def test_turn_metrics_empty_no_output(self, capsys):
        """Test that turn with no metrics produces no output."""
        emf = EMFLogger(environment="test")
        turn = TurnMetrics(turn_number=1)

        emf.emit_turn_metrics("call-123", turn)

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_call_summary_format(self, capsys):
        """Test EMF format for call summary."""
        emf = EMFLogger(environment="test")
        metrics = CallMetrics(
            call_id="call-123",
            session_id="session-456",
            environment="test",
        )
        metrics.turn_count = 3
        metrics.completion_status = "completed"

        emf.emit_call_summary(metrics)

        captured = capsys.readouterr()
        log = json.loads(captured.out.strip())

        # Verify structure
        assert "_aws" in log
        assert log["TurnCount"] == 3
        assert log["CompletionStatus"] == "completed"
        assert log["event"] == "call_summary"
        assert log["SessionId"] == "session-456"

    def test_call_summary_includes_interruption_count(self, capsys):
        """Test EMF call summary includes InterruptionCount metric."""
        emf = EMFLogger(environment="test")
        metrics = CallMetrics(
            call_id="call-123",
            session_id="session-456",
            environment="test",
        )
        metrics.turn_count = 5
        metrics.interruption_count = 2

        emf.emit_call_summary(metrics)

        captured = capsys.readouterr()
        log = json.loads(captured.out.strip())

        # Verify InterruptionCount is in the EMF log
        assert log["InterruptionCount"] == 2

        # Verify InterruptionCount is in the metrics definition
        metric_names = [
            m["Name"] for m in log["_aws"]["CloudWatchMetrics"][0]["Metrics"]
        ]
        assert "InterruptionCount" in metric_names

    def test_emf_timestamp(self, capsys):
        """Test that EMF timestamp is in milliseconds."""
        import time

        emf = EMFLogger(environment="test")
        turn = TurnMetrics(turn_number=1, stt_latency_ms=100.0)

        before = int(time.time() * 1000)
        emf.emit_turn_metrics("call-123", turn)
        after = int(time.time() * 1000)

        captured = capsys.readouterr()
        log = json.loads(captured.out.strip())

        timestamp = log["_aws"]["Timestamp"]
        assert before <= timestamp <= after

    def test_emf_dimensions_structure(self, capsys):
        """Test EMF dimensions are properly structured."""
        emf = EMFLogger(environment="prod")
        turn = TurnMetrics(turn_number=1, stt_latency_ms=100.0)

        emf.emit_turn_metrics("call-abc", turn)

        captured = capsys.readouterr()
        log = json.loads(captured.out.strip())

        dimensions = log["_aws"]["CloudWatchMetrics"][0]["Dimensions"]
        assert ["Environment"] in dimensions
        assert ["Environment", "CallId"] in dimensions

    def test_session_health_format(self, capsys):
        """Test EMF format for session health metrics."""
        emf = EMFLogger(environment="test")

        emf.emit_session_health(active_sessions=3)

        captured = capsys.readouterr()
        log = json.loads(captured.out.strip())

        # Verify EMF structure
        assert "_aws" in log
        assert log["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "VoiceAgent/Pipeline"
        assert log["Environment"] == "test"
        assert log["ActiveSessions"] == 3
        assert log["event"] == "session_health"

        # Verify metric definition
        metric_names = [
            m["Name"] for m in log["_aws"]["CloudWatchMetrics"][0]["Metrics"]
        ]
        assert "ActiveSessions" in metric_names

    def test_session_health_with_error(self, capsys):
        """Test session health includes error count and category."""
        emf = EMFLogger(environment="test")

        emf.emit_session_health(
            active_sessions=2, error_count=1, error_category="llm_error"
        )

        captured = capsys.readouterr()
        log = json.loads(captured.out.strip())

        # Verify error fields
        assert log["ActiveSessions"] == 2
        assert log["ErrorCount"] == 1
        assert log["ErrorCategory"] == "llm_error"

        # Verify error metric and dimension
        metric_names = [
            m["Name"] for m in log["_aws"]["CloudWatchMetrics"][0]["Metrics"]
        ]
        assert "ErrorCount" in metric_names

        dimensions = log["_aws"]["CloudWatchMetrics"][0]["Dimensions"]
        assert ["Environment"] in dimensions
        assert ["Environment", "ErrorCategory"] in dimensions

    def test_session_health_no_error_no_error_fields(self, capsys):
        """Test session health without errors doesn't include error fields."""
        emf = EMFLogger(environment="test")

        emf.emit_session_health(active_sessions=5)

        captured = capsys.readouterr()
        log = json.loads(captured.out.strip())

        # No error fields
        assert "ErrorCount" not in log
        assert "ErrorCategory" not in log

        # Only Environment dimension (no ErrorCategory)
        dimensions = log["_aws"]["CloudWatchMetrics"][0]["Dimensions"]
        assert ["Environment"] in dimensions
        assert len(dimensions) == 1


class TestTimingContext:
    """Tests for TimingContext async context manager."""

    @pytest.mark.asyncio
    async def test_timing_records_elapsed(self):
        """Test that timing context records elapsed time."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        timer = TimingContext(collector, "stt", record_total=True)
        async with timer:
            await asyncio.sleep(0.01)  # 10ms

        assert timer.elapsed_ms >= 10.0
        assert collector.current_turn.stt_latency_ms >= 10.0

    @pytest.mark.asyncio
    async def test_timing_ttfb(self):
        """Test time-to-first-byte tracking."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        timer = TimingContext(collector, "llm", record_total=True, record_ttfb=True)
        async with timer:
            await asyncio.sleep(0.005)  # 5ms
            timer.mark_first_byte()
            await asyncio.sleep(0.005)  # another 5ms

        assert collector.current_turn.llm_ttfb_ms >= 5.0
        assert collector.current_turn.llm_ttfb_ms < 10.0
        assert collector.current_turn.llm_total_ms >= 10.0

    @pytest.mark.asyncio
    async def test_mark_first_byte_only_once(self):
        """Test that mark_first_byte only records on first call."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        timer = TimingContext(collector, "llm", record_total=True, record_ttfb=True)
        async with timer:
            await asyncio.sleep(0.005)
            timer.mark_first_byte()
            first_ttfb = collector.current_turn.llm_ttfb_ms
            await asyncio.sleep(0.005)
            timer.mark_first_byte()  # Second call should be ignored

        assert collector.current_turn.llm_ttfb_ms == first_ttfb


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    def test_initialization(self):
        """Test collector initialization."""
        collector = MetricsCollector("call-1", "session-1", "test")
        assert collector.call_id == "call-1"
        assert collector.session_id == "session-1"
        assert collector.environment == "test"
        assert collector.turn_count == 0

    def test_environment_from_env_var(self, monkeypatch):
        """Test environment defaults from ENVIRONMENT env var."""
        monkeypatch.setenv("ENVIRONMENT", "staging")
        collector = MetricsCollector("call-1", "session-1")
        assert collector.environment == "staging"

    def test_turn_lifecycle(self):
        """Test basic turn lifecycle."""
        collector = MetricsCollector("call-1", "session-1", "test")

        collector.start_turn()
        assert collector.turn_count == 1
        assert collector.current_turn is not None
        assert collector.current_turn.turn_number == 1

        collector.record_stt_latency(150.0)
        assert collector.current_turn.stt_latency_ms == 150.0

        collector.end_turn(user_text="hello", assistant_text="hi")
        assert collector.current_turn is None
        assert len(collector.call_metrics._turn_metrics) == 1
        assert collector.call_metrics._turn_metrics[0].user_text == "hello"

    def test_multiple_turns(self, capsys):
        """Test multiple turn cycles."""
        collector = MetricsCollector("call-1", "session-1", "test")

        for i in range(3):
            collector.start_turn()
            collector.record_stt_latency(100.0 + i * 10)
            collector.end_turn()

        assert collector.turn_count == 3
        assert collector.call_metrics.avg_stt_ms == 110.0

        # Verify EMF logs emitted (filter out structlog lines)
        captured = capsys.readouterr()
        emf_logs = extract_emf_lines(captured.out)
        assert len(emf_logs) == 3  # One per turn
        assert all(log["event"] == "turn_metrics" for log in emf_logs)

    def test_record_without_turn_is_noop(self):
        """Test that recording without active turn does nothing."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.record_stt_latency(100.0)  # No turn started
        assert collector.call_metrics.total_stt_ms == 0.0

    def test_end_turn_without_start_warns(self):
        """Test that end_turn without start logs warning."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.end_turn()  # Should not raise, just warn
        assert collector.turn_count == 0

    @pytest.mark.asyncio
    async def test_time_stt_context_manager(self):
        """Test time_stt context manager."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        async with collector.time_stt():
            await asyncio.sleep(0.01)

        assert collector.current_turn.stt_latency_ms >= 10.0

    @pytest.mark.asyncio
    async def test_time_llm_context_manager(self):
        """Test time_llm context manager with TTFB."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        async with collector.time_llm() as timer:
            await asyncio.sleep(0.005)
            timer.mark_first_byte()
            await asyncio.sleep(0.005)

        assert collector.current_turn.llm_ttfb_ms >= 5.0
        assert collector.current_turn.llm_total_ms >= 10.0

    def test_mark_vad_stop_and_first_audio(self):
        """Test E2E latency via VAD/audio markers."""
        import time

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        collector.mark_vad_stop()
        time.sleep(0.01)  # 10ms
        collector.mark_first_audio()

        assert collector.current_turn.agent_response_latency_ms >= 10.0

    def test_finalize(self, capsys):
        """Test call finalization."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        collector.record_stt_latency(100.0)
        collector.end_turn()

        result = collector.finalize(status="completed")

        assert result.completion_status == "completed"
        assert result.turn_count == 1

        # Verify EMF call summary was emitted
        captured = capsys.readouterr()
        assert "call_summary" in captured.out

    def test_finalize_with_incomplete_turn(self, capsys):
        """Test finalize auto-ends incomplete turn."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        collector.record_stt_latency(100.0)
        # Don't call end_turn()

        result = collector.finalize(status="completed")

        # Should auto-end the turn
        assert result.turn_count == 1
        assert len(result._turn_metrics) == 1
        assert result._turn_metrics[0].stt_latency_ms == 100.0

    def test_finalize_with_error(self, capsys):
        """Test finalization with error status."""
        collector = MetricsCollector("call-1", "session-1", "test")

        result = collector.finalize(status="error", error_category="llm_error")

        assert result.completion_status == "error"
        assert result.error_category == "llm_error"

        captured = capsys.readouterr()
        emf_logs = extract_emf_lines(captured.out)
        assert len(emf_logs) == 1
        log = emf_logs[0]
        assert log["CompletionStatus"] == "error"
        assert log["ErrorCategory"] == "llm_error"

    def test_manual_metric_recording(self):
        """Test all manual metric recording methods."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        collector.record_stt_latency(100.0)
        collector.record_llm_ttfb(200.0)
        collector.record_llm_total(500.0)
        collector.record_tts_ttfb(80.0)
        collector.record_agent_response_latency(600.0)

        turn = collector.current_turn
        assert turn.stt_latency_ms == 100.0
        assert turn.llm_ttfb_ms == 200.0
        assert turn.llm_total_ms == 500.0
        assert turn.tts_ttfb_ms == 80.0
        assert turn.agent_response_latency_ms == 600.0

    def test_record_interruption(self):
        """Test interruption recording increments counter."""
        collector = MetricsCollector("call-1", "session-1", "test")

        assert collector.call_metrics.interruption_count == 0

        collector.record_interruption()
        assert collector.call_metrics.interruption_count == 1

        collector.record_interruption()
        collector.record_interruption()
        assert collector.call_metrics.interruption_count == 3

    def test_interruption_count_in_finalize(self, capsys):
        """Test interruption count is included in finalized call summary."""
        collector = MetricsCollector("call-1", "session-1", "test")

        # Record some interruptions
        collector.record_interruption()
        collector.record_interruption()

        result = collector.finalize(status="completed")

        assert result.interruption_count == 2

        # Verify EMF log includes interruption count
        captured = capsys.readouterr()
        emf_logs = extract_emf_lines(captured.out)
        assert len(emf_logs) == 1
        assert emf_logs[0]["InterruptionCount"] == 2


class TestCreateMetricsCollector:
    """Tests for factory function."""

    def test_creates_collector(self):
        """Test factory creates collector with correct values."""
        collector = create_metrics_collector("call-1", "session-1")
        assert collector.call_id == "call-1"
        assert collector.session_id == "session-1"

    def test_uses_environment_variable(self, monkeypatch):
        """Test factory uses ENVIRONMENT env var."""
        monkeypatch.setenv("ENVIRONMENT", "staging")
        collector = create_metrics_collector("call-1", "session-1")
        assert collector.environment == "staging"

    def test_explicit_environment_overrides(self, monkeypatch):
        """Test explicit environment overrides env var."""
        monkeypatch.setenv("ENVIRONMENT", "staging")
        collector = create_metrics_collector("call-1", "session-1", "custom")
        assert collector.environment == "custom"

    def test_passes_poor_audio_threshold(self):
        """Test factory passes poor_audio_threshold_db to MetricsCollector."""
        collector = create_metrics_collector(
            "call-1", "session-1", poor_audio_threshold_db=-55.0
        )
        assert collector._poor_audio_threshold_db == -55.0

    def test_default_poor_audio_threshold(self):
        """Test factory defaults poor_audio_threshold_db to -70.0."""
        collector = create_metrics_collector("call-1", "session-1")
        assert collector._poor_audio_threshold_db == -70.0


class TestConversationObserver:
    """Tests for ConversationObserver."""

    def _make_frame_pushed(self, frame, from_llm: bool = False) -> FramePushed:
        """Helper to create a FramePushed event with a mock source.

        Args:
            frame: The frame to wrap
            from_llm: If True, source will be an LLMService mock (needed for TextFrame,
                      LLMFullResponseStartFrame, LLMFullResponseEndFrame filtering)
        """
        if from_llm:
            # Create a mock that passes isinstance(source, LLMService) checks
            mock_source = create_autospec(LLMService, instance=True)
            mock_source.name = "test_llm_service"
        else:
            mock_source = MagicMock()
            mock_source.name = "test_processor"
        mock_destination = MagicMock()
        mock_destination.name = "test_destination"
        return FramePushed(
            source=mock_source,
            frame=frame,
            direction=FrameDirection.DOWNSTREAM,
            timestamp=0,
            destination=mock_destination,
        )

    @pytest.mark.asyncio
    async def test_logs_user_transcription(self, capsys):
        """Test that user transcription is logged."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        frame = TranscriptionFrame(
            text="Hello, how are you?", user_id="user-1", timestamp="2024-01-01"
        )
        await observer.on_push_frame(self._make_frame_pushed(frame))

        # Check that conversation_turn was logged (structlog outputs to stdout)
        # Format may be key=value or JSON depending on environment
        captured = capsys.readouterr()
        assert "conversation_turn" in captured.out
        assert "speaker=user" in captured.out or '"speaker": "user"' in captured.out
        assert "Hello, how are you?" in captured.out

    @pytest.mark.asyncio
    async def test_logs_bot_response_on_llm_end(self, capsys):
        """Test that bot response is logged when LLM response ends."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        # Simulate LLM streaming text frames (bounded by LLM response frames)
        # Note: from_llm=True required for LLM frames to be processed
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseStartFrame(), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="Hello, "), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="I'm "), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="here to help."), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseEndFrame(), from_llm=True)
        )

        # Check that conversation_turn was logged with accumulated text
        # Format may be key=value or JSON depending on environment
        captured = capsys.readouterr()
        assert "conversation_turn" in captured.out
        assert (
            "speaker=assistant" in captured.out
            or '"speaker": "assistant"' in captured.out
        )
        assert "Hello, I'm here to help." in captured.out

    @pytest.mark.asyncio
    async def test_accumulates_text_frames(self):
        """Test that text frames are accumulated before logging."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        # Send text frames during LLM response (from_llm=True required)
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseStartFrame(), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="Part 1 "), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="Part 2"), from_llm=True)
        )

        # Text should be accumulated
        assert observer._current_bot_text == ["Part 1 ", "Part 2"]

        # After LLM response ends, should be flushed
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseEndFrame(), from_llm=True)
        )
        assert observer._current_bot_text == []

    @pytest.mark.asyncio
    async def test_detects_barge_in(self, capsys):
        """Test barge-in detection when user speaks during TTS."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        # Start bot speaking (audio playback)
        await observer.on_push_frame(self._make_frame_pushed(BotStartedSpeakingFrame()))
        assert observer._bot_speaking is True

        # User starts speaking (barge-in)
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )

        # Check that barge_in was logged
        captured = capsys.readouterr()
        assert "barge_in" in captured.out

    @pytest.mark.asyncio
    async def test_barge_in_increments_interruption_count(self):
        """Test barge-in increments collector's interruption counter."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        # Verify initial count is 0
        assert collector.call_metrics.interruption_count == 0

        # First barge-in
        await observer.on_push_frame(self._make_frame_pushed(BotStartedSpeakingFrame()))
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )
        assert collector.call_metrics.interruption_count == 1

        # Stop and start bot speaking again for second barge-in
        await observer.on_push_frame(self._make_frame_pushed(BotStoppedSpeakingFrame()))
        await observer.on_push_frame(self._make_frame_pushed(BotStartedSpeakingFrame()))
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )
        assert collector.call_metrics.interruption_count == 2

    @pytest.mark.asyncio
    async def test_no_barge_in_when_tts_inactive(self, capsys):
        """Test no barge-in logged when TTS is not active."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        # User speaks without TTS active (normal turn start)
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )

        # Should not log barge-in
        captured = capsys.readouterr()
        assert "barge_in" not in captured.out

    @pytest.mark.asyncio
    async def test_disabled_observer_does_nothing(self, capsys):
        """Test that disabled observer doesn't log anything."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=False)

        # Clear any previous output
        capsys.readouterr()

        # Send various frames
        await observer.on_push_frame(
            self._make_frame_pushed(
                TranscriptionFrame(
                    text="Test", user_id="user-1", timestamp="2024-01-01"
                )
            )
        )
        await observer.on_push_frame(self._make_frame_pushed(TTSStartedFrame()))
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="Response"))
        )
        await observer.on_push_frame(self._make_frame_pushed(TTSStoppedFrame()))

        # Should not log conversation events
        captured = capsys.readouterr()
        assert "conversation_turn" not in captured.out

    @pytest.mark.asyncio
    async def test_empty_transcription_ignored(self, capsys):
        """Test that empty transcriptions are not logged."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        # Clear any previous output
        capsys.readouterr()

        # Send empty transcription
        await observer.on_push_frame(
            self._make_frame_pushed(
                TranscriptionFrame(text="   ", user_id="user-1", timestamp="2024-01-01")
            )
        )

        # Should not log conversation_turn (observer_created is OK)
        captured = capsys.readouterr()
        assert "conversation_turn" not in captured.out

    @pytest.mark.asyncio
    async def test_empty_bot_response_ignored(self, capsys):
        """Test that empty bot responses are not logged."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        # Clear any previous output
        capsys.readouterr()

        # LLM response with no text (from_llm=True required)
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseStartFrame(), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseEndFrame(), from_llm=True)
        )

        # Should not log assistant turn
        # Format may be key=value or JSON depending on environment
        captured = capsys.readouterr()
        assert (
            "speaker=assistant" not in captured.out
            and '"speaker": "assistant"' not in captured.out
        )

    @pytest.mark.asyncio
    async def test_uses_collector_turn_number(self):
        """Test that observer uses collector's turn number."""
        collector = MetricsCollector("call-1", "session-1", "test")

        # Simulate 3 turns
        for _ in range(3):
            collector.start_turn()
            collector.end_turn()

        collector.start_turn()  # Turn 4
        observer = ConversationObserver(collector, enabled=True)

        # Verify we can access turn count
        assert collector.turn_count == 4

    @pytest.mark.asyncio
    async def test_bot_speaking_state_tracking(self):
        """Test bot speaking state is properly tracked for barge-in detection."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        assert observer._bot_speaking is False

        await observer.on_push_frame(self._make_frame_pushed(BotStartedSpeakingFrame()))
        assert observer._bot_speaking is True

        await observer.on_push_frame(self._make_frame_pushed(BotStoppedSpeakingFrame()))
        assert observer._bot_speaking is False

    @pytest.mark.asyncio
    async def test_barge_in_flushes_partial_response(self, caplog):
        """Test that barge-in clears any accumulated partial response."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        # Start LLM response and accumulate some text (from_llm=True required)
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseStartFrame(), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(
                TextFrame(text="Hello, I'm going to"), from_llm=True
            )
        )
        # Bot starts speaking (audio playback)
        await observer.on_push_frame(self._make_frame_pushed(BotStartedSpeakingFrame()))

        # Verify text is accumulated
        assert len(observer._current_bot_text) == 1

        # Barge-in while bot is speaking
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )

        # Barge-in should be detected (bot was speaking)
        # Note: We don't clear text on barge-in anymore since we use LLM boundaries
        # The text will be cleared when LLM response ends or new one starts
        assert observer._bot_speaking is True

    @pytest.mark.asyncio
    async def test_bot_response_spacing_normalized(self, capsys):
        """Test that bot response text has proper spacing between tokens."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        # Simulate LLM streaming tokens without spaces (from_llm=True required)
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseStartFrame(), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="Hello"), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text=","), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="how"), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="can"), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="I"), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="help"), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="you"), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="?"), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseEndFrame(), from_llm=True)
        )

        # Check that logged output has proper spacing
        captured = capsys.readouterr()
        # Should be "Hello, how can I help you?" not "Hello,howcanIhelpyou?"
        assert "Hello, how can I help you?" in captured.out

    @pytest.mark.asyncio
    async def test_ignores_text_frames_outside_llm_response(self):
        """Test that TextFrames outside LLM response boundaries are ignored."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        # Send text frames without LLM response start (even from_llm=True shouldn't matter)
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="Stray text"), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="More stray text"), from_llm=True)
        )

        # Text should NOT be accumulated (no LLM response started)
        assert observer._current_bot_text == []

        # Now start a proper LLM response (from_llm=True required)
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseStartFrame(), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="Real response"), from_llm=True)
        )

        # This text SHOULD be accumulated
        assert observer._current_bot_text == ["Real response"]

    @pytest.mark.asyncio
    async def test_ignores_text_frames_from_non_llm_sources(self):
        """Test that TextFrames from non-LLM sources (e.g., TTS) are filtered out."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        # Start a proper LLM response
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseStartFrame(), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="Hello "), from_llm=True)
        )

        # These should be accumulated (from LLM)
        assert observer._current_bot_text == ["Hello "]

        # Now send TextFrames from non-LLM source (like TTS echoing)
        # These should be IGNORED even though we're in an LLM response
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="Duplicate"), from_llm=False)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="Echo"), from_llm=False)
        )

        # Should still only have the LLM text
        assert observer._current_bot_text == ["Hello "]

        # Continue with more LLM text
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="world!"), from_llm=True)
        )

        # Should have both LLM texts, not the non-LLM ones
        assert observer._current_bot_text == ["Hello ", "world!"]

    # ---- TTSSpeakFrame (transition/filler/spoken_response TTS) ----

    @pytest.mark.asyncio
    async def test_logs_tts_speak_frame_as_system(self, capsys):
        """Test that TTSSpeakFrame from non-LLM source logs as speaker=system."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        frame = TTSSpeakFrame(text="One moment please.")
        await observer.on_push_frame(self._make_frame_pushed(frame, from_llm=False))

        captured = capsys.readouterr()
        assert "conversation_turn" in captured.out
        assert "speaker=system" in captured.out or '"speaker": "system"' in captured.out
        assert "One moment please." in captured.out

    @pytest.mark.asyncio
    async def test_tts_speak_frame_from_llm_not_logged(self, capsys):
        """Test that TTSSpeakFrame from LLMService is skipped (avoids double-logging)."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        frame = TTSSpeakFrame(text="LLM-generated speech")
        await observer.on_push_frame(self._make_frame_pushed(frame, from_llm=True))

        captured = capsys.readouterr()
        assert "conversation_turn" not in captured.out

    @pytest.mark.asyncio
    async def test_tts_speak_frame_dedup(self, capsys):
        """Test that duplicate TTSSpeakFrame is logged only once."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        frame = TTSSpeakFrame(text="One moment please.")
        await observer.on_push_frame(self._make_frame_pushed(frame, from_llm=False))
        # Push same frame again (simulates multi-hop in pipeline)
        await observer.on_push_frame(self._make_frame_pushed(frame, from_llm=False))

        captured = capsys.readouterr()
        # Should appear exactly once
        assert captured.out.count("One moment please.") == 1

    @pytest.mark.asyncio
    async def test_tts_speak_frame_empty_text_skipped(self, capsys):
        """Test that TTSSpeakFrame with empty/whitespace text is not logged."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        for text in ["", "   ", None]:
            frame = TTSSpeakFrame(text=text)
            await observer.on_push_frame(self._make_frame_pushed(frame, from_llm=False))

        captured = capsys.readouterr()
        assert "conversation_turn" not in captured.out

    @pytest.mark.asyncio
    async def test_tts_speak_frame_does_not_affect_assistant_logging(self, capsys):
        """Test that LLM-generated speech still logs as assistant after TTSSpeakFrame."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        # System TTS first (transition phrase)
        system_frame = TTSSpeakFrame(text="One moment please.")
        await observer.on_push_frame(
            self._make_frame_pushed(system_frame, from_llm=False)
        )

        # Then LLM response
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseStartFrame(), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(TextFrame(text="How can I help?"), from_llm=True)
        )
        await observer.on_push_frame(
            self._make_frame_pushed(LLMFullResponseEndFrame(), from_llm=True)
        )

        captured = capsys.readouterr()
        # Both should be present
        assert "One moment please." in captured.out
        assert "How can I help?" in captured.out
        # System and assistant speakers both present
        assert "speaker=system" in captured.out or '"speaker": "system"' in captured.out
        assert (
            "speaker=assistant" in captured.out
            or '"speaker": "assistant"' in captured.out
        )

    @pytest.mark.asyncio
    async def test_conversation_turn_includes_agent_node(self, capsys):
        """conversation_turn log should include agent_node when set on collector."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        collector.set_agent_node("kb_agent")
        observer = ConversationObserver(collector, enabled=True)

        frame = TranscriptionFrame(
            text="What is the return policy?", user_id="user-1", timestamp="2024-01-01"
        )
        await observer.on_push_frame(self._make_frame_pushed(frame))

        captured = capsys.readouterr()
        assert "conversation_turn" in captured.out
        assert (
            "agent_node=kb_agent" in captured.out
            or '"agent_node": "kb_agent"' in captured.out
        )

    @pytest.mark.asyncio
    async def test_conversation_turn_omits_agent_node_when_none(self, capsys):
        """conversation_turn log should omit agent_node in single-agent mode."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationObserver(collector, enabled=True)

        frame = TranscriptionFrame(
            text="Hello!", user_id="user-1", timestamp="2024-01-01"
        )
        await observer.on_push_frame(self._make_frame_pushed(frame))

        captured = capsys.readouterr()
        assert "conversation_turn" in captured.out
        assert "agent_node" not in captured.out


# =============================================================================
# AudioQualityObserver Tests
# =============================================================================


class TestAudioQualityObserver:
    """Tests for AudioQualityObserver class."""

    def _make_frame_pushed(self, frame, source=None):
        """Helper to create FramePushed objects."""
        mock_source = source or MagicMock()
        mock_destination = MagicMock()
        mock_destination.name = "test_destination"
        return FramePushed(
            source=mock_source,
            frame=frame,
            direction=FrameDirection.DOWNSTREAM,
            timestamp=0,
            destination=mock_destination,
        )

    def _make_audio_frame(self, samples: list):
        """Helper to create InputAudioRawFrame with PCM audio data."""
        import struct
        from pipecat.frames.frames import InputAudioRawFrame

        audio_bytes = struct.pack(f"<{len(samples)}h", *samples)
        return InputAudioRawFrame(audio=audio_bytes, sample_rate=8000, num_channels=1)

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test observer initialization."""
        from app.observability import AudioQualityObserver

        collector = MetricsCollector("call-1", "session-1", "test")
        observer = AudioQualityObserver(collector, enabled=True)

        assert observer._enabled is True
        assert observer._collector is collector
        assert observer._rms_samples == []
        assert observer._peak_samples == []

    @pytest.mark.asyncio
    async def test_disabled_observer_does_nothing(self):
        """Test that disabled observer doesn't process frames."""
        from app.observability import AudioQualityObserver

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=False)

        # Send audio frame - should be ignored
        frame = self._make_audio_frame([1000, 2000, 3000])
        await observer.on_push_frame(self._make_frame_pushed(frame))

        # No samples should be accumulated
        assert observer._rms_samples == []

    @pytest.mark.asyncio
    async def test_processes_audio_frame(self):
        """Test audio frame processing accumulates RMS and peak samples."""
        from app.observability import AudioQualityObserver

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        # Send audio frame with known values
        frame = self._make_audio_frame([1000, 2000, 3000, -1000, -2000])
        await observer.on_push_frame(self._make_frame_pushed(frame))

        # Should have accumulated samples
        assert len(observer._rms_samples) == 1
        assert len(observer._peak_samples) == 1

    @pytest.mark.asyncio
    async def test_rms_calculation(self):
        """Test RMS level calculation."""
        from app.observability import AudioQualityObserver

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        # Send audio with known amplitude (half max = ~-6dB)
        half_max = 16383  # Half of 32767
        frame = self._make_audio_frame([half_max] * 100)
        await observer.on_push_frame(self._make_frame_pushed(frame))

        # Check RMS is approximately -6dB (allowing some tolerance)
        assert len(observer._rms_samples) == 1
        rms_db = observer._rms_samples[0]
        assert -7.0 < rms_db < -5.0

    @pytest.mark.asyncio
    async def test_silence_detection(self):
        """Test silence detection with very low amplitude."""
        from app.observability import AudioQualityObserver

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        # Send near-silent audio
        frame = self._make_audio_frame([1, 2, -1, -2, 0])
        await observer.on_push_frame(self._make_frame_pushed(frame))

        # RMS should be very low (below silence threshold)
        assert len(observer._rms_samples) == 1
        rms_db = observer._rms_samples[0]
        assert rms_db < AudioQualityObserver.SILENCE_THRESHOLD_DB

    @pytest.mark.asyncio
    async def test_speech_start_resets_accumulators(self):
        """Test that UserStartedSpeakingFrame resets sample accumulators."""
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import UserStartedSpeakingFrame

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        # Accumulate some samples
        frame = self._make_audio_frame([1000, 2000, 3000])
        await observer.on_push_frame(self._make_frame_pushed(frame))
        assert len(observer._rms_samples) == 1

        # User starts speaking - should reset
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )
        assert observer._rms_samples == []
        assert observer._peak_samples == []

    @pytest.mark.asyncio
    async def test_speech_stop_records_metrics(self):
        """Test that UserStoppedSpeakingFrame records metrics to collector."""
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import (
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        # Simulate speech: start, audio, stop
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )

        # Send some audio frames
        frame = self._make_audio_frame([10000, 15000, 20000])
        await observer.on_push_frame(self._make_frame_pushed(frame))
        await observer.on_push_frame(self._make_frame_pushed(frame))

        # Stop speaking - should record metrics
        await observer.on_push_frame(
            self._make_frame_pushed(UserStoppedSpeakingFrame())
        )

        # Check that metrics were recorded in current turn
        turn = collector.current_turn
        assert turn is not None
        assert turn.audio_rms_db is not None
        assert turn.audio_peak_db is not None

    @pytest.mark.asyncio
    async def test_silence_duration_recorded(self):
        """Test that silence duration is recorded between speech segments."""
        import asyncio
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import (
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        # First speech segment
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )
        await observer.on_push_frame(
            self._make_frame_pushed(UserStoppedSpeakingFrame())
        )

        # Small delay to simulate silence
        await asyncio.sleep(0.05)  # 50ms

        # Second speech segment - should record silence duration
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )

        # Check that silence was recorded
        turn = collector.current_turn
        assert turn is not None
        assert turn.silence_duration_ms is not None
        assert turn.silence_duration_ms >= 40  # At least 40ms (allowing some tolerance)

    @pytest.mark.asyncio
    async def test_poor_audio_turn_recorded(self):
        """Test that poor audio quality is tracked via dual-signal detection in end_turn().

        Dual-signal detection flags a turn as poor audio when BOTH:
        1. RMS is below threshold (-70 dBFS default), AND
        2. STT confidence is low or absent (None or < 0.9)
        """
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import (
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        # Simulate speech with very low audio
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )

        # Send very quiet audio (below poor audio threshold of -70 dBFS)
        # These samples (~-76 dBFS) should trigger poor audio detection
        frame = self._make_audio_frame([3, 5, 7, -3, -5])
        await observer.on_push_frame(self._make_frame_pushed(frame))
        await observer.on_push_frame(self._make_frame_pushed(frame))

        await observer.on_push_frame(
            self._make_frame_pushed(UserStoppedSpeakingFrame())
        )

        # Poor audio detection happens in end_turn() (dual-signal).
        # No STT confidence recorded => stt_confidence_avg is None => not "stt_ok" => flagged.
        collector.end_turn()
        assert collector.call_metrics.poor_audio_turns == 1

    @pytest.mark.asyncio
    async def test_poor_audio_counted_once_per_turn(self):
        """Test that poor audio is only counted once per conversation turn, not per VAD event.

        Multiple VAD start/stop events can fire within a single conversation turn.
        Poor audio detection happens in end_turn(), so it counts exactly once per turn.
        """
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import (
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        # Very quiet audio that will trigger poor audio detection (~-76 dBFS)
        quiet_frame = self._make_audio_frame([3, 5, 7, -3, -5])

        # Simulate multiple VAD events within the same conversation turn
        # (VAD can fire start/stop multiple times during a single user utterance)
        for _ in range(5):
            await observer.on_push_frame(
                self._make_frame_pushed(UserStartedSpeakingFrame())
            )
            await observer.on_push_frame(self._make_frame_pushed(quiet_frame))
            await observer.on_push_frame(
                self._make_frame_pushed(UserStoppedSpeakingFrame())
            )

        # Poor audio is evaluated once in end_turn(), not per VAD event
        collector.end_turn()
        assert collector.call_metrics.poor_audio_turns == 1

    @pytest.mark.asyncio
    async def test_poor_audio_counted_per_conversation_turn(self):
        """Test that poor audio is counted once per actual conversation turn."""
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import (
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )

        collector = MetricsCollector("call-1", "session-1", "test")
        observer = AudioQualityObserver(collector, enabled=True)

        # First conversation turn (fresh frames -- real pipelines always
        # create new frame instances per audio chunk / VAD event)
        collector.start_turn()  # Turn 1
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )
        await observer.on_push_frame(
            self._make_frame_pushed(self._make_audio_frame([3, 5, 7, -3, -5]))
        )
        await observer.on_push_frame(
            self._make_frame_pushed(UserStoppedSpeakingFrame())
        )
        collector.end_turn()

        # Second conversation turn (new frame instances)
        collector.start_turn()  # Turn 2
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )
        await observer.on_push_frame(
            self._make_frame_pushed(self._make_audio_frame([3, 5, 7, -3, -5]))
        )
        await observer.on_push_frame(
            self._make_frame_pushed(UserStoppedSpeakingFrame())
        )
        collector.end_turn()

        # Poor audio should be counted for each turn (2 total)
        assert collector.call_metrics.poor_audio_turns == 2

    @pytest.mark.asyncio
    async def test_normal_audio_not_counted_as_poor(self):
        """Test that normal audio levels are not counted as poor."""
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import (
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        # Normal phone audio (~-20 dBFS, which is well above the -70 dBFS threshold)
        # Amplitude of ~3000 gives roughly -20 dB
        normal_frame = self._make_audio_frame([3000, 4000, 5000, -3000, -4000])

        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )
        await observer.on_push_frame(self._make_frame_pushed(normal_frame))
        await observer.on_push_frame(
            self._make_frame_pushed(UserStoppedSpeakingFrame())
        )

        # Should NOT be counted as poor audio
        assert collector.call_metrics.poor_audio_turns == 0

    @pytest.mark.asyncio
    async def test_error_handling_does_not_crash(self):
        """Test that errors in audio processing don't crash the observer."""
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import InputAudioRawFrame

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        # Send malformed audio frame (invalid bytes - odd number of bytes)
        frame = InputAudioRawFrame(audio=b"invalid", sample_rate=8000, num_channels=1)
        # Should not raise - observer handles struct.error gracefully
        await observer.on_push_frame(self._make_frame_pushed(frame))

        # Send empty audio frame
        frame = InputAudioRawFrame(audio=b"", sample_rate=8000, num_channels=1)
        # Should not raise - observer handles empty audio gracefully
        await observer.on_push_frame(self._make_frame_pushed(frame))

        # Send single byte (too short for a sample)
        frame = InputAudioRawFrame(audio=b"\x00", sample_rate=8000, num_channels=1)
        # Should not raise - observer checks length before processing
        await observer.on_push_frame(self._make_frame_pushed(frame))

    @pytest.mark.asyncio
    async def test_peak_detection_near_max(self):
        """Test peak detection for clipping (near max amplitude)."""
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import (
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )

        # Send audio with values near max (potential clipping)
        frame = self._make_audio_frame([32000, 32500, 32700, -32000])
        await observer.on_push_frame(self._make_frame_pushed(frame))

        await observer.on_push_frame(
            self._make_frame_pushed(UserStoppedSpeakingFrame())
        )

        # Peak should be very close to 0 dBFS
        turn = collector.current_turn
        assert turn is not None
        assert turn.audio_peak_db is not None
        assert turn.audio_peak_db > -1.0  # Very close to full scale

    @pytest.mark.asyncio
    async def test_custom_threshold_overrides_default(self):
        """Test that a custom poor audio threshold overrides the default.

        The threshold is used by both the observer (for logging) and
        MetricsCollector.end_turn() (for dual-signal poor audio detection).
        """
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import (
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )

        # Pass the stricter threshold to MetricsCollector for dual-signal detection
        collector = MetricsCollector(
            "call-1", "session-1", "test", poor_audio_threshold_db=-55.0
        )
        collector.start_turn()
        # Use a stricter threshold (-55 dBFS) that flags more audio as poor
        observer = AudioQualityObserver(
            collector, enabled=True, poor_audio_threshold_db=-55.0
        )

        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )

        # Audio at ~-64 dBFS: below -55 threshold, so should be flagged as poor
        frame = self._make_audio_frame([10, 20, 30, -10, -20])
        await observer.on_push_frame(self._make_frame_pushed(frame))

        await observer.on_push_frame(
            self._make_frame_pushed(UserStoppedSpeakingFrame())
        )

        # No STT confidence => dual-signal flags as poor
        collector.end_turn()
        assert collector.call_metrics.poor_audio_turns == 1

    @pytest.mark.asyncio
    async def test_pstn_audio_not_flagged_with_default_threshold(self):
        """Test that normal PSTN audio (-62 to -68 dBFS) is not flagged with default -70 threshold."""
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import (
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        # Default threshold is -70 dBFS
        observer = AudioQualityObserver(collector, enabled=True)

        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )

        # Typical PSTN audio (~-64 dBFS) -- above the -70 threshold
        frame = self._make_audio_frame([10, 20, 30, -10, -20])
        await observer.on_push_frame(self._make_frame_pushed(frame))

        await observer.on_push_frame(
            self._make_frame_pushed(UserStoppedSpeakingFrame())
        )

        # Should NOT be flagged as poor audio
        assert collector.call_metrics.poor_audio_turns == 0

    @pytest.mark.asyncio
    async def test_default_threshold_is_negative_70(self):
        """Test that the default poor audio threshold is -70 dBFS."""
        from app.observability import AudioQualityObserver

        collector = MetricsCollector("call-1", "session-1", "test")
        observer = AudioQualityObserver(collector, enabled=True)

        assert observer._poor_audio_threshold_db == -70.0
        assert observer.DEFAULT_POOR_AUDIO_THRESHOLD_DB == -70.0

    @pytest.mark.asyncio
    async def test_rms_distribution_metrics_recorded(self):
        """Test that min, max, and stddev of per-frame RMS are recorded on the turn."""
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import (
            InputAudioRawFrame,
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )

        # Send two frames with very different amplitudes to create a measurable spread.
        # Frame 1: loud audio (~-20 dBFS) -- amplitude ~3000
        loud_frame = self._make_audio_frame([3000, 4000, 5000, -3000, -4000])
        await observer.on_push_frame(self._make_frame_pushed(loud_frame))

        # Frame 2: quiet audio (~-64 dBFS) -- amplitude ~20
        quiet_frame = self._make_audio_frame([10, 20, 30, -10, -20])
        await observer.on_push_frame(self._make_frame_pushed(quiet_frame))

        await observer.on_push_frame(
            self._make_frame_pushed(UserStoppedSpeakingFrame())
        )

        turn = collector.current_turn
        assert turn is not None

        # avg should be set (existing behavior)
        assert turn.audio_rms_db is not None

        # Distribution stats should be set
        assert turn.audio_rms_min_db is not None
        assert turn.audio_rms_max_db is not None
        assert turn.audio_rms_stddev_db is not None

        # min should be the quiet frame, max should be the loud frame
        assert turn.audio_rms_min_db < turn.audio_rms_db
        assert turn.audio_rms_max_db > turn.audio_rms_db

        # stddev should be > 0 since frames have different levels
        assert turn.audio_rms_stddev_db > 0.0

        # Verify they appear in to_dict() for structured logging
        d = turn.to_dict()
        assert "audio_rms_min_db" in d
        assert "audio_rms_max_db" in d
        assert "audio_rms_stddev_db" in d

    @pytest.mark.asyncio
    async def test_rms_distribution_single_frame(self):
        """Test that stddev is 0 when only one audio frame is captured."""
        from app.observability import AudioQualityObserver
        from pipecat.frames.frames import (
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )

        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )

        # Single frame only
        frame = self._make_audio_frame([3000, 4000, 5000, -3000, -4000])
        await observer.on_push_frame(self._make_frame_pushed(frame))

        await observer.on_push_frame(
            self._make_frame_pushed(UserStoppedSpeakingFrame())
        )

        turn = collector.current_turn
        assert turn is not None
        assert turn.audio_rms_min_db is not None
        assert turn.audio_rms_max_db is not None
        assert turn.audio_rms_stddev_db == 0.0
        # With single frame, min == max == avg
        assert turn.audio_rms_min_db == turn.audio_rms_max_db == turn.audio_rms_db


# =============================================================================
# Dual-Signal Poor Audio Detection Tests
# =============================================================================


class TestDualSignalPoorAudioDetection:
    """Tests for dual-signal poor audio detection in MetricsCollector.end_turn().

    Dual-signal detection flags a turn as poor audio only when BOTH conditions are met:
    1. Audio RMS is below the configured threshold (default -70 dBFS)
    2. STT confidence is absent (None) or below the minimum threshold (default 0.9)

    This prevents false positives where audio is quiet but Deepgram still
    transcribes perfectly (e.g., PSTN audio at -62 to -75 dBFS).
    """

    def test_low_rms_low_stt_confidence_is_poor(self):
        """Low RMS + low STT confidence = poor audio (both signals agree)."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        # Set low RMS (below -70 threshold)
        collector.record_audio_rms(-80.0)
        # Set low STT confidence (below 0.9)
        collector.record_stt_quality(
            confidence_avg=0.5,
            confidence_min=0.3,
            interim_count=2,
            final_count=1,
            word_count=3,
        )

        collector.end_turn()
        assert collector.call_metrics.poor_audio_turns == 1

    def test_low_rms_no_stt_confidence_is_poor(self):
        """Low RMS + absent STT confidence (None) = poor audio (true silence)."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        # Set low RMS (below -70 threshold)
        collector.record_audio_rms(-88.0)
        # No STT confidence recorded (stt_confidence_avg stays None)

        collector.end_turn()
        assert collector.call_metrics.poor_audio_turns == 1

    def test_low_rms_high_stt_confidence_not_poor(self):
        """Low RMS + high STT confidence = NOT poor audio.

        This is the key false-positive scenario: audio is quiet on the wire
        but Deepgram transcribes perfectly. Real call data shows STT confidence
        of 0.997-0.999 even at -88 dBFS on PSTN.
        """
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        # Set low RMS (below -70 threshold)
        collector.record_audio_rms(-75.0)
        # Set high STT confidence (Deepgram transcribed fine)
        collector.record_stt_quality(
            confidence_avg=0.997,
            confidence_min=0.99,
            interim_count=3,
            final_count=1,
            word_count=5,
        )

        collector.end_turn()
        assert collector.call_metrics.poor_audio_turns == 0

    def test_normal_rms_low_stt_confidence_not_poor(self):
        """Normal RMS + low STT confidence = NOT poor audio (RMS is fine)."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        # Set normal RMS (above -70 threshold)
        collector.record_audio_rms(-40.0)
        # Set low STT confidence (rare: loud but garbled?)
        collector.record_stt_quality(
            confidence_avg=0.5,
            confidence_min=0.3,
            interim_count=2,
            final_count=1,
            word_count=3,
        )

        collector.end_turn()
        # RMS above threshold means it's not "poor audio" regardless of STT
        assert collector.call_metrics.poor_audio_turns == 0

    def test_normal_rms_no_stt_not_poor(self):
        """Normal RMS + no STT confidence = NOT poor audio."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        # Set normal RMS (above threshold)
        collector.record_audio_rms(-50.0)
        # No STT confidence

        collector.end_turn()
        assert collector.call_metrics.poor_audio_turns == 0

    def test_no_rms_data_not_poor(self):
        """No audio RMS recorded at all = NOT poor audio (no data to judge)."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        # Don't record any audio metrics

        collector.end_turn()
        assert collector.call_metrics.poor_audio_turns == 0

    def test_silence_minus_96_no_stt_is_poor(self):
        """True silence (-96 dBFS) with no STT = poor audio (dead air)."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        collector.record_audio_rms(-96.0)
        # No STT at all (dead silence, VAD fired but nothing transcribed)

        collector.end_turn()
        assert collector.call_metrics.poor_audio_turns == 1

    def test_stt_confidence_exactly_at_threshold_not_poor(self):
        """STT confidence exactly at 0.9 threshold = considered OK (not poor)."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        collector.record_audio_rms(-75.0)  # Below RMS threshold
        collector.record_stt_quality(
            confidence_avg=0.9,
            confidence_min=0.9,
            interim_count=1,
            final_count=1,
            word_count=2,
        )

        collector.end_turn()
        # stt_confidence_avg >= 0.9, so stt_ok is True => not flagged
        assert collector.call_metrics.poor_audio_turns == 0

    def test_custom_threshold_used_by_collector(self):
        """MetricsCollector uses its own poor_audio_threshold_db, not the observer's."""
        collector = MetricsCollector(
            "call-1", "session-1", "test", poor_audio_threshold_db=-55.0
        )
        collector.start_turn()

        # RMS at -60 dBFS: below -55 threshold
        collector.record_audio_rms(-60.0)
        # No STT confidence => flagged

        collector.end_turn()
        assert collector.call_metrics.poor_audio_turns == 1

    def test_dual_signal_across_multiple_turns(self, capsys):
        """Dual-signal detection counts poor turns correctly across multiple turns."""
        collector = MetricsCollector("call-1", "session-1", "test")

        # Turn 1: Low RMS + no STT => poor
        collector.start_turn()
        collector.record_audio_rms(-80.0)
        collector.end_turn()

        # Turn 2: Low RMS + high STT => NOT poor (false positive avoided)
        collector.start_turn()
        collector.record_audio_rms(-75.0)
        collector.record_stt_quality(
            confidence_avg=0.998,
            confidence_min=0.995,
            interim_count=2,
            final_count=1,
            word_count=4,
        )
        collector.end_turn()

        # Turn 3: Normal RMS => NOT poor
        collector.start_turn()
        collector.record_audio_rms(-40.0)
        collector.end_turn()

        # Turn 4: Low RMS + low STT => poor
        collector.start_turn()
        collector.record_audio_rms(-82.0)
        collector.record_stt_quality(
            confidence_avg=0.4,
            confidence_min=0.2,
            interim_count=1,
            final_count=1,
            word_count=1,
        )
        collector.end_turn()

        # Only turns 1 and 4 should be flagged
        assert collector.call_metrics.poor_audio_turns == 2


# =============================================================================
# Audio Quality Metrics in CallMetrics Tests
# =============================================================================


class TestAudioQualityMetrics:
    """Tests for audio quality metrics in CallMetrics."""

    def test_avg_rms_db_calculation(self):
        """Test average RMS calculation across turns."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        metrics._turn_metrics = [
            TurnMetrics(turn_number=1, audio_rms_db=-20.0),
            TurnMetrics(turn_number=2, audio_rms_db=-30.0),
        ]
        assert metrics.avg_rms_db == -25.0

    def test_avg_rms_db_ignores_none(self):
        """Test average RMS ignores None values."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        metrics._turn_metrics = [
            TurnMetrics(turn_number=1, audio_rms_db=-20.0),
            TurnMetrics(turn_number=2, audio_rms_db=None),
            TurnMetrics(turn_number=3, audio_rms_db=-30.0),
        ]
        assert metrics.avg_rms_db == -25.0

    def test_avg_peak_db_calculation(self):
        """Test average peak calculation across turns."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        metrics._turn_metrics = [
            TurnMetrics(turn_number=1, audio_peak_db=-10.0),
            TurnMetrics(turn_number=2, audio_peak_db=-20.0),
        ]
        assert metrics.avg_peak_db == -15.0

    def test_poor_audio_turns_default(self):
        """Test poor_audio_turns defaults to 0."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        assert metrics.poor_audio_turns == 0

    def test_to_dict_includes_audio_quality(self):
        """Test to_dict includes audio quality metrics."""
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        metrics._turn_metrics = [
            TurnMetrics(turn_number=1, audio_rms_db=-20.0, audio_peak_db=-10.0),
        ]
        metrics.poor_audio_turns = 2

        result = metrics.to_dict()
        assert "avg_rms_db" in result
        assert "avg_peak_db" in result
        assert "poor_audio_turns" in result
        assert result["poor_audio_turns"] == 2

    def test_turn_metrics_to_dict_includes_audio_quality(self):
        """Test TurnMetrics to_dict includes audio quality fields."""
        turn = TurnMetrics(
            turn_number=1,
            audio_rms_db=-25.5,
            audio_peak_db=-12.3,
            silence_duration_ms=350.0,
        )
        result = turn.to_dict()
        assert result["audio_rms_db"] == -25.5
        assert result["audio_peak_db"] == -12.3
        assert result["silence_duration_ms"] == 350.0

    def test_turn_metrics_to_dict_includes_rms_distribution(self):
        """Test TurnMetrics to_dict includes RMS distribution fields."""
        turn = TurnMetrics(
            turn_number=1,
            audio_rms_db=-50.0,
            audio_rms_min_db=-72.5,
            audio_rms_max_db=-25.0,
            audio_rms_stddev_db=15.3,
        )
        result = turn.to_dict()
        assert result["audio_rms_min_db"] == -72.5
        assert result["audio_rms_max_db"] == -25.0
        assert result["audio_rms_stddev_db"] == 15.3


# =============================================================================
# Frame Deduplication Tests
# =============================================================================


class TestFrameDedup:
    """Test that observers deduplicate frames pushed through multiple processors."""

    def _make_frame_pushed(self, frame, source=None):
        """Helper to create FramePushed with a given source."""
        from unittest.mock import MagicMock

        mock_source = source or MagicMock()
        mock_dest = MagicMock()
        mock_dest.name = "test_dest"
        return FramePushed(
            source=mock_source,
            frame=frame,
            direction=FrameDirection.DOWNSTREAM,
            timestamp=0,
            destination=mock_dest,
        )

    @pytest.mark.asyncio
    async def test_metrics_observer_dedup_speaking_frames(self):
        """Same BotStartedSpeakingFrame pushed through N processors fires once."""
        from app.observability import MetricsObserver

        collector = MetricsCollector("call-1", "sess-1", "test")
        observer = MetricsObserver(collector)

        # Simulate a user speech start
        user_start = UserStartedSpeakingFrame()
        for _ in range(11):
            await observer.on_push_frame(self._make_frame_pushed(user_start))

        # start_turn should be called exactly once
        assert collector.turn_count == 1

    @pytest.mark.asyncio
    async def test_conversation_observer_dedup_bot_speaking(self):
        """Same BotStartedSpeakingFrame should only log once."""
        from app.observability import ConversationObserver

        collector = MetricsCollector("call-1", "sess-1", "test")
        observer = ConversationObserver(collector, enabled=True)

        frame = BotStartedSpeakingFrame()
        for _ in range(11):
            await observer.on_push_frame(self._make_frame_pushed(frame))

        # _bot_speaking should be True (set once), not toggled 11 times
        assert observer._bot_speaking is True

    @pytest.mark.asyncio
    async def test_audio_quality_observer_dedup_audio_frames(self):
        """Same InputAudioRawFrame pushed through N processors counts once."""
        import struct
        from app.observability import AudioQualityObserver

        collector = MetricsCollector("call-1", "sess-1", "test")
        collector.start_turn()
        observer = AudioQualityObserver(collector, enabled=True)

        # Start speech
        await observer.on_push_frame(
            self._make_frame_pushed(UserStartedSpeakingFrame())
        )

        # Same audio frame through 11 processors
        audio_bytes = struct.pack("<5h", 1000, 2000, 3000, -1000, -2000)
        audio_frame = InputAudioRawFrame(
            audio=audio_bytes, sample_rate=8000, num_channels=1
        )
        for _ in range(11):
            await observer.on_push_frame(self._make_frame_pushed(audio_frame))

        # Should only accumulate 1 RMS sample, not 11
        assert len(observer._rms_samples) == 1

    @pytest.mark.asyncio
    async def test_is_new_frame_helper(self):
        """Test the _is_new_frame helper directly."""
        from app.observability import _is_new_frame

        seen: dict[type, set[int]] = {}
        frame = BotStartedSpeakingFrame()

        # Wrap in FramePushed (downstream direction = 1)
        def fp(f):
            return self._make_frame_pushed(f)

        assert _is_new_frame(seen, fp(frame)) is True
        assert _is_new_frame(seen, fp(frame)) is False
        assert _is_new_frame(seen, fp(frame)) is False

        # Different frame instance of same type
        frame2 = BotStartedSpeakingFrame()
        assert _is_new_frame(seen, fp(frame2)) is True
        assert _is_new_frame(seen, fp(frame2)) is False

        # Original frame still deduped
        assert _is_new_frame(seen, fp(frame)) is False

        # Different frame type
        frame3 = BotStoppedSpeakingFrame()
        assert _is_new_frame(seen, fp(frame3)) is True
