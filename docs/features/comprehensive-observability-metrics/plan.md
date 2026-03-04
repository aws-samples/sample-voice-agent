---
started: 2026-02-06
---

# Implementation Plan: Comprehensive Observability Metrics

## Overview

This plan implements comprehensive observability metrics to address gaps in our current monitoring system. The implementation expands beyond basic latency tracking to include quality signals, network metrics, conversation flow analysis, and a composite quality score for quick call assessment.

## Architecture Summary

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ Frame Observers │───▶│ Enhanced Metrics │───▶│ CloudWatch EMF  │
│ (Non-blocking)  │    │ Collectors       │    │ (Real-time)     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ STT Confidence  │    │ LLM Token Counts │    │ WebRTC Metrics  │
│ Flow Analysis   │    │ Network Quality  │    │ Quality Score   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Enhanced Dashboard                           │
│  AgentResponseLatency | STTConfidence | LLMTokens | QualityScore │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Steps

### Phase 1: Metric Renaming and Foundation

#### Step 1: Rename E2E Latency to AgentResponseLatency
**Files**: `backend/voice-agent/app/observability.py`, `infrastructure/src/constructs/voice-agent-monitoring-construct.ts`

**Changes**:
- Update `EMFLogger.emit_turn_metrics()` to emit "AgentResponseLatency" instead of "E2ELatency"
- Update CloudWatch dashboard metric references
- Update alarm configurations
- Maintain backward compatibility during transition period

**Implementation**:
```python
# In observability.py - EMFLogger.emit_turn_metrics()
if turn.e2e_latency_ms is not None:
    metrics_list.append({"Name": "AgentResponseLatency", "Unit": "Milliseconds"})
    metric_values["AgentResponseLatency"] = round(turn.e2e_latency_ms, 1)
    
    # Backward compatibility - emit both for transition period
    metrics_list.append({"Name": "E2ELatency", "Unit": "Milliseconds"})
    metric_values["E2ELatency"] = round(turn.e2e_latency_ms, 1)
```

#### Step 2: Add STT Quality Metrics Collection
**Files**: `backend/voice-agent/app/observability.py`

**New Classes**:
- `STTQualityObserver` - Captures Deepgram confidence scores and transcription patterns
- Enhanced `TurnMetrics` with STT quality fields

**Implementation**:
```python
@dataclass
class TurnMetrics:
    # ... existing fields ...
    
    # STT Quality metrics
    stt_confidence_avg: Optional[float] = None
    stt_confidence_min: Optional[float] = None
    stt_interim_count: int = 0
    stt_final_count: int = 0
    stt_word_count: Optional[int] = None

class STTQualityObserver(BaseObserver):
    """Observes STT frames to collect quality metrics."""
    
    def __init__(self, collector: MetricsCollector, enabled: bool = True):
        super().__init__()
        self._collector = collector
        self._enabled = enabled
        self._confidence_scores: List[float] = []
        self._interim_count = 0
        self._final_count = 0
    
    async def on_push_frame(self, data: FramePushed):
        if not self._enabled:
            return
            
        frame = data.frame
        
        if isinstance(frame, TranscriptionFrame):
            # Extract confidence from Deepgram metadata
            if hasattr(frame, 'confidence') and frame.confidence is not None:
                self._confidence_scores.append(frame.confidence)
            
            # Track interim vs final transcriptions
            if hasattr(frame, 'is_final') and frame.is_final:
                self._final_count += 1
                self._record_stt_metrics(frame)
            else:
                self._interim_count += 1
    
    def _record_stt_metrics(self, frame: TranscriptionFrame):
        """Record STT quality metrics when final transcription received."""
        if not self._confidence_scores:
            return
            
        avg_confidence = sum(self._confidence_scores) / len(self._confidence_scores)
        min_confidence = min(self._confidence_scores)
        word_count = len(frame.text.split()) if frame.text else 0
        
        self._collector.record_stt_quality(
            confidence_avg=avg_confidence,
            confidence_min=min_confidence,
            interim_count=self._interim_count,
            final_count=self._final_count,
            word_count=word_count
        )
        
        # Reset for next turn
        self._confidence_scores = []
        self._interim_count = 0
        self._final_count = 0
```

#### Step 3: Add LLM Quality Metrics Collection
**Files**: `backend/voice-agent/app/observability.py`

**Enhanced Classes**:
- `TurnMetrics` with LLM token fields
- `MetricsCollector` with LLM quality recording methods

**Implementation**:
```python
@dataclass
class TurnMetrics:
    # ... existing fields ...
    
    # LLM Quality metrics
    llm_input_tokens: Optional[int] = None
    llm_output_tokens: Optional[int] = None
    llm_tokens_per_second: Optional[float] = None
    llm_prompt_cached: Optional[bool] = None

class LLMQualityObserver(BaseObserver):
    """Observes LLM frames to collect token usage and generation metrics."""
    
    def __init__(self, collector: MetricsCollector, enabled: bool = True):
        super().__init__()
        self._collector = collector
        self._enabled = enabled
        self._response_start_time: Optional[float] = None
        self._token_count = 0
    
    async def on_push_frame(self, data: FramePushed):
        if not self._enabled:
            return
            
        frame = data.frame
        source = data.source
        
        # Only process frames from LLM service
        if not isinstance(source, LLMService):
            return
            
        if isinstance(frame, LLMFullResponseStartFrame):
            self._response_start_time = time.perf_counter()
            self._token_count = 0
            
        elif isinstance(frame, TextFrame) and self._response_start_time:
            # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
            if frame.text:
                estimated_tokens = len(frame.text) / 4
                self._token_count += estimated_tokens
                
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._response_start_time and self._token_count > 0:
                duration_sec = time.perf_counter() - self._response_start_time
                tokens_per_sec = self._token_count / duration_sec if duration_sec > 0 else 0
                
                self._collector.record_llm_quality(
                    output_tokens=int(self._token_count),
                    tokens_per_second=tokens_per_sec
                )
            
            self._response_start_time = None
            self._token_count = 0
```

### Phase 2: Network and WebRTC Metrics

#### Step 4: Add WebRTC Quality Metrics
**Files**: `backend/voice-agent/app/observability.py`, `backend/voice-agent/app/pipeline_ecs.py`

**New Classes**:
- `WebRTCQualityObserver` - Captures network quality from Daily transport

**Implementation**:
```python
@dataclass
class TurnMetrics:
    # ... existing fields ...
    
    # Network Quality metrics
    webrtc_rtt_ms: Optional[float] = None
    webrtc_jitter_ms: Optional[float] = None
    webrtc_packet_loss_percent: Optional[float] = None
    webrtc_bitrate_kbps: Optional[float] = None

class WebRTCQualityObserver(BaseObserver):
    """Observes WebRTC quality metrics from Daily transport."""
    
    def __init__(self, collector: MetricsCollector, transport: DailyTransport, enabled: bool = True):
        super().__init__()
        self._collector = collector
        self._transport = transport
        self._enabled = enabled
        self._last_stats_time = 0
        
    async def on_push_frame(self, data: FramePushed):
        if not self._enabled:
            return
            
        # Sample WebRTC stats periodically (every 5 seconds)
        current_time = time.time()
        if current_time - self._last_stats_time > 5.0:
            await self._collect_webrtc_stats()
            self._last_stats_time = current_time
    
    async def _collect_webrtc_stats(self):
        """Collect WebRTC statistics from Daily transport."""
        try:
            # Get stats from Daily transport (implementation depends on Daily API)
            stats = await self._transport.get_network_stats()
            
            if stats:
                self._collector.record_webrtc_quality(
                    rtt_ms=stats.get('rtt_ms'),
                    jitter_ms=stats.get('jitter_ms'),
                    packet_loss_percent=stats.get('packet_loss_percent'),
                    bitrate_kbps=stats.get('bitrate_kbps')
                )
        except Exception as e:
            logger.debug("webrtc_stats_collection_error", error=str(e))
```

### Phase 3: Conversation Flow Analysis

#### Step 5: Add Conversation Flow Metrics
**Files**: `backend/voice-agent/app/observability.py`

**Enhanced Classes**:
- `ConversationFlowObserver` - Analyzes turn-taking patterns and conversation quality

**Implementation**:
```python
@dataclass
class TurnMetrics:
    # ... existing fields ...
    
    # Conversation Flow metrics
    turn_gap_ms: Optional[float] = None
    speaking_duration_ms: Optional[float] = None
    response_delay_ms: Optional[float] = None
    was_abandoned: bool = False

@dataclass
class CallMetrics:
    # ... existing fields ...
    
    # Flow aggregates
    abandoned_turns: int = 0
    avg_turn_gap_ms: float = 0.0
    user_speaking_ratio: float = 0.0  # Percentage of time user was speaking

class ConversationFlowObserver(BaseObserver):
    """Analyzes conversation flow patterns and turn-taking quality."""
    
    def __init__(self, collector: MetricsCollector, enabled: bool = True):
        super().__init__()
        self._collector = collector
        self._enabled = enabled
        
        # State tracking
        self._last_user_stop_time: Optional[float] = None
        self._last_bot_stop_time: Optional[float] = None
        self._user_speaking_start: Optional[float] = None
        self._bot_speaking_start: Optional[float] = None
        
        # Timing accumulators
        self._total_user_speaking_time = 0.0
        self._total_bot_speaking_time = 0.0
        self._turn_gaps: List[float] = []
    
    async def on_push_frame(self, data: FramePushed):
        if not self._enabled:
            return
            
        frame = data.frame
        current_time = time.perf_counter()
        
        if isinstance(frame, UserStartedSpeakingFrame):
            self._user_speaking_start = current_time
            
            # Calculate gap since last bot stopped speaking
            if self._last_bot_stop_time:
                gap_ms = (current_time - self._last_bot_stop_time) * 1000
                self._turn_gaps.append(gap_ms)
                self._collector.record_turn_gap(gap_ms)
                
        elif isinstance(frame, UserStoppedSpeakingFrame):
            if self._user_speaking_start:
                speaking_duration = (current_time - self._user_speaking_start) * 1000
                self._total_user_speaking_time += speaking_duration / 1000
                self._collector.record_speaking_duration(speaking_duration)
                
            self._last_user_stop_time = current_time
            self._user_speaking_start = None
            
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking_start = current_time
            
            # Calculate response delay since user stopped
            if self._last_user_stop_time:
                delay_ms = (current_time - self._last_user_stop_time) * 1000
                self._collector.record_response_delay(delay_ms)
                
        elif isinstance(frame, BotStoppedSpeakingFrame):
            if self._bot_speaking_start:
                speaking_duration = (current_time - self._bot_speaking_start) * 1000
                self._total_bot_speaking_time += speaking_duration / 1000
                
            self._last_bot_stop_time = current_time
            self._bot_speaking_start = None
    
    def finalize_call_metrics(self, call_duration_sec: float):
        """Calculate final conversation flow metrics."""
        total_speaking_time = self._total_user_speaking_time + self._total_bot_speaking_time
        
        if total_speaking_time > 0:
            user_ratio = self._total_user_speaking_time / total_speaking_time
            self._collector.record_speaking_ratio(user_ratio)
        
        if self._turn_gaps:
            avg_gap = sum(self._turn_gaps) / len(self._turn_gaps)
            self._collector.record_avg_turn_gap(avg_gap)
```

### Phase 4: Composite Quality Score

#### Step 6: Implement Quality Score Calculation
**Files**: `backend/voice-agent/app/observability.py`

**New Classes**:
- `QualityScoreCalculator` - Computes weighted quality score

**Implementation**:
```python
@dataclass
class TurnMetrics:
    # ... existing fields ...
    
    # Composite Quality
    quality_score: Optional[float] = None  # 0.0 to 1.0

@dataclass
class CallMetrics:
    # ... existing fields ...
    
    # Quality aggregates
    avg_quality_score: float = 0.0
    quality_issues: List[str] = field(default_factory=list)

class QualityScoreCalculator:
    """Calculates composite quality scores for turns and calls."""
    
    # Weights for different quality factors (must sum to 1.0)
    WEIGHTS = {
        'latency': 0.3,      # Agent response latency
        'audio': 0.2,        # Audio RMS quality
        'stt_confidence': 0.2,  # STT confidence
        'flow': 0.15,        # Conversation flow smoothness
        'network': 0.15      # WebRTC quality
    }
    
    # Thresholds for quality scoring
    THRESHOLDS = {
        'excellent_latency_ms': 800,
        'poor_latency_ms': 2000,
        'excellent_audio_db': -30,
        'poor_audio_db': -55,
        'excellent_confidence': 0.9,
        'poor_confidence': 0.6,
        'excellent_gap_ms': 500,
        'poor_gap_ms': 2000,
        'excellent_rtt_ms': 50,
        'poor_rtt_ms': 200
    }
    
    @classmethod
    def calculate_turn_quality(cls, turn: TurnMetrics) -> float:
        """Calculate quality score for a single turn (0.0 to 1.0)."""
        scores = {}
        
        # Latency score (0.0 = poor, 1.0 = excellent)
        if turn.e2e_latency_ms is not None:
            scores['latency'] = cls._score_latency(turn.e2e_latency_ms)
        
        # Audio quality score
        if turn.audio_rms_db is not None:
            scores['audio'] = cls._score_audio_quality(turn.audio_rms_db)
        
        # STT confidence score
        if turn.stt_confidence_avg is not None:
            scores['stt_confidence'] = cls._score_stt_confidence(turn.stt_confidence_avg)
        
        # Flow score (turn gap)
        if turn.turn_gap_ms is not None:
            scores['flow'] = cls._score_turn_gap(turn.turn_gap_ms)
        
        # Network score
        if turn.webrtc_rtt_ms is not None:
            scores['network'] = cls._score_network_quality(turn.webrtc_rtt_ms)
        
        # Calculate weighted average of available scores
        if not scores:
            return 0.5  # Neutral score if no data
        
        total_weight = sum(cls.WEIGHTS[key] for key in scores.keys())
        weighted_sum = sum(scores[key] * cls.WEIGHTS[key] for key in scores.keys())
        
        return weighted_sum / total_weight if total_weight > 0 else 0.5
    
    @classmethod
    def _score_latency(cls, latency_ms: float) -> float:
        """Score latency from 0.0 (poor) to 1.0 (excellent)."""
        if latency_ms <= cls.THRESHOLDS['excellent_latency_ms']:
            return 1.0
        elif latency_ms >= cls.THRESHOLDS['poor_latency_ms']:
            return 0.0
        else:
            # Linear interpolation between excellent and poor
            range_ms = cls.THRESHOLDS['poor_latency_ms'] - cls.THRESHOLDS['excellent_latency_ms']
            offset_ms = latency_ms - cls.THRESHOLDS['excellent_latency_ms']
            return 1.0 - (offset_ms / range_ms)
    
    @classmethod
    def _score_audio_quality(cls, rms_db: float) -> float:
        """Score audio quality from 0.0 (poor) to 1.0 (excellent)."""
        if rms_db >= cls.THRESHOLDS['excellent_audio_db']:
            return 1.0
        elif rms_db <= cls.THRESHOLDS['poor_audio_db']:
            return 0.0
        else:
            range_db = cls.THRESHOLDS['excellent_audio_db'] - cls.THRESHOLDS['poor_audio_db']
            offset_db = rms_db - cls.THRESHOLDS['poor_audio_db']
            return offset_db / range_db
    
    @classmethod
    def _score_stt_confidence(cls, confidence: float) -> float:
        """Score STT confidence from 0.0 (poor) to 1.0 (excellent)."""
        if confidence >= cls.THRESHOLDS['excellent_confidence']:
            return 1.0
        elif confidence <= cls.THRESHOLDS['poor_confidence']:
            return 0.0
        else:
            range_conf = cls.THRESHOLDS['excellent_confidence'] - cls.THRESHOLDS['poor_confidence']
            offset_conf = confidence - cls.THRESHOLDS['poor_confidence']
            return offset_conf / range_conf
    
    @classmethod
    def _score_turn_gap(cls, gap_ms: float) -> float:
        """Score turn gap from 0.0 (poor) to 1.0 (excellent)."""
        if gap_ms <= cls.THRESHOLDS['excellent_gap_ms']:
            return 1.0
        elif gap_ms >= cls.THRESHOLDS['poor_gap_ms']:
            return 0.0
        else:
            range_ms = cls.THRESHOLDS['poor_gap_ms'] - cls.THRESHOLDS['excellent_gap_ms']
            offset_ms = gap_ms - cls.THRESHOLDS['excellent_gap_ms']
            return 1.0 - (offset_ms / range_ms)
    
    @classmethod
    def _score_network_quality(cls, rtt_ms: float) -> float:
        """Score network quality from 0.0 (poor) to 1.0 (excellent)."""
        if rtt_ms <= cls.THRESHOLDS['excellent_rtt_ms']:
            return 1.0
        elif rtt_ms >= cls.THRESHOLDS['poor_rtt_ms']:
            return 0.0
        else:
            range_ms = cls.THRESHOLDS['poor_rtt_ms'] - cls.THRESHOLDS['excellent_rtt_ms']
            offset_ms = rtt_ms - cls.THRESHOLDS['excellent_rtt_ms']
            return 1.0 - (offset_ms / range_ms)
```

### Phase 5: Enhanced EMF Logging and Dashboard

#### Step 7: Update EMF Logging for New Metrics
**Files**: `backend/voice-agent/app/observability.py`

**Enhanced Methods**:
- `EMFLogger.emit_turn_metrics()` - Add new metric types
- `EMFLogger.emit_call_summary()` - Add quality aggregates

**Implementation**:
```python
def emit_turn_metrics(self, call_id: str, turn: TurnMetrics) -> None:
    """Emit EMF log for turn metrics with enhanced quality data."""
    metrics_list = []
    metric_values = {}
    
    # Existing metrics (renamed)
    if turn.e2e_latency_ms is not None:
        metrics_list.append({"Name": "AgentResponseLatency", "Unit": "Milliseconds"})
        metric_values["AgentResponseLatency"] = round(turn.e2e_latency_ms, 1)
    
    # STT Quality metrics
    if turn.stt_confidence_avg is not None:
        metrics_list.append({"Name": "STTConfidenceAvg", "Unit": "None"})
        metric_values["STTConfidenceAvg"] = round(turn.stt_confidence_avg, 3)
    
    if turn.stt_confidence_min is not None:
        metrics_list.append({"Name": "STTConfidenceMin", "Unit": "None"})
        metric_values["STTConfidenceMin"] = round(turn.stt_confidence_min, 3)
    
    if turn.stt_word_count is not None:
        metrics_list.append({"Name": "STTWordCount", "Unit": "Count"})
        metric_values["STTWordCount"] = turn.stt_word_count
    
    # LLM Quality metrics
    if turn.llm_output_tokens is not None:
        metrics_list.append({"Name": "LLMOutputTokens", "Unit": "Count"})
        metric_values["LLMOutputTokens"] = turn.llm_output_tokens
    
    if turn.llm_tokens_per_second is not None:
        metrics_list.append({"Name": "LLMTokensPerSecond", "Unit": "Count/Second"})
        metric_values["LLMTokensPerSecond"] = round(turn.llm_tokens_per_second, 1)
    
    # WebRTC Quality metrics
    if turn.webrtc_rtt_ms is not None:
        metrics_list.append({"Name": "WebRTCRTT", "Unit": "Milliseconds"})
        metric_values["WebRTCRTT"] = round(turn.webrtc_rtt_ms, 1)
    
    if turn.webrtc_jitter_ms is not None:
        metrics_list.append({"Name": "WebRTCJitter", "Unit": "Milliseconds"})
        metric_values["WebRTCJitter"] = round(turn.webrtc_jitter_ms, 1)
    
    if turn.webrtc_packet_loss_percent is not None:
        metrics_list.append({"Name": "WebRTCPacketLoss", "Unit": "Percent"})
        metric_values["WebRTCPacketLoss"] = round(turn.webrtc_packet_loss_percent, 2)
    
    # Flow metrics
    if turn.turn_gap_ms is not None:
        metrics_list.append({"Name": "TurnGap", "Unit": "Milliseconds"})
        metric_values["TurnGap"] = round(turn.turn_gap_ms, 1)
    
    if turn.response_delay_ms is not None:
        metrics_list.append({"Name": "ResponseDelay", "Unit": "Milliseconds"})
        metric_values["ResponseDelay"] = round(turn.response_delay_ms, 1)
    
    # Composite Quality Score
    if turn.quality_score is not None:
        metrics_list.append({"Name": "QualityScore", "Unit": "None"})
        metric_values["QualityScore"] = round(turn.quality_score, 3)
    
    # ... rest of existing EMF emission logic
```

#### Step 8: Update CloudWatch Dashboard and Alarms
**Files**: `infrastructure/src/constructs/voice-agent-monitoring-construct.ts`

**New Dashboard Widgets**:
- STT Quality panel (confidence scores, word counts)
- LLM Performance panel (token counts, generation speed)
- WebRTC Quality panel (RTT, jitter, packet loss)
- Conversation Flow panel (turn gaps, response delays)
- Quality Score panel (composite score trends)

**New Alarms**:
- Low STT confidence alarm (avg < 0.7)
- High WebRTC latency alarm (RTT > 200ms)
- Poor quality score alarm (avg < 0.6)

**Implementation**:
```typescript
// Add to createDashboard method
// Row 6: Quality Metrics
dashboard.addWidgets(
  // STT Quality
  new cloudwatch.GraphWidget({
    title: 'STT Quality',
    left: [
      new cloudwatch.Metric({
        namespace: 'VoiceAgent/Pipeline',
        metricName: 'STTConfidenceAvg',
        dimensionsMap: { Environment: props.environment },
        statistic: 'Average',
        period: cdk.Duration.minutes(1),
        label: 'Avg Confidence',
      }),
      new cloudwatch.Metric({
        namespace: 'VoiceAgent/Pipeline',
        metricName: 'STTConfidenceMin',
        dimensionsMap: { Environment: props.environment },
        statistic: 'Average',
        period: cdk.Duration.minutes(1),
        label: 'Min Confidence',
      }),
    ],
    leftYAxis: { min: 0, max: 1, label: 'Confidence Score' },
    leftAnnotations: [
      { value: 0.7, color: '#ff9900', label: 'Warning Threshold' },
      { value: 0.9, color: '#2ca02c', label: 'Good Threshold' },
    ],
    width: 12,
    height: 6,
  }),
  
  // Quality Score
  new cloudwatch.GraphWidget({
    title: 'Composite Quality Score',
    left: [
      new cloudwatch.Metric({
        namespace: 'VoiceAgent/Pipeline',
        metricName: 'QualityScore',
        dimensionsMap: { Environment: props.environment },
        statistic: 'Average',
        period: cdk.Duration.minutes(1),
        label: 'Quality Score',
      }),
    ],
    leftYAxis: { min: 0, max: 1, label: 'Quality Score (0-1)' },
    leftAnnotations: [
      { value: 0.6, color: '#ff0000', label: 'Poor Quality' },
      { value: 0.8, color: '#ff9900', label: 'Good Quality' },
      { value: 0.9, color: '#2ca02c', label: 'Excellent Quality' },
    ],
    width: 12,
    height: 6,
  })
);

// Add quality-based alarms
const lowQualityAlarm = new cloudwatch.Alarm(this, 'LowQualityAlarm', {
  alarmName: `${resourcePrefix}-quality-score-low`,
  alarmDescription: 'Composite quality score below 0.6 - investigate call quality issues',
  metric: new cloudwatch.Metric({
    namespace: 'VoiceAgent/Pipeline',
    metricName: 'QualityScore',
    dimensionsMap: { Environment: props.environment },
    statistic: 'Average',
    period: cdk.Duration.minutes(5),
  }),
  threshold: 0.6,
  evaluationPeriods: 3,
  datapointsToAlarm: 2,
  comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
  treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
});
```

### Phase 6: Integration and Testing

#### Step 9: Update Pipeline Integration
**Files**: `backend/voice-agent/app/pipeline_ecs.py`

**Changes**:
- Add new observers to pipeline
- Configure observer enablement via environment variables

**Implementation**:
```python
# In create_voice_pipeline function
observers = []
if collector:
    from app.observability import (
        MetricsObserver,
        ConversationObserver,
        AudioQualityObserver,
        STTQualityObserver,
        LLMQualityObserver,
        WebRTCQualityObserver,
        ConversationFlowObserver,
    )
    
    # Core metrics observer
    observers.append(MetricsObserver(collector))
    
    # Enhanced quality observers
    if _get_enable_audio_quality():
        observers.append(AudioQualityObserver(collector, enabled=True))
    
    # New quality observers
    observers.append(STTQualityObserver(collector, enabled=True))
    observers.append(LLMQualityObserver(collector, enabled=True))
    observers.append(WebRTCQualityObserver(collector, transport, enabled=True))
    observers.append(ConversationFlowObserver(collector, enabled=True))
    
    # Conversation logging (if enabled)
    if _get_enable_conversation_logging():
        observers.append(ConversationObserver(collector, enabled=True))
```

#### Step 10: Add Comprehensive Testing
**Files**: `backend/voice-agent/tests/test_observability_enhanced.py`

**Test Coverage**:
- STT quality metric collection and aggregation
- LLM token counting and speed calculation
- WebRTC quality metric extraction
- Conversation flow analysis
- Quality score calculation with various scenarios
- EMF logging for all new metrics

**Implementation**:
```python
class TestSTTQualityObserver:
    """Tests for STT quality metrics collection."""
    
    @pytest.mark.asyncio
    async def test_confidence_score_aggregation(self):
        """Test STT confidence scores are properly aggregated."""
        collector = MetricsCollector("call-1", "session-1", "test")
        collector.start_turn()
        observer = STTQualityObserver(collector, enabled=True)
        
        # Simulate transcription frames with confidence scores
        frames = [
            TranscriptionFrame(text="Hello", confidence=0.95, is_final=False),
            TranscriptionFrame(text="Hello there", confidence=0.92, is_final=False),
            TranscriptionFrame(text="Hello there!", confidence=0.88, is_final=True),
        ]
        
        for frame in frames:
            await observer.on_push_frame(self._make_frame_pushed(frame))
        
        turn = collector.current_turn
        assert turn.stt_confidence_avg == pytest.approx(0.917, abs=0.01)
        assert turn.stt_confidence_min == 0.88
        assert turn.stt_interim_count == 2
        assert turn.stt_final_count == 1

class TestQualityScoreCalculator:
    """Tests for composite quality score calculation."""
    
    def test_excellent_quality_score(self):
        """Test quality score calculation for excellent metrics."""
        turn = TurnMetrics(
            turn_number=1,
            e2e_latency_ms=500,  # Excellent
            audio_rms_db=-25,    # Excellent
            stt_confidence_avg=0.95,  # Excellent
            turn_gap_ms=300,     # Excellent
            webrtc_rtt_ms=30     # Excellent
        )
        
        score = QualityScoreCalculator.calculate_turn_quality(turn)
        assert score >= 0.9  # Should be excellent
    
    def test_poor_quality_score(self):
        """Test quality score calculation for poor metrics."""
        turn = TurnMetrics(
            turn_number=1,
            e2e_latency_ms=3000,  # Poor
            audio_rms_db=-60,     # Poor
            stt_confidence_avg=0.5,   # Poor
            turn_gap_ms=3000,     # Poor
            webrtc_rtt_ms=300     # Poor
        )
        
        score = QualityScoreCalculator.calculate_turn_quality(turn)
        assert score <= 0.3  # Should be poor
```

## Technical Decisions

### 1. Backward Compatibility for Metric Renaming
During the transition period, emit both "E2ELatency" and "AgentResponseLatency" to avoid breaking existing dashboards and alarms. Remove the old metric after confirming all consumers have migrated.

### 2. Observer-Based Architecture
Continue using Pipecat's observer pattern for non-intrusive metrics collection. Observers run in separate async tasks and cannot block the pipeline, ensuring performance is not impacted.

### 3. Weighted Quality Score
Use a configurable weighted scoring system that can be tuned based on operational experience. Initial weights prioritize latency and audio quality as most impactful to user experience.

### 4. Gradual Rollout Strategy
Implement new metrics behind feature flags to enable gradual rollout and easy rollback if issues are discovered.

## Testing Strategy

### Unit Tests
- `test_stt_quality_observer.py`: STT confidence aggregation, interim/final counting
- `test_llm_quality_observer.py`: Token counting, generation speed calculation
- `test_webrtc_quality_observer.py`: Network metrics collection and validation
- `test_conversation_flow_observer.py`: Turn gap analysis, speaking time ratios
- `test_quality_score_calculator.py`: Score calculation with various input scenarios
- `test_enhanced_emf_logging.py`: EMF format validation for new metrics

### Integration Tests
- `test_enhanced_pipeline_observability.py`: End-to-end with all observers enabled
- `test_quality_score_integration.py`: Quality score calculation in real pipeline context

### Performance Tests
- Verify observer overhead is minimal (<1% CPU impact)
- Confirm EMF log volume is manageable
- Test with high call volume scenarios

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Observer performance overhead | Medium - pipeline slowdown | Comprehensive performance testing; feature flags for quick disable |
| EMF log volume increase | Medium - higher CloudWatch costs | Implement sampling for high-volume metrics; monitor costs |
| WebRTC API availability | High - missing network metrics | Graceful degradation; mock data for testing |
| Quality score accuracy | Medium - misleading scores | Extensive testing with real call data; tunable weights |
| Dashboard complexity | Low - user confusion | Clear metric definitions; progressive disclosure |

## Dependencies

- **Pipecat v0.0.100+**: Observer pattern support
- **Daily Transport API**: WebRTC statistics access
- **Deepgram API**: Confidence score metadata
- **AWS CloudWatch**: EMF log processing and dashboard updates

## File Structure

```
backend/voice-agent/app/
├── observability.py              # Enhanced with new observers and metrics
└── pipeline_ecs.py               # Updated observer registration

backend/voice-agent/tests/
├── test_observability_enhanced.py # New comprehensive tests
└── test_quality_score.py         # Quality calculation tests

infrastructure/src/constructs/
└── voice-agent-monitoring-construct.ts # Enhanced dashboard and alarms

docs/features/comprehensive-observability-metrics/
├── idea.md                       # Original feature request
├── plan.md                       # This implementation plan
└── metrics-reference.md          # Metric definitions and thresholds
```

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Metric collection success rate | >99% | CloudWatch metric availability |
| Observer performance overhead | <1% CPU | ECS container metrics comparison |
| Quality score accuracy | >85% correlation with manual assessment | Manual call quality review |
| Dashboard adoption | >80% team usage | CloudWatch dashboard access logs |
| Alert actionability | <10% false positive rate | Alert response tracking |

## Rollback Plan

1. **Immediate Rollback**: Disable new observers via environment variables
2. **Metric Rollback**: Continue emitting old metric names, stop new ones
3. **Dashboard Rollback**: Revert to previous dashboard version
4. **Full Rollback**: Remove new observer code, restore original observability.py

## Progress Log

| Date | Update |
|------|--------|
| 2026-02-06 | Plan created, architecture designed, technical decisions documented |
| TBD | Phase 1 implementation (metric renaming and STT quality) |
| TBD | Phase 2 implementation (LLM and WebRTC metrics) |
| TBD | Phase 3 implementation (conversation flow analysis) |
| TBD | Phase 4 implementation (quality score calculation) |
| TBD | Phase 5 implementation (enhanced dashboard and alarms) |
| TBD | Phase 6 implementation (integration and testing) |