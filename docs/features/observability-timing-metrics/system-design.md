# System Design: Timing Metrics and CloudWatch EMF Integration

## 1. System Overview

This design adds comprehensive timing metrics to the pipecat voice pipeline with CloudWatch Embedded Metric Format (EMF) integration. Metrics are emitted as structured JSON to stdout, where CloudWatch Logs automatically extracts them as CloudWatch Metrics without requiring a separate agent.

### High-Level Architecture

```
+-------------------+     +--------------------+     +-------------------+
|   Voice Pipeline  |     |   Observability    |     |   CloudWatch      |
|                   |     |      Module        |     |                   |
|  +-------------+  |     |  +-------------+   |     |  +-------------+  |
|  | STT Service |--+---->|  | Metrics     |   |     |  | Logs        |  |
|  +-------------+  |     |  | Collector   |---+---->|  +-------------+  |
|  +-------------+  |     |  +-------------+   |     |         |        |
|  | LLM Service |--+---->|        |          |     |         v        |
|  +-------------+  |     |        v          |     |  +-------------+  |
|  +-------------+  |     |  +-------------+   |     |  | Metrics     |  |
|  | TTS Service |--+---->|  | EMF Logger  |   |     |  | (extracted) |  |
|  +-------------+  |     |  +-------------+   |     |  +-------------+  |
+-------------------+     +--------------------+     +-------------------+
```

### Design Principles

1. **Non-Intrusive**: Timing instrumentation via context managers with minimal code changes
2. **Correlation**: All metrics tied to call_id for distributed tracing
3. **Efficient**: Single EMF log per turn plus call summary (not per-operation)
4. **Observable**: Both individual latencies and aggregates available in CloudWatch

---

## 2. Component Specification

### 2.1 MetricsCollector Class

**File**: `/backend/voice-agent/app/observability.py`

**Responsibility**: Accumulate per-turn and per-call metrics, emit EMF-formatted logs at appropriate boundaries.

```python
@dataclass
class TurnMetrics:
    """Metrics for a single conversation turn."""
    turn_number: int
    stt_latency_ms: Optional[float] = None
    llm_ttfb_ms: Optional[float] = None           # Time to First Byte
    llm_total_ms: Optional[float] = None
    tts_ttfb_ms: Optional[float] = None
    e2e_latency_ms: Optional[float] = None        # VAD stop -> first audio
    user_text: Optional[str] = None               # For conversation logging
    assistant_text: Optional[str] = None


@dataclass
class CallMetrics:
    """Aggregated metrics for a complete call."""
    call_id: str
    session_id: str
    start_time: float                             # monotonic time
    turn_count: int = 0
    total_stt_ms: float = 0.0
    total_llm_ms: float = 0.0
    total_tts_ms: float = 0.0
    completion_status: str = "in_progress"
    error_category: Optional[str] = None


class MetricsCollector:
    """
    Collects timing metrics for voice pipeline operations.

    Thread-safe accumulator that emits EMF logs at turn and call boundaries.
    Integrates with structlog contextvars for call_id correlation.

    Usage:
        collector = MetricsCollector(call_id, session_id, environment)

        # In service methods:
        async with collector.time_stt():
            result = await run_stt(audio)

        # At turn boundary:
        collector.end_turn()

        # At call end:
        collector.finalize(status="completed")
    """
```

### 2.2 Timing Context Managers

**Purpose**: Zero-overhead timing instrumentation that integrates naturally with async code.

```python
class TimingContext:
    """Async context manager for timing operations."""

    def __init__(self, collector: MetricsCollector, metric_name: str):
        self.collector = collector
        self.metric_name = metric_name
        self.start_time: Optional[float] = None
        self.first_byte_time: Optional[float] = None

    async def __aenter__(self):
        self.start_time = time.perf_counter()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = (time.perf_counter() - self.start_time) * 1000
        self.collector.record_metric(self.metric_name, elapsed_ms)
        return False

    def mark_first_byte(self):
        """Call when first response byte arrives (for TTFB metrics)."""
        if self.first_byte_time is None:
            self.first_byte_time = time.perf_counter()
            ttfb_ms = (self.first_byte_time - self.start_time) * 1000
            self.collector.record_metric(f"{self.metric_name}_ttfb", ttfb_ms)
```

### 2.3 EMF Logger

**Purpose**: Format and emit CloudWatch Embedded Metric Format logs.

```python
class EMFLogger:
    """
    Emits CloudWatch Embedded Metric Format (EMF) logs.

    EMF allows publishing metrics via CloudWatch Logs without
    requiring a CloudWatch agent. Logs are JSON with a special
    _aws metadata block that CloudWatch recognizes.

    Format: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Specification.html
    """

    def __init__(
        self,
        namespace: str = "VoiceAgent/Pipeline",
        environment: str = "production"
    ):
        self.namespace = namespace
        self.environment = environment

    def emit_turn_metrics(
        self,
        call_id: str,
        turn_number: int,
        metrics: TurnMetrics,
        dimensions: Optional[Dict[str, str]] = None
    ):
        """Emit EMF log for a conversation turn."""

    def emit_call_summary(
        self,
        metrics: CallMetrics,
        dimensions: Optional[Dict[str, str]] = None
    ):
        """Emit EMF log for call completion."""
```

---

## 3. Interface Specifications

### 3.1 MetricsCollector Public Interface

```python
class MetricsCollector:
    def __init__(
        self,
        call_id: str,
        session_id: str,
        environment: str = "production"
    ) -> None: ...

    # Timing context managers
    def time_stt(self) -> TimingContext: ...
    def time_llm(self) -> TimingContext: ...
    def time_tts(self) -> TimingContext: ...
    def time_e2e(self) -> TimingContext: ...

    # Manual metric recording (for external timers)
    def record_stt_latency(self, latency_ms: float) -> None: ...
    def record_llm_ttfb(self, latency_ms: float) -> None: ...
    def record_llm_total(self, latency_ms: float) -> None: ...
    def record_tts_ttfb(self, latency_ms: float) -> None: ...
    def record_e2e_latency(self, latency_ms: float) -> None: ...

    # Turn boundary
    def start_turn(self) -> None: ...
    def end_turn(self, user_text: str = "", assistant_text: str = "") -> None: ...

    # Call boundary
    def finalize(
        self,
        status: str = "completed",
        error_category: Optional[str] = None
    ) -> CallMetrics: ...

    # Accessors
    @property
    def turn_count(self) -> int: ...
    @property
    def current_turn(self) -> Optional[TurnMetrics]: ...
```

### 3.2 EMF Log Schema

**Turn Metrics EMF Log**:
```json
{
  "_aws": {
    "Timestamp": 1706234400000,
    "CloudWatchMetrics": [{
      "Namespace": "VoiceAgent/Pipeline",
      "Dimensions": [["Environment"], ["Environment", "CallId"]],
      "Metrics": [
        {"Name": "STTLatency", "Unit": "Milliseconds"},
        {"Name": "LLMTimeToFirstByte", "Unit": "Milliseconds"},
        {"Name": "LLMTotalResponseTime", "Unit": "Milliseconds"},
        {"Name": "TTSTimeToFirstByte", "Unit": "Milliseconds"},
        {"Name": "E2ELatency", "Unit": "Milliseconds"}
      ]
    }]
  },
  "Environment": "production",
  "CallId": "550e8400-e29b-41d4-a716-446655440000",
  "TurnNumber": 3,
  "STTLatency": 145.2,
  "LLMTimeToFirstByte": 312.5,
  "LLMTotalResponseTime": 1240.8,
  "TTSTimeToFirstByte": 89.3,
  "E2ELatency": 1475.3,
  "event": "turn_metrics"
}
```

**Call Summary EMF Log**:
```json
{
  "_aws": {
    "Timestamp": 1706234500000,
    "CloudWatchMetrics": [{
      "Namespace": "VoiceAgent/Pipeline",
      "Dimensions": [["Environment"]],
      "Metrics": [
        {"Name": "CallDuration", "Unit": "Seconds"},
        {"Name": "TurnCount", "Unit": "Count"},
        {"Name": "AvgSTTLatency", "Unit": "Milliseconds"},
        {"Name": "AvgLLMLatency", "Unit": "Milliseconds"},
        {"Name": "AvgTTSLatency", "Unit": "Milliseconds"}
      ]
    }]
  },
  "Environment": "production",
  "CallId": "550e8400-e29b-41d4-a716-446655440000",
  "SessionId": "session-123",
  "CallDuration": 45.2,
  "TurnCount": 6,
  "AvgSTTLatency": 142.1,
  "AvgLLMLatency": 1180.5,
  "AvgTTSLatency": 91.2,
  "CompletionStatus": "completed",
  "event": "call_summary"
}
```

---

## 4. Integration Pattern

### 4.1 Service Instrumentation (Minimal Changes)

The design enables instrumentation with minimal code changes by wrapping existing timing points.

**Pattern A: Context Manager Wrapper (Preferred)**

```python
# In pipeline_ecs.py - wrap service creation
def create_instrumented_services(config, collector):
    """Create services with timing instrumentation."""

    # Original services
    stt = DeepgramSTTService(api_key=..., sample_rate=8000)
    llm = AWSBedrockLLMService(model=..., region=...)
    tts = CartesiaTTSService(api_key=..., voice_id=...)

    # Wrap with timing (decorator pattern)
    return InstrumentedSTT(stt, collector), \
           InstrumentedLLM(llm, collector), \
           InstrumentedTTS(tts, collector)
```

**Pattern B: Event-Based (No Service Modification)**

For pipecat's built-in services (Deepgram, Bedrock, Cartesia), use frame event observers:

```python
# In pipeline_ecs.py
@task.on("transcription_complete")
async def on_transcription(frame):
    collector.record_stt_latency(frame.processing_time_ms)

@task.on("llm_first_token")
async def on_llm_first_token(frame):
    collector.mark_llm_ttfb()

@task.on("tts_audio_start")
async def on_tts_start(frame):
    collector.mark_tts_ttfb()
```

### 4.2 Integration Points

```
+------------------+                    +-------------------+
|  service_main.py |                    |  pipeline_ecs.py  |
+------------------+                    +-------------------+
         |                                       |
         | 1. Create MetricsCollector            |
         |    with call_id, session_id           |
         |                                       |
         +-------------------------------------->|
         |                                       |
         |                              2. Pass collector to
         |                                 create_voice_pipeline()
         |                                       |
         |                              3. Register frame observers
         |                                 for timing events
         |                                       |
         |                              4. On each turn boundary:
         |                                 collector.end_turn()
         |                                       |
         +<--------------------------------------+
         |                                       |
         | 5. On call end:                       |
         |    collector.finalize()               |
         |                                       |
```

### 4.3 File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `backend/voice-agent/app/observability.py` | **NEW** | MetricsCollector, EMFLogger, timing utilities |
| `backend/voice-agent/app/service_main.py` | Modify | Create collector, pass to pipeline, finalize |
| `backend/voice-agent/app/pipeline_ecs.py` | Modify | Accept collector, register frame observers |
| `backend/voice-agent/requirements.txt` | Modify | Add `aws-embedded-metrics` package |

---

## 5. Data Flow

### 5.1 Per-Turn Metrics Flow

```
                        Turn Start (VAD Stop)
                              |
                              v
+------------------+    +-----------+    +------------------+
|  Audio Frames    |--->|    STT    |--->| TranscriptionFrame|
|                  |    +-----------+    +------------------+
|  collector.      |          |                   |
|  time_e2e().__   |    record_stt_              |
|  aenter__()      |    latency()                 v
+------------------+                      +-------------+
                                          |     LLM     |
                                          +-------------+
                                                |
                              mark_llm_ttfb()   | (first token)
                                          |    |
                                          v    v
                                    +-------------+
                                    |     TTS     |
                                    +-------------+
                                          |
                              mark_tts_ttfb()   | (first audio)
                                          |    |
                                          v    v
                                  +------------------+
                                  | AudioRawFrame    |
                                  | (to transport)   |
                                  +------------------+
                                          |
                              collector.time_e2e().
                              __aexit__()
                                          |
                                          v
                                  collector.end_turn()
                                          |
                                          v
                                  EMF log emitted
```

### 5.2 Call Summary Flow

```
                    Call Start
                        |
                        v
               +----------------+
               | Initialize     |
               | MetricsCollector|
               +----------------+
                        |
          +-------------+-------------+
          |             |             |
          v             v             v
      Turn 1        Turn 2    ...  Turn N
          |             |             |
          v             v             v
     end_turn()    end_turn()    end_turn()
          |             |             |
          v             v             v
    EMF (turn)     EMF (turn)    EMF (turn)
          |             |             |
          +-------------+-------------+
                        |
                        v
                Call End / Error
                        |
                        v
               collector.finalize()
                        |
                        v
               EMF (call_summary)
                        |
                        v
               CloudWatch Logs
                        |
                        v
               CloudWatch Metrics
               (auto-extracted)
```

---

## 6. CloudWatch Integration

### 6.1 Metric Extraction

CloudWatch automatically extracts metrics from EMF logs when:
1. Logs are sent to CloudWatch Logs
2. Log format matches EMF specification
3. `_aws` metadata block contains valid metric definitions

**No agent required** - ECS Fargate sends stdout to CloudWatch Logs via awslogs driver.

### 6.2 Metrics Namespace and Dimensions

```
Namespace: VoiceAgent/Pipeline

Dimensions:
  - Environment (primary): "production", "staging", "development"
  - CallId (high-cardinality, secondary): For per-call drill-down

Metrics:
  STTLatency (ms)           - P50, P90, P99
  LLMTimeToFirstByte (ms)   - Critical for perceived latency
  LLMTotalResponseTime (ms) - Total LLM processing
  TTSTimeToFirstByte (ms)   - P50, P90, P99
  E2ELatency (ms)           - VAD stop to first audio
  CallDuration (seconds)    - For billing/usage
  TurnCount (count)         - Conversation complexity
```

### 6.3 CloudWatch Alarms (Recommendations)

| Alarm | Threshold | Period | Datapoints |
|-------|-----------|--------|------------|
| HighE2ELatency | P90 > 2000ms | 5 min | 2/3 |
| HighSTTLatency | P90 > 500ms | 5 min | 2/3 |
| HighLLMTTFB | P90 > 1000ms | 5 min | 2/3 |
| LowTurnCount | Avg < 1 | 15 min | 3/3 |

### 6.4 CloudWatch Logs Insights Queries

**Latency by Turn**:
```sql
filter event = "turn_metrics"
| stats avg(E2ELatency) as avg_e2e,
        pct(E2ELatency, 90) as p90_e2e,
        pct(E2ELatency, 99) as p99_e2e
  by bin(5m)
```

**Slow Calls Investigation**:
```sql
filter event = "call_summary" and CallDuration > 60
| fields CallId, TurnCount, CompletionStatus, AvgLLMLatency
| sort CallDuration desc
| limit 20
```

**Error Rate by Category**:
```sql
filter event = "call_summary" and CompletionStatus = "error"
| stats count() as errors by ErrorCategory
| sort errors desc
```

---

## 7. Implementation Sequence

### Phase 1: Core Module
1. Create `observability.py` with MetricsCollector, TurnMetrics, CallMetrics
2. Implement TimingContext context managers
3. Implement EMFLogger with proper EMF JSON formatting
4. Unit tests for metric accumulation and EMF output

### Phase 2: Service Integration
1. Modify `service_main.py` to create MetricsCollector
2. Modify `pipeline_ecs.py` to accept collector parameter
3. Add frame observers for pipecat's built-in metrics events
4. Wire up end_turn() calls at turn boundaries

### Phase 3: Testing and Validation
1. Integration tests with mock CloudWatch
2. Load testing to verify metric accuracy under concurrency
3. Validate EMF logs parse correctly in CloudWatch

### Phase 4: Dashboards and Alarms
1. Create CloudWatch dashboard with key metrics
2. Set up alarms for latency thresholds
3. Document operational runbooks

---

## 8. Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| EMF format errors cause metric loss | Medium | Medium | Validate EMF output in tests; use aws-embedded-metrics library |
| High-cardinality dimensions (CallId) cause cost spikes | Medium | High | Use CallId only as secondary dimension; monitor metrics cost |
| Timing instrumentation adds latency | Low | High | Use perf_counter(); measure overhead in benchmarks |
| Missing turn boundaries | Medium | Medium | Default to emitting metrics on call end if turn detection fails |
| Concurrent access to collector | Low | High | Use asyncio locks; collector is per-call (not shared) |

---

## 9. Dependencies

### Python Packages

```
# Add to requirements.txt
aws-embedded-metrics>=3.2.0
```

The `aws-embedded-metrics` library provides:
- Proper EMF JSON formatting
- Dimension management
- Unit handling
- Async support

### Infrastructure

No infrastructure changes required. ECS Fargate already sends logs to CloudWatch.

---

## 10. Appendix: EMF Format Reference

### Minimal EMF Log Structure

```json
{
  "_aws": {
    "Timestamp": 1706234400000,
    "CloudWatchMetrics": [{
      "Namespace": "MyNamespace",
      "Dimensions": [["Dimension1"]],
      "Metrics": [
        {"Name": "MetricName", "Unit": "Milliseconds"}
      ]
    }]
  },
  "Dimension1": "value1",
  "MetricName": 123.45
}
```

### Key Rules

1. `Timestamp` must be Unix epoch milliseconds
2. Each metric must appear in both `Metrics` array and as a top-level property
3. Each dimension must appear in `Dimensions` array and as a top-level property
4. `Unit` must be a valid CloudWatch unit: Count, Seconds, Milliseconds, etc.
5. Dimension combinations create separate metric streams (cost implications)
