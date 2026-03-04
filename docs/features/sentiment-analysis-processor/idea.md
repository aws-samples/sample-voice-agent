---
id: sentiment-analysis-processor
name: Real-time Sentiment Analysis Processor
type: Feature
priority: P2
effort: Medium
impact: High
created: 2026-02-02
---

# Real-time Sentiment Analysis Processor

## Problem Statement

The voice agent currently has no awareness of customer emotional state. Frustrated or angry customers should be identified and escalated quickly, but without sentiment analysis, the agent treats all conversations the same regardless of customer satisfaction.

## Proposed Solution

Implement a real-time sentiment analysis processor that monitors customer speech during the call, detects emotional states (frustration, anger, satisfaction), and triggers appropriate actions.

### Sentiment Dimensions

```python
@dataclass
class SentimentAnalysis:
    """Multi-dimensional sentiment analysis."""
    
    # Overall sentiment (-1.0 to 1.0)
    overall: float
    
    # Emotional states (0.0 to 1.0)
    frustration: float
    anger: float
    satisfaction: float
    confusion: float
    urgency: float
    
    # Trend (improving, stable, declining)
    trend: str
    
    # Key phrases that triggered sentiment
    trigger_phrases: List[str]
    
    # Timestamp
    timestamp: datetime
```

### Implementation Options

#### Option 1: AWS Comprehend (Managed Service)

```python
# app/processors/sentiment_processor.py

import boto3
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import TextFrame, TranscriptionFrame

class AWSSentimentProcessor(FrameProcessor):
    """Real-time sentiment analysis using AWS Comprehend."""
    
    def __init__(self):
        super().__init__()
        self.comprehend = boto3.client('comprehend')
        self.sentiment_history = []
        self.current_sentiment = None
    
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        
        if isinstance(frame, TranscriptionFrame):
            # Analyze sentiment of transcription
            sentiment = await self._analyze_sentiment(frame.text)
            
            # Update current sentiment
            self.current_sentiment = sentiment
            self.sentiment_history.append(sentiment)
            
            # Check for escalation triggers
            if self._should_escalate(sentiment):
                await self._trigger_escalation(frame)
            
            # Emit sentiment frame for other processors
            await self.push_frame(SentimentFrame(sentiment=sentiment))
        
        await self.push_frame(frame, direction)
    
    async def _analyze_sentiment(self, text: str) -> SentimentAnalysis:
        """Analyze sentiment using AWS Comprehend."""
        response = self.comprehend.detect_sentiment(
            Text=text,
            LanguageCode='en'
        )
        
        sentiment = response['Sentiment']
        scores = response['SentimentScore']
        
        return SentimentAnalysis(
            overall=self._calculate_overall(scores),
            frustration=self._detect_frustration(text, scores),
            anger=scores.get('Negative', 0),
            satisfaction=scores.get('Positive', 0),
            confusion=self._detect_confusion(text),
            urgency=self._detect_urgency(text),
            trend=self._calculate_trend(),
            trigger_phrases=self._extract_trigger_phrases(text),
            timestamp=datetime.now(),
        )
    
    def _should_escalate(self, sentiment: SentimentAnalysis) -> bool:
        """Determine if sentiment warrants escalation."""
        # Immediate escalation triggers
        if sentiment.anger > 0.8:
            return True
        
        if sentiment.frustration > 0.7 and sentiment.trend == "declining":
            return True
        
        # Sustained negative sentiment
        recent_sentiments = self.sentiment_history[-3:]
        if all(s.overall < -0.5 for s in recent_sentiments):
            return True
        
        return False
```

#### Option 2: Custom Bedrock Model

```python
class BedrockSentimentProcessor(FrameProcessor):
    """Custom sentiment analysis using Bedrock Claude."""
    
    async def _analyze_sentiment(self, text: str) -> SentimentAnalysis:
        """Analyze sentiment using custom prompt with Claude."""
        
        prompt = f"""
        Analyze the sentiment of this customer utterance in a voice call.
        
        Customer: "{text}"
        
        Provide sentiment scores (0.0 to 1.0) for:
        - overall_sentiment: (-1.0 = very negative, 1.0 = very positive)
        - frustration_level: (0.0 = calm, 1.0 = very frustrated)
        - anger_level: (0.0 = not angry, 1.0 = very angry)
        - satisfaction_level: (0.0 = unsatisfied, 1.0 = very satisfied)
        - confusion_level: (0.0 = clear, 1.0 = very confused)
        - urgency_level: (0.0 = not urgent, 1.0 = very urgent)
        
        Also identify any trigger phrases that indicate strong emotions.
        
        Return as JSON.
        """
        
        response = await self.bedrock_client.invoke_model(
            modelId="anthropic.claude-3-5-haiku-20241022-v1:0",
            body=json.dumps({
                "prompt": prompt,
                "max_tokens": 200,
                "temperature": 0.0,
            })
        )
        
        result = json.loads(response['body'].read())
        sentiment_data = json.loads(result['completion'])
        
        return SentimentAnalysis(**sentiment_data)
```

### Integration with Pipeline

```python
# In pipeline_ecs.py

# Add sentiment processor to pipeline
sentiment_processor = AWSSentimentProcessor()

# Pipeline flow
pipeline = Pipeline([
    transport.input(),
    stt,
    context_aggregator.user(),
    sentiment_processor,  # Analyze sentiment on user speech
    llm,
    tts,
    transport.output(),
    context_aggregator.assistant(),
])
```

### Escalation Triggers

```python
ESCALATION_RULES = {
    "immediate": {
        "conditions": [
            "anger > 0.8",
            "frustration > 0.9",
        ],
        "action": "transfer_to_human",
        "message": "I understand your frustration. Let me connect you with a specialist right away.",
    },
    "proactive": {
        "conditions": [
            "frustration > 0.7 AND trend == declining",
            "sustained_negative_sentiment > 3_turns",
        ],
        "action": "offer_human_transfer",
        "message": "I want to make sure you get the best help. Would you like me to connect you with a specialist?",
    },
    "monitor": {
        "conditions": [
            "frustration > 0.5",
            "confusion > 0.6",
        ],
        "action": "adjust_approach",
        "message": None,  # System adjusts tone/pacing
    },
}
```

### Conversation Flow Example

```
[Call begins - sentiment: neutral]

Caller: "Hi, I'm having trouble with my internet"
Sentiment: {overall: 0.0, frustration: 0.2}

Agent: "I'll help you troubleshoot that. Can you tell me what specific issues 
        you're experiencing?"

Caller: "It's been down for THREE DAYS and I've already called twice!"
Sentiment: {overall: -0.7, frustration: 0.8, anger: 0.6}
[ESCALATION TRIGGERED - Proactive offer]

Agent: "I sincerely apologize for the ongoing issue. That's absolutely 
        frustrating, and you shouldn't have to deal with this. I want to make 
        sure you get this resolved quickly. Would you like me to connect you 
        with a technical specialist who can prioritize getting your service 
        restored?"

Caller: "Yes, please"

[Transfer initiated with context about frustration and outage duration]
```

## Acceptance Criteria

- [ ] Real-time sentiment analysis on customer speech
- [ ] Tracks multiple sentiment dimensions (frustration, anger, satisfaction, etc.)
- [ ] Detects sentiment trends over the conversation
- [ ] Triggers escalation when thresholds are exceeded
- [ ] Adjusts agent tone/approach based on sentiment
- [ ] Provides sentiment data to human agents on transfer
- [ ] Latency < 500ms for sentiment analysis
- [ ] Privacy-compliant (no storage of sensitive sentiment data)

## Dependencies

- AWS Comprehend or Bedrock LLM access
- Pipeline processor framework
- Transfer tool for escalation

## Notes

- Consider using custom models for industry-specific language
- Combine acoustic features (tone, pitch) with text for better accuracy
- Sentiment history helps detect declining trends
- Can be used post-call for quality analysis
