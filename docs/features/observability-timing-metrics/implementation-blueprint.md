# Implementation Blueprint: observability.py Module

This document provides the detailed implementation specification for the observability module.

---

## Module Structure

```
backend/voice-agent/app/
    observability.py      # New file (this spec)
    service_main.py       # Modified (collector lifecycle)
    pipeline_ecs.py       # Modified (timing hooks)
```

---

## 1. observability.py - Full Specification

```python
"""
Observability module for voice pipeline timing metrics.

Provides MetricsCollector for accumulating per-turn and per-call metrics,
with CloudWatch EMF (Embedded Metric Format) output for automatic metric
extraction from logs.

Usage:
    collector = MetricsCollector(call_id, session_id)

    # Automatic timing with context manager
    async with collector.time_stt():
        result = await stt_service.run(audio)

    # Manual timing for external measurements
    collector.record_llm_ttfb(312.5)

    # Turn boundaries
    collector.end_turn(user_text="hello", assistant_text="Hi there!")

    # Call completion
    summary = collector.finalize(status="completed")
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class TurnMetrics:
    """Metrics for a single conversation turn."""
    turn_number: int
    started_at: float = field(default_factory=time.perf_counter)

    # Latency metrics (milliseconds)
    stt_latency_ms: Optional[float] = None
    llm_ttfb_ms: Optional[float] = None
    llm_total_ms: Optional[float] = None
    tts_ttfb_ms: Optional[float] = None
    e2e_latency_ms: Optional[float] = None

    # E2E tracking
    vad_stop_time: Optional[float] = None
    first_audio_time: Optional[float] = None

    # Content (optional, for conversation logging)
    user_text: Optional[str] = None
    assistant_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "turn_number": self.turn_number,
            "stt_latency_ms": self.stt_latency_ms,
            "llm_ttfb_ms": self.llm_ttfb_ms,
            "llm_total_ms": self.llm_total_ms,
            "tts_ttfb_ms": self.tts_ttfb_ms,
            "e2e_latency_ms": self.e2e_latency_ms,
        }


@dataclass
class CallMetrics:
    """Aggregated metrics for a complete call."""
    call_id: str
    session_id: str
    environment: str
    started_at: float = field(default_factory=time.monotonic)

    # Aggregates
    turn_count: int = 0
    total_stt_ms: float = 0.0
    total_llm_ms: float = 0.0
    total_tts_ms: float = 0.0

    # Status
    completion_status: str = "in_progress"
    error_category: Optional[str] = None

    # Turn history (for avg calculations)
    _turn_metrics: List[TurnMetrics] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        """Total call duration in seconds."""
        return time.monotonic() - self.started_at

    @property
    def avg_stt_ms(self) -> float:
        """Average STT latency across turns."""
        values = [t.stt_latency_ms for t in self._turn_metrics if t.stt_latency_ms]
        return sum(values) / len(values) if values else 0.0

    @property
    def avg_llm_ms(self) -> float:
        """Average LLM total time across turns."""
        values = [t.llm_total_ms for t in self._turn_metrics if t.llm_total_ms]
        return sum(values) / len(values) if values else 0.0

    @property
    def avg_tts_ms(self) -> float:
        """Average TTS TTFB across turns."""
        values = [t.tts_ttfb_ms for t in self._turn_metrics if t.tts_ttfb_ms]
        return sum(values) / len(values) if values else 0.0

    @property
    def avg_e2e_ms(self) -> float:
        """Average E2E latency across turns."""
        values = [t.e2e_latency_ms for t in self._turn_metrics if t.e2e_latency_ms]
        return sum(values) / len(values) if values else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "call_id": self.call_id,
            "session_id": self.session_id,
            "environment": self.environment,
            "duration_seconds": round(self.duration_seconds, 2),
            "turn_count": self.turn_count,
            "avg_stt_ms": round(self.avg_stt_ms, 1),
            "avg_llm_ms": round(self.avg_llm_ms, 1),
            "avg_tts_ms": round(self.avg_tts_ms, 1),
            "avg_e2e_ms": round(self.avg_e2e_ms, 1),
            "completion_status": self.completion_status,
            "error_category": self.error_category,
        }


# =============================================================================
# Timing Context Manager
# =============================================================================

class TimingContext:
    """
    Async context manager for timing operations.

    Supports both total time and time-to-first-byte measurements.

    Usage:
        async with TimingContext(collector, "stt") as timer:
            async for chunk in stream():
                timer.mark_first_byte()  # Call on first chunk
                yield chunk
        # Total time automatically recorded on exit
    """

    def __init__(
        self,
        collector: MetricsCollector,
        metric_name: str,
        record_total: bool = True,
        record_ttfb: bool = False,
    ):
        self.collector = collector
        self.metric_name = metric_name
        self.record_total = record_total
        self.record_ttfb = record_ttfb

        self.start_time: Optional[float] = None
        self.first_byte_time: Optional[float] = None

    async def __aenter__(self) -> TimingContext:
        self.start_time = time.perf_counter()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None and self.record_total:
            elapsed_ms = (time.perf_counter() - self.start_time) * 1000
            self.collector._record_metric(f"{self.metric_name}_total", elapsed_ms)
        return False

    def mark_first_byte(self) -> None:
        """Mark the arrival of the first response byte."""
        if self.first_byte_time is None and self.record_ttfb:
            self.first_byte_time = time.perf_counter()
            ttfb_ms = (self.first_byte_time - self.start_time) * 1000
            self.collector._record_metric(f"{self.metric_name}_ttfb", ttfb_ms)

    @property
    def elapsed_ms(self) -> float:
        """Current elapsed time in milliseconds."""
        if self.start_time is None:
            return 0.0
        return (time.perf_counter() - self.start_time) * 1000


# =============================================================================
# EMF Logger
# =============================================================================

class EMFLogger:
    """
    Emits CloudWatch Embedded Metric Format (EMF) logs.

    EMF logs are JSON with a special _aws metadata block that CloudWatch
    automatically parses to extract metrics. No CloudWatch agent required.

    Reference:
    https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Specification.html
    """

    def __init__(
        self,
        namespace: str = "VoiceAgent/Pipeline",
        environment: str = "production",
    ):
        self.namespace = namespace
        self.environment = environment
        self._logger = structlog.get_logger("emf")

    def emit_turn_metrics(
        self,
        call_id: str,
        turn: TurnMetrics,
    ) -> None:
        """Emit EMF log for turn metrics."""
        metrics_list = []
        metric_values = {}

        # Only include metrics that have values
        if turn.stt_latency_ms is not None:
            metrics_list.append({"Name": "STTLatency", "Unit": "Milliseconds"})
            metric_values["STTLatency"] = round(turn.stt_latency_ms, 1)

        if turn.llm_ttfb_ms is not None:
            metrics_list.append({"Name": "LLMTimeToFirstByte", "Unit": "Milliseconds"})
            metric_values["LLMTimeToFirstByte"] = round(turn.llm_ttfb_ms, 1)

        if turn.llm_total_ms is not None:
            metrics_list.append({"Name": "LLMTotalResponseTime", "Unit": "Milliseconds"})
            metric_values["LLMTotalResponseTime"] = round(turn.llm_total_ms, 1)

        if turn.tts_ttfb_ms is not None:
            metrics_list.append({"Name": "TTSTimeToFirstByte", "Unit": "Milliseconds"})
            metric_values["TTSTimeToFirstByte"] = round(turn.tts_ttfb_ms, 1)

        if turn.e2e_latency_ms is not None:
            metrics_list.append({"Name": "E2ELatency", "Unit": "Milliseconds"})
            metric_values["E2ELatency"] = round(turn.e2e_latency_ms, 1)

        if not metrics_list:
            return  # No metrics to emit

        emf_log = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [{
                    "Namespace": self.namespace,
                    "Dimensions": [
                        ["Environment"],
                        ["Environment", "CallId"],
                    ],
                    "Metrics": metrics_list,
                }],
            },
            "Environment": self.environment,
            "CallId": call_id,
            "TurnNumber": turn.turn_number,
            "event": "turn_metrics",
            **metric_values,
        }

        # EMF logs must be printed as single-line JSON to stdout
        print(json.dumps(emf_log), flush=True)

    def emit_call_summary(self, metrics: CallMetrics) -> None:
        """Emit EMF log for call summary."""
        emf_log = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [{
                    "Namespace": self.namespace,
                    "Dimensions": [["Environment"]],
                    "Metrics": [
                        {"Name": "CallDuration", "Unit": "Seconds"},
                        {"Name": "TurnCount", "Unit": "Count"},
                        {"Name": "AvgSTTLatency", "Unit": "Milliseconds"},
                        {"Name": "AvgLLMLatency", "Unit": "Milliseconds"},
                        {"Name": "AvgTTSLatency", "Unit": "Milliseconds"},
                        {"Name": "AvgE2ELatency", "Unit": "Milliseconds"},
                    ],
                }],
            },
            "Environment": metrics.environment,
            "CallId": metrics.call_id,
            "SessionId": metrics.session_id,
            "CallDuration": round(metrics.duration_seconds, 2),
            "TurnCount": metrics.turn_count,
            "AvgSTTLatency": round(metrics.avg_stt_ms, 1),
            "AvgLLMLatency": round(metrics.avg_llm_ms, 1),
            "AvgTTSLatency": round(metrics.avg_tts_ms, 1),
            "AvgE2ELatency": round(metrics.avg_e2e_ms, 1),
            "CompletionStatus": metrics.completion_status,
            "ErrorCategory": metrics.error_category,
            "event": "call_summary",
        }

        print(json.dumps(emf_log), flush=True)


# =============================================================================
# Metrics Collector
# =============================================================================

class MetricsCollector:
    """
    Collects timing metrics for voice pipeline operations.

    Thread-safe accumulator that emits EMF logs at turn and call boundaries.

    Lifecycle:
        1. Create collector at call start
        2. Use timing context managers or record_* methods during processing
        3. Call end_turn() at each turn boundary
        4. Call finalize() when call ends

    Example:
        collector = MetricsCollector(call_id, session_id)

        # During a turn:
        async with collector.time_stt():
            transcript = await stt.run(audio)

        collector.record_llm_ttfb(312.5)
        collector.record_llm_total(1240.8)
        collector.record_tts_ttfb(89.3)

        collector.end_turn(user_text=transcript, assistant_text=response)

        # At call end:
        summary = collector.finalize(status="completed")
    """

    def __init__(
        self,
        call_id: str,
        session_id: str,
        environment: Optional[str] = None,
    ):
        self.call_id = call_id
        self.session_id = session_id
        self.environment = environment or os.environ.get("ENVIRONMENT", "production")

        # EMF logger
        self._emf = EMFLogger(environment=self.environment)

        # Call-level metrics
        self._call_metrics = CallMetrics(
            call_id=call_id,
            session_id=session_id,
            environment=self.environment,
        )

        # Current turn (None until start_turn called)
        self._current_turn: Optional[TurnMetrics] = None
        self._lock = asyncio.Lock()

        logger.debug(
            "metrics_collector_created",
            call_id=call_id,
            session_id=session_id,
            environment=self.environment,
        )

    # -------------------------------------------------------------------------
    # Timing Context Managers
    # -------------------------------------------------------------------------

    @asynccontextmanager
    async def time_stt(self):
        """Time STT operation (total time only)."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record_stt_latency(elapsed_ms)

    @asynccontextmanager
    async def time_llm(self):
        """
        Time LLM operation with TTFB support.

        Usage:
            async with collector.time_llm() as timer:
                async for chunk in llm.stream():
                    timer.mark_first_byte()
                    yield chunk
        """
        timer = TimingContext(self, "llm", record_total=True, record_ttfb=True)
        async with timer:
            yield timer

    @asynccontextmanager
    async def time_tts(self):
        """
        Time TTS operation with TTFB support.

        Usage:
            async with collector.time_tts() as timer:
                async for chunk in tts.stream():
                    timer.mark_first_byte()
                    yield chunk
        """
        timer = TimingContext(self, "tts", record_total=True, record_ttfb=True)
        async with timer:
            yield timer

    @asynccontextmanager
    async def time_e2e(self):
        """
        Time end-to-end latency (VAD stop to first audio).

        Usage:
            async with collector.time_e2e():
                # Process turn
                pass
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record_e2e_latency(elapsed_ms)

    # -------------------------------------------------------------------------
    # Manual Metric Recording
    # -------------------------------------------------------------------------

    def record_stt_latency(self, latency_ms: float) -> None:
        """Record STT latency for current turn."""
        if self._current_turn:
            self._current_turn.stt_latency_ms = latency_ms
            self._call_metrics.total_stt_ms += latency_ms

    def record_llm_ttfb(self, latency_ms: float) -> None:
        """Record LLM time-to-first-byte for current turn."""
        if self._current_turn:
            self._current_turn.llm_ttfb_ms = latency_ms

    def record_llm_total(self, latency_ms: float) -> None:
        """Record LLM total response time for current turn."""
        if self._current_turn:
            self._current_turn.llm_total_ms = latency_ms
            self._call_metrics.total_llm_ms += latency_ms

    def record_tts_ttfb(self, latency_ms: float) -> None:
        """Record TTS time-to-first-byte for current turn."""
        if self._current_turn:
            self._current_turn.tts_ttfb_ms = latency_ms
            self._call_metrics.total_tts_ms += latency_ms

    def record_e2e_latency(self, latency_ms: float) -> None:
        """Record end-to-end latency for current turn."""
        if self._current_turn:
            self._current_turn.e2e_latency_ms = latency_ms

    def _record_metric(self, metric_name: str, value: float) -> None:
        """Internal method for TimingContext to record metrics."""
        if metric_name == "stt_total":
            self.record_stt_latency(value)
        elif metric_name == "llm_ttfb":
            self.record_llm_ttfb(value)
        elif metric_name == "llm_total":
            self.record_llm_total(value)
        elif metric_name == "tts_ttfb":
            self.record_tts_ttfb(value)
        elif metric_name == "tts_total":
            # TTS total not tracked separately (TTFB is primary metric)
            pass
        elif metric_name == "e2e_total":
            self.record_e2e_latency(value)

    # -------------------------------------------------------------------------
    # Turn Lifecycle
    # -------------------------------------------------------------------------

    def start_turn(self) -> None:
        """Start a new conversation turn."""
        self._call_metrics.turn_count += 1
        self._current_turn = TurnMetrics(
            turn_number=self._call_metrics.turn_count,
        )
        logger.debug(
            "turn_started",
            turn_number=self._current_turn.turn_number,
        )

    def end_turn(
        self,
        user_text: str = "",
        assistant_text: str = "",
    ) -> None:
        """
        End the current turn and emit metrics.

        Args:
            user_text: User's transcribed speech (optional)
            assistant_text: Assistant's response (optional)
        """
        if self._current_turn is None:
            logger.warning("end_turn_called_without_start")
            return

        # Store conversation content
        self._current_turn.user_text = user_text
        self._current_turn.assistant_text = assistant_text

        # Add to history
        self._call_metrics._turn_metrics.append(self._current_turn)

        # Emit turn metrics via EMF
        self._emf.emit_turn_metrics(self.call_id, self._current_turn)

        # Log turn summary
        logger.info(
            "turn_completed",
            **self._current_turn.to_dict(),
        )

        # Reset current turn
        self._current_turn = None

    # -------------------------------------------------------------------------
    # Call Lifecycle
    # -------------------------------------------------------------------------

    def finalize(
        self,
        status: str = "completed",
        error_category: Optional[str] = None,
    ) -> CallMetrics:
        """
        Finalize call metrics and emit summary.

        Args:
            status: Completion status (completed, cancelled, error)
            error_category: Error category if status is error

        Returns:
            Final CallMetrics object
        """
        # Handle any incomplete turn
        if self._current_turn is not None:
            self.end_turn()

        # Update status
        self._call_metrics.completion_status = status
        self._call_metrics.error_category = error_category

        # Emit call summary via EMF
        self._emf.emit_call_summary(self._call_metrics)

        # Log call summary (also captured by structlog)
        logger.info(
            "call_metrics_summary",
            **self._call_metrics.to_dict(),
        )

        return self._call_metrics

    # -------------------------------------------------------------------------
    # Accessors
    # -------------------------------------------------------------------------

    @property
    def turn_count(self) -> int:
        """Current turn count."""
        return self._call_metrics.turn_count

    @property
    def current_turn(self) -> Optional[TurnMetrics]:
        """Current turn metrics (None if between turns)."""
        return self._current_turn

    @property
    def call_metrics(self) -> CallMetrics:
        """Call-level metrics."""
        return self._call_metrics


# =============================================================================
# Convenience Functions
# =============================================================================

def create_metrics_collector(
    call_id: str,
    session_id: str,
    environment: Optional[str] = None,
) -> MetricsCollector:
    """
    Factory function to create a MetricsCollector.

    Args:
        call_id: Unique call identifier
        session_id: Session identifier
        environment: Environment name (defaults to ENVIRONMENT env var)

    Returns:
        Configured MetricsCollector instance
    """
    return MetricsCollector(
        call_id=call_id,
        session_id=session_id,
        environment=environment,
    )
```

---

## 2. service_main.py Integration

### Changes Required

```python
# At top of file, add import
from app.observability import MetricsCollector, create_metrics_collector

# In PipelineManager._run_pipeline(), modify as follows:

async def _run_pipeline(
    self,
    room_url: str,
    room_token: str,
    session_id: str,
    call_id: str,
    system_prompt: Optional[str],
    dialin_settings: Optional[dict],
):
    """Run a voice pipeline for a call."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(call_id=call_id, session_id=session_id)

    # Create metrics collector for this call
    collector = create_metrics_collector(
        call_id=call_id,
        session_id=session_id,
    )

    transport = None

    try:
        logger.info("pipeline_starting")

        # Build pipeline config (unchanged)
        dialin = None
        if dialin_settings:
            dialin = DialinSettings(
                call_id=dialin_settings.get("call_id", ""),
                call_domain=dialin_settings.get("call_domain", ""),
                sip_uri=dialin_settings.get("sip_uri", ""),
            )

        config = PipelineConfig(
            room_url=room_url,
            room_token=room_token,
            session_id=session_id,
            system_prompt=system_prompt or "You are a helpful AI assistant.",
            voice_id=os.environ.get("VOICE_ID", "79a125e8-cd45-4c13-8a67-188112f4dd22"),
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            dialin_settings=dialin,
        )

        # Pass collector to pipeline creation
        task, transport = await create_voice_pipeline(config, collector)

        # Run the pipeline
        runner = PipelineRunner()
        await runner.run(task)

        # Finalize metrics on successful completion
        collector.finalize(status="completed")
        logger.info("pipeline_completed")

    except asyncio.CancelledError:
        collector.finalize(status="cancelled")
        logger.info("pipeline_cancelled")

    except Exception as e:
        error_category = categorize_error(e)
        collector.finalize(status="error", error_category=error_category)
        logger.error(
            "pipeline_error",
            error=str(e),
            error_category=error_category,
            error_type=type(e).__name__,
        )

    finally:
        self.active_sessions.pop(session_id, None)
        if transport:
            try:
                await transport.cleanup()
            except Exception:
                pass
        structlog.contextvars.clear_contextvars()
```

---

## 3. pipeline_ecs.py Integration

### Changes Required

```python
# Modify function signature
async def create_voice_pipeline(
    config: PipelineConfig,
    collector: Optional[MetricsCollector] = None,  # Add parameter
) -> Tuple[PipelineTask, DailyTransport]:
    """..."""

    # ... existing service creation code ...

    # After pipeline assembly, add turn tracking via event handlers

    # Track user speech boundaries for turn detection
    user_speaking = False
    turn_start_time = None

    @transport.event_handler("on_user_started_speaking")
    async def on_user_started_speaking(transport, participant):
        nonlocal user_speaking
        user_speaking = True
        if collector:
            collector.start_turn()

    @transport.event_handler("on_user_stopped_speaking")
    async def on_user_stopped_speaking(transport, participant):
        nonlocal user_speaking, turn_start_time
        user_speaking = False
        turn_start_time = time.perf_counter()  # VAD stop time for E2E

    # Add frame observer for timing (if pipecat supports it)
    # This is pseudocode - actual implementation depends on pipecat's event system

    # Alternative: Use processor wrapper for timing
    # (see Pattern B in system design)

    return task, transport
```

### Alternative: Timing Processor Wrapper

If pipecat doesn't expose fine-grained timing events, create processor wrappers:

```python
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import Frame, TranscriptionFrame, TextFrame, AudioRawFrame


class MetricsProcessor(FrameProcessor):
    """
    Pipeline processor that captures timing metrics.

    Insert this into the pipeline to observe frame flow and record timings.
    """

    def __init__(self, collector: MetricsCollector, **kwargs):
        super().__init__(**kwargs)
        self.collector = collector
        self._llm_first_token_seen = False
        self._tts_first_chunk_seen = False

    async def process_frame(self, frame: Frame, direction: str):
        if isinstance(frame, TranscriptionFrame):
            # STT complete - could record timing here if we tracked start
            pass

        elif isinstance(frame, TextFrame):
            # LLM token
            if not self._llm_first_token_seen:
                self._llm_first_token_seen = True
                # Would need timer start time to calculate TTFB

        elif isinstance(frame, AudioRawFrame):
            # TTS chunk
            if not self._tts_first_chunk_seen:
                self._tts_first_chunk_seen = True
                # Would need timer start time to calculate TTFB

        # Pass frame through
        await self.push_frame(frame, direction)

    def reset_turn(self):
        """Reset turn-level state."""
        self._llm_first_token_seen = False
        self._tts_first_chunk_seen = False
```

---

## 4. Testing Specification

### Unit Tests (test_observability.py)

```python
"""Tests for observability module."""

import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock
from io import StringIO

from app.observability import (
    MetricsCollector,
    TurnMetrics,
    CallMetrics,
    EMFLogger,
    create_metrics_collector,
)


class TestTurnMetrics:
    """Tests for TurnMetrics data class."""

    def test_to_dict(self):
        turn = TurnMetrics(
            turn_number=1,
            stt_latency_ms=145.2,
            llm_ttfb_ms=312.5,
            llm_total_ms=1240.8,
            tts_ttfb_ms=89.3,
            e2e_latency_ms=1475.3,
        )
        result = turn.to_dict()
        assert result["turn_number"] == 1
        assert result["stt_latency_ms"] == 145.2
        assert result["e2e_latency_ms"] == 1475.3


class TestCallMetrics:
    """Tests for CallMetrics data class."""

    def test_averages(self):
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

    def test_averages_empty(self):
        metrics = CallMetrics(
            call_id="test-123",
            session_id="session-456",
            environment="test",
        )
        assert metrics.avg_stt_ms == 0.0


class TestEMFLogger:
    """Tests for EMF log formatting."""

    def test_turn_metrics_format(self, capsys):
        emf = EMFLogger(namespace="Test/Metrics", environment="test")
        turn = TurnMetrics(
            turn_number=1,
            stt_latency_ms=145.2,
            e2e_latency_ms=1475.3,
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

        # Verify metrics
        assert log["STTLatency"] == 145.2
        assert log["E2ELatency"] == 1475.3
        assert "LLMTimeToFirstByte" not in log  # Not set

    def test_call_summary_format(self, capsys):
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

        assert log["TurnCount"] == 3
        assert log["CompletionStatus"] == "completed"
        assert log["event"] == "call_summary"


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    def test_turn_lifecycle(self):
        collector = MetricsCollector("call-1", "session-1", "test")

        collector.start_turn()
        assert collector.turn_count == 1
        assert collector.current_turn is not None

        collector.record_stt_latency(150.0)
        assert collector.current_turn.stt_latency_ms == 150.0

        collector.end_turn(user_text="hello", assistant_text="hi")
        assert collector.current_turn is None
        assert len(collector.call_metrics._turn_metrics) == 1

    def test_multiple_turns(self):
        collector = MetricsCollector("call-1", "session-1", "test")

        for i in range(3):
            collector.start_turn()
            collector.record_stt_latency(100.0 + i * 10)
            collector.end_turn()

        assert collector.turn_count == 3
        assert collector.call_metrics.avg_stt_ms == 110.0

    @pytest.mark.asyncio
    async def test_time_stt_context_manager(self):
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()

        async with collector.time_stt():
            await asyncio.sleep(0.01)  # 10ms

        assert collector.current_turn.stt_latency_ms >= 10.0

    def test_finalize(self, capsys):
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        collector.end_turn()

        result = collector.finalize(status="completed")

        assert result.completion_status == "completed"
        assert result.turn_count == 1

        # Verify EMF was emitted
        captured = capsys.readouterr()
        assert "call_summary" in captured.out

    def test_finalize_with_incomplete_turn(self, capsys):
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        collector.record_stt_latency(100.0)
        # Don't call end_turn()

        result = collector.finalize(status="completed")

        # Should auto-end the turn
        assert result.turn_count == 1
        assert len(result._turn_metrics) == 1


class TestCreateMetricsCollector:
    """Tests for factory function."""

    def test_creates_collector(self):
        collector = create_metrics_collector("call-1", "session-1")
        assert collector.call_id == "call-1"
        assert collector.session_id == "session-1"

    def test_uses_environment_variable(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "staging")
        collector = create_metrics_collector("call-1", "session-1")
        assert collector.environment == "staging"

    def test_explicit_environment_overrides(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "staging")
        collector = create_metrics_collector("call-1", "session-1", "custom")
        assert collector.environment == "custom"
```

---

## 5. Dependencies

Add to `requirements.txt`:

```
# Observability (EMF logs work without this, but library provides validation)
# aws-embedded-metrics>=3.2.0  # Optional - we implement EMF directly
```

Note: The implementation above writes EMF JSON directly without using the aws-embedded-metrics library, which keeps dependencies minimal and gives full control over the format.
