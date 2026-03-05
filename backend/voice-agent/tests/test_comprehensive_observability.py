"""
Tests for comprehensive observability metrics: STTQualityObserver, LLMQualityObserver,
ConversationFlowObserver, and QualityScoreCalculator.

Run with: pytest tests/test_comprehensive_observability.py -v
"""

import asyncio
import pytest
from unittest.mock import MagicMock, create_autospec

try:
    from pipecat.frames.frames import (
        TranscriptionFrame,
        InterimTranscriptionFrame,
        TextFrame,
        LLMFullResponseStartFrame,
        LLMFullResponseEndFrame,
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
        BotStartedSpeakingFrame,
        BotStoppedSpeakingFrame,
    )
    from pipecat.observers.base_observer import FramePushed
    from pipecat.services.llm_service import LLMService
    from pipecat.processors.frame_processor import FrameDirection
except ImportError:
    pytest.skip(
        "pipecat not available (container-only dependency)", allow_module_level=True
    )

from app.observability import (
    MetricsCollector,
    STTQualityObserver,
    LLMQualityObserver,
    ConversationFlowObserver,
    QualityScoreCalculator,
    TurnMetrics,
)

import time


def make_frame_pushed(frame, source=None):
    """Create a FramePushed object for testing."""
    return FramePushed(
        frame=frame,
        source=source,
        destination=None,
        direction=FrameDirection.DOWNSTREAM,
        timestamp=int(time.time() * 1_000_000),  # Microseconds
    )


class MockDeepgramResult:
    """Mock Deepgram result structure."""

    def __init__(self, confidence, is_final=True):
        self.channel = MagicMock()
        self.channel.alternatives = [MagicMock()]
        self.channel.alternatives[0].confidence = confidence
        self.is_final = is_final


class TestSTTQualityObserver:
    """Tests for STT quality metrics collection."""

    @pytest.mark.asyncio
    async def test_confidence_score_aggregation(self):
        """Test STT confidence scores are properly aggregated with object results."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = STTQualityObserver(collector, enabled=True)

        # Simulate interim frames (InterimTranscriptionFrame) then a final frame
        frames = [
            InterimTranscriptionFrame(
                text="Hello",
                user_id="user",
                timestamp="2024-01-01",
                result=MockDeepgramResult(confidence=0.95, is_final=False),
            ),
            InterimTranscriptionFrame(
                text="Hello there",
                user_id="user",
                timestamp="2024-01-01",
                result=MockDeepgramResult(confidence=0.92, is_final=False),
            ),
            TranscriptionFrame(
                text="Hello there!",
                user_id="user",
                timestamp="2024-01-01",
                result=MockDeepgramResult(confidence=0.88, is_final=True),
            ),
        ]

        for frame in frames:
            await observer.on_push_frame(make_frame_pushed(frame))

        turn = collector.current_turn
        assert turn.stt_confidence_avg == pytest.approx(0.917, abs=0.01)
        assert turn.stt_confidence_min == 0.88
        assert turn.stt_interim_count == 2
        assert turn.stt_final_count == 1
        assert turn.stt_word_count == 2  # "Hello there!" = 2 words

    @pytest.mark.asyncio
    async def test_disabled_observer_does_nothing(self):
        """Test that disabled observer doesn't record metrics."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = STTQualityObserver(collector, enabled=False)

        frame = TranscriptionFrame(
            text="Hello",
            user_id="user",
            timestamp="2024-01-01",
            result=MockDeepgramResult(confidence=0.95, is_final=True),
        )

        await observer.on_push_frame(make_frame_pushed(frame))

        turn = collector.current_turn
        assert turn.stt_confidence_avg is None

    @pytest.mark.asyncio
    async def test_no_result_attribute(self):
        """Test handling frames without result attribute."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = STTQualityObserver(collector, enabled=True)

        # Frame without result attribute — should still count as final
        frame = TranscriptionFrame(text="Hello", user_id="user", timestamp="2024-01-01")

        await observer.on_push_frame(make_frame_pushed(frame))

        turn = collector.current_turn
        # No confidence, but final_count and word_count should be recorded
        assert turn.stt_confidence_avg is None
        assert turn.stt_final_count == 1
        assert turn.stt_word_count == 1

    @pytest.mark.asyncio
    async def test_sagemaker_dict_result_confidence(self):
        """Test confidence extraction from SageMaker dict result format."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = STTQualityObserver(collector, enabled=True)

        # SageMaker STT emits result as a raw dict
        sagemaker_result = {
            "channel": {
                "alternatives": [
                    {
                        "transcript": "Hello there",
                        "confidence": 0.93,
                    }
                ]
            },
            "is_final": True,
            "speech_final": True,
        }

        frame = TranscriptionFrame(
            text="Hello there",
            user_id="user",
            timestamp="2024-01-01",
            result=sagemaker_result,
        )

        await observer.on_push_frame(make_frame_pushed(frame))

        turn = collector.current_turn
        assert turn.stt_confidence_avg == pytest.approx(0.93, abs=0.01)
        assert turn.stt_confidence_min == pytest.approx(0.93, abs=0.01)
        assert turn.stt_final_count == 1
        assert turn.stt_word_count == 2

    @pytest.mark.asyncio
    async def test_sagemaker_dict_result_without_confidence(self):
        """Test dict result without confidence still records counts."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = STTQualityObserver(collector, enabled=True)

        # SageMaker result without confidence field
        sagemaker_result = {
            "channel": {
                "alternatives": [
                    {
                        "transcript": "Hi",
                    }
                ]
            },
            "is_final": True,
        }

        frame = TranscriptionFrame(
            text="Hi",
            user_id="user",
            timestamp="2024-01-01",
            result=sagemaker_result,
        )

        await observer.on_push_frame(make_frame_pushed(frame))

        turn = collector.current_turn
        assert turn.stt_confidence_avg is None
        assert turn.stt_final_count == 1
        assert turn.stt_word_count == 1

    @pytest.mark.asyncio
    async def test_sagemaker_mixed_interim_and_final_flow(self):
        """Test full SageMaker flow: interim dict frames + final dict frame."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = STTQualityObserver(collector, enabled=True)

        # Two interim frames (InterimTranscriptionFrame with dict results)
        interim1_result = {
            "channel": {"alternatives": [{"transcript": "I", "confidence": 0.80}]},
            "is_final": False,
        }
        interim2_result = {
            "channel": {
                "alternatives": [{"transcript": "I need help", "confidence": 0.85}]
            },
            "is_final": False,
        }
        # Final frame
        final_result = {
            "channel": {
                "alternatives": [
                    {"transcript": "I need help please", "confidence": 0.91}
                ]
            },
            "is_final": True,
            "speech_final": True,
        }

        frames = [
            InterimTranscriptionFrame(
                text="I",
                user_id="user",
                timestamp="2024-01-01",
                result=interim1_result,
            ),
            InterimTranscriptionFrame(
                text="I need help",
                user_id="user",
                timestamp="2024-01-01",
                result=interim2_result,
            ),
            TranscriptionFrame(
                text="I need help please",
                user_id="user",
                timestamp="2024-01-01",
                result=final_result,
            ),
        ]

        for frame in frames:
            await observer.on_push_frame(make_frame_pushed(frame))

        turn = collector.current_turn
        expected_avg = (0.80 + 0.85 + 0.91) / 3
        assert turn.stt_confidence_avg == pytest.approx(expected_avg, abs=0.01)
        assert turn.stt_confidence_min == pytest.approx(0.80, abs=0.01)
        assert turn.stt_interim_count == 2
        assert turn.stt_final_count == 1
        assert turn.stt_word_count == 4  # "I need help please"

    @pytest.mark.asyncio
    async def test_interim_transcription_frame_counting(self):
        """Test that InterimTranscriptionFrame increments interim count."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = STTQualityObserver(collector, enabled=True)

        # Push 3 interim frames then 1 final
        for i in range(3):
            interim = InterimTranscriptionFrame(
                text=f"word{i}",
                user_id="user",
                timestamp="2024-01-01",
                result=MockDeepgramResult(confidence=0.90, is_final=False),
            )
            await observer.on_push_frame(make_frame_pushed(interim))

        final = TranscriptionFrame(
            text="word0 word1 word2 done",
            user_id="user",
            timestamp="2024-01-01",
            result=MockDeepgramResult(confidence=0.95, is_final=True),
        )
        await observer.on_push_frame(make_frame_pushed(final))

        turn = collector.current_turn
        assert turn.stt_interim_count == 3
        assert turn.stt_final_count == 1
        assert turn.stt_word_count == 4


class TestLLMQualityObserver:
    """Tests for LLM quality metrics collection."""

    @pytest.mark.asyncio
    async def test_token_counting(self):
        """Test LLM token counting and speed calculation."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = LLMQualityObserver(collector, enabled=True)

        # Start LLM response
        await observer.on_push_frame(make_frame_pushed(LLMFullResponseStartFrame()))

        # Simulate text chunks (each ~4 chars = 1 token)
        text_frames = [
            TextFrame(text="Hello "),
            TextFrame(text="world, "),
            TextFrame(text="this "),
            TextFrame(text="is "),
            TextFrame(text="a "),
            TextFrame(text="test."),
        ]

        for frame in text_frames:
            await observer.on_push_frame(make_frame_pushed(frame))

        # End response
        await asyncio.sleep(0.01)  # Small delay to ensure measurable time
        await observer.on_push_frame(make_frame_pushed(LLMFullResponseEndFrame()))

        turn = collector.current_turn
        # Total text: "Hello world, this is a test." = ~28 chars = ~7 tokens
        assert turn.llm_output_tokens is not None
        assert turn.llm_output_tokens > 0
        assert turn.llm_tokens_per_second is not None
        assert turn.llm_tokens_per_second > 0

    @pytest.mark.asyncio
    async def test_disabled_observer_does_nothing(self):
        """Test that disabled observer doesn't record metrics."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = LLMQualityObserver(collector, enabled=False)

        await observer.on_push_frame(make_frame_pushed(LLMFullResponseStartFrame()))
        await observer.on_push_frame(make_frame_pushed(TextFrame(text="Hello")))
        await observer.on_push_frame(make_frame_pushed(LLMFullResponseEndFrame()))

        turn = collector.current_turn
        assert turn.llm_output_tokens is None


class TestConversationFlowObserver:
    """Tests for conversation flow metrics collection."""

    @pytest.mark.asyncio
    async def test_turn_gap_calculation(self):
        """Test turn gap calculation between bot stop and user start."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationFlowObserver(collector, enabled=True)

        # Bot stops speaking
        await observer.on_push_frame(make_frame_pushed(BotStoppedSpeakingFrame()))

        await asyncio.sleep(0.01)  # 10ms gap

        # User starts speaking
        await observer.on_push_frame(make_frame_pushed(UserStartedSpeakingFrame()))

        turn = collector.current_turn
        assert turn.turn_gap_ms is not None
        assert turn.turn_gap_ms >= 10.0  # At least 10ms

    @pytest.mark.asyncio
    async def test_response_delay_calculation(self):
        """Test response delay calculation between user stop and bot start."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationFlowObserver(collector, enabled=True)

        # User stops speaking
        await observer.on_push_frame(make_frame_pushed(UserStoppedSpeakingFrame()))

        await asyncio.sleep(0.01)  # 10ms delay

        # Bot starts speaking
        await observer.on_push_frame(make_frame_pushed(BotStartedSpeakingFrame()))

        turn = collector.current_turn
        assert turn.response_delay_ms is not None
        assert turn.response_delay_ms >= 10.0  # At least 10ms

    @pytest.mark.asyncio
    async def test_speaking_durations(self):
        """Test user and bot speaking duration recording."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationFlowObserver(collector, enabled=True)

        # User speaks
        await observer.on_push_frame(make_frame_pushed(UserStartedSpeakingFrame()))
        await asyncio.sleep(0.01)
        await observer.on_push_frame(make_frame_pushed(UserStoppedSpeakingFrame()))

        turn = collector.current_turn
        assert turn.user_speaking_duration_ms is not None
        assert turn.user_speaking_duration_ms >= 10.0

    @pytest.mark.asyncio
    async def test_disabled_observer_does_nothing(self):
        """Test that disabled observer doesn't record metrics."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = ConversationFlowObserver(collector, enabled=False)

        await observer.on_push_frame(make_frame_pushed(UserStoppedSpeakingFrame()))
        await observer.on_push_frame(make_frame_pushed(BotStartedSpeakingFrame()))

        turn = collector.current_turn
        assert turn.response_delay_ms is None


class TestQualityScoreCalculator:
    """Tests for composite quality score calculation."""

    def test_excellent_quality_score(self):
        """Test quality score calculation for excellent metrics."""
        turn = TurnMetrics(
            turn_number=1,
            agent_response_latency_ms=500,  # Excellent
            audio_rms_db=-25,  # Excellent
            stt_confidence_avg=0.95,  # Excellent
            turn_gap_ms=300,  # Excellent
            webrtc_rtt_ms=30,  # Excellent
        )

        score = QualityScoreCalculator.calculate_turn_quality(turn)
        assert score >= 0.9  # Should be excellent

    def test_poor_quality_score(self):
        """Test quality score calculation for poor metrics."""
        turn = TurnMetrics(
            turn_number=1,
            agent_response_latency_ms=3000,  # Poor
            audio_rms_db=-75,  # Poor (below -70 threshold)
            stt_confidence_avg=0.5,  # Poor
            turn_gap_ms=3000,  # Poor
            webrtc_rtt_ms=300,  # Poor
        )

        score = QualityScoreCalculator.calculate_turn_quality(turn)
        assert score <= 0.3  # Should be poor

    def test_mixed_quality_score(self):
        """Test quality score with mixed metrics."""
        turn = TurnMetrics(
            turn_number=1,
            agent_response_latency_ms=1500,  # Medium
            audio_rms_db=-40,  # Medium
            stt_confidence_avg=0.75,  # Medium
        )

        score = QualityScoreCalculator.calculate_turn_quality(turn)
        assert 0.4 <= score <= 0.7  # Should be medium

    def test_neutral_score_when_no_data(self):
        """Test that score is neutral when no metrics available."""
        turn = TurnMetrics(turn_number=1)

        score = QualityScoreCalculator.calculate_turn_quality(turn)
        assert score == 0.5  # Neutral score

    def test_latency_scoring(self):
        """Test latency scoring function."""
        # Excellent latency
        assert QualityScoreCalculator._score_latency(500) == 1.0
        # Poor latency
        assert QualityScoreCalculator._score_latency(3000) == 0.0
        # Medium latency (linear interpolation)
        score = QualityScoreCalculator._score_latency(1400)
        assert 0.0 < score < 1.0

    def test_audio_quality_scoring(self):
        """Test audio quality scoring function."""
        # Excellent audio
        assert QualityScoreCalculator._score_audio_quality(-25) == 1.0
        # Poor audio (below -70 threshold)
        assert QualityScoreCalculator._score_audio_quality(-75) == 0.0
        # Medium audio (between -30 excellent and -70 poor)
        score = QualityScoreCalculator._score_audio_quality(-50)
        assert 0.0 < score < 1.0

    def test_configure_updates_threshold(self):
        """Test that configure() updates the poor audio threshold."""
        original = QualityScoreCalculator.THRESHOLDS["poor_audio_db"]
        try:
            # Configure a stricter threshold
            QualityScoreCalculator.configure(-55.0)
            assert QualityScoreCalculator.THRESHOLDS["poor_audio_db"] == -55.0

            # Audio at -60 dB should now score 0.0 (below -55 threshold)
            assert QualityScoreCalculator._score_audio_quality(-60) == 0.0

            # Audio at -50 dB should score > 0.0 (above -55 threshold)
            score = QualityScoreCalculator._score_audio_quality(-50)
            assert score > 0.0
        finally:
            # Restore original threshold for other tests
            QualityScoreCalculator.configure(original)

    def test_stt_confidence_scoring(self):
        """Test STT confidence scoring function."""
        # Excellent confidence
        assert QualityScoreCalculator._score_stt_confidence(0.95) == 1.0
        # Poor confidence
        assert QualityScoreCalculator._score_stt_confidence(0.5) == 0.0
        # Medium confidence
        score = QualityScoreCalculator._score_stt_confidence(0.75)
        assert 0.0 < score < 1.0


class TestMetricsCollectorNewMethods:
    """Tests for new MetricsCollector recording methods."""

    def test_record_stt_quality(self):
        """Test STT quality recording."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        collector.record_stt_quality(
            confidence_avg=0.85,
            confidence_min=0.75,
            interim_count=2,
            final_count=1,
            word_count=10,
        )

        turn = collector.current_turn
        assert turn.stt_confidence_avg == 0.85
        assert turn.stt_confidence_min == 0.75
        assert turn.stt_interim_count == 2
        assert turn.stt_final_count == 1
        assert turn.stt_word_count == 10

    def test_record_llm_quality(self):
        """Test LLM quality recording."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        collector.record_llm_quality(output_tokens=100, tokens_per_second=50.5)

        turn = collector.current_turn
        assert turn.llm_output_tokens == 100
        assert turn.llm_tokens_per_second == 50.5

    def test_record_webrtc_quality(self):
        """Test WebRTC quality recording."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        collector.record_webrtc_quality(
            rtt_ms=50.0, jitter_ms=5.0, packet_loss_percent=0.1, bitrate_kbps=64.0
        )

        turn = collector.current_turn
        assert turn.webrtc_rtt_ms == 50.0
        assert turn.webrtc_jitter_ms == 5.0
        assert turn.webrtc_packet_loss_percent == 0.1
        assert turn.webrtc_bitrate_kbps == 64.0

    def test_record_conversation_flow_metrics(self):
        """Test conversation flow metrics recording."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        collector.record_turn_gap(500.0)
        collector.record_user_speaking_duration(2000.0)
        collector.record_bot_speaking_duration(3000.0)
        collector.record_response_delay(800.0)

        turn = collector.current_turn
        assert turn.turn_gap_ms == 500.0
        assert turn.user_speaking_duration_ms == 2000.0
        assert turn.bot_speaking_duration_ms == 3000.0
        assert turn.response_delay_ms == 800.0

    def test_record_quality_score(self):
        """Test quality score recording."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        collector.record_quality_score(0.85)

        turn = collector.current_turn
        assert turn.quality_score == 0.85
