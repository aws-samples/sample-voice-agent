---
id: intent-classification-service
name: Intent Classification Service
type: Feature
priority: P2
effort: Medium
impact: Medium
created: 2026-02-02
---

# Intent Classification Service

## Problem Statement

The voice agent relies entirely on the LLM to understand customer intent, which can be inconsistent. A dedicated intent classification service would provide:
- More accurate routing to appropriate queues/skills
- Consistent intent detection across conversations
- Confidence scores for escalation decisions
- Analytics on why customers are calling

## Proposed Solution

Build an intent classification service that analyzes customer utterances, classifies intent, and provides confidence scores for routing and analytics.

### Intent Taxonomy

```python
class CustomerIntent(Enum):
    """Standardized customer intents for routing."""
    
    # Billing & Payments
    CHECK_BALANCE = "check_balance"
    MAKE_PAYMENT = "make_payment"
    BILLING_INQUIRY = "billing_inquiry"
    DISPUTE_CHARGE = "dispute_charge"
    REQUEST_REFUND = "request_refund"
    
    # Technical Support
    TROUBLESHOOT = "troubleshoot"
    REPORT_OUTAGE = "report_outage"
    SERVICE_ISSUE = "service_issue"
    
    # Account Management
    UPDATE_ACCOUNT = "update_account"
    RESET_PASSWORD = "reset_password"
    CLOSE_ACCOUNT = "close_account"
    
    # Orders & Shipping
    CHECK_ORDER_STATUS = "check_order_status"
    TRACK_SHIPMENT = "track_shipment"
    MODIFY_ORDER = "modify_order"
    RETURN_ITEM = "return_item"
    
    # Scheduling
    BOOK_APPOINTMENT = "book_appointment"
    RESCHEDULE = "reschedule"
    CANCEL_APPOINTMENT = "cancel_appointment"
    
    # General
    GENERAL_INQUIRY = "general_inquiry"
    COMPLAINT = "complaint"
    COMPLIMENT = "compliment"
    SPEAK_TO_AGENT = "speak_to_agent"
    
    # Unknown/Fallback
    UNKNOWN = "unknown"
```

### Technical Design

```python
# app/services/intent_classification_service.py

from typing import Dict, List, Tuple
import boto3
from dataclasses import dataclass

@dataclass
class IntentClassification:
    """Intent classification result."""
    intent: str
    confidence: float
    alternative_intents: List[Tuple[str, float]]
    entities: Dict[str, str]
    requires_authentication: bool
    suggested_queue: str

class IntentClassificationService:
    """
    Classifies customer intent from utterances.
    
    Uses AWS Comprehend Custom Classification or
    Bedrock LLM for intent detection.
    """
    
    def __init__(self):
        self.comprehend = boto3.client('comprehend')
        self.bedrock = boto3.client('bedrock-runtime')
        
        # Intent to queue mapping
        self.intent_queues = {
            CustomerIntent.CHECK_BALANCE: "billing",
            CustomerIntent.MAKE_PAYMENT: "billing",
            CustomerIntent.BILLING_INQUIRY: "billing",
            CustomerIntent.DISPUTE_CHARGE: "billing_escalated",
            CustomerIntent.TROUBLESHOOT: "technical_support",
            CustomerIntent.REPORT_OUTAGE: "technical_support_priority",
            CustomerIntent.CHECK_ORDER_STATUS: "order_support",
            CustomerIntent.SPEAK_TO_AGENT: "general_queue",
        }
        
        # Intents requiring authentication
        self.auth_required_intents = {
            CustomerIntent.CHECK_BALANCE,
            CustomerIntent.MAKE_PAYMENT,
            CustomerIntent.UPDATE_ACCOUNT,
            CustomerIntent.CLOSE_ACCOUNT,
            CustomerIntent.CHECK_ORDER_STATUS,
        }
    
    async def classify_intent(self, utterance: str) -> IntentClassification:
        """
        Classify customer intent from utterance.
        
        Returns intent, confidence, and routing information.
        """
        # Try Comprehend first (faster, cheaper)
        comprehend_result = await self._classify_with_comprehend(utterance)
        
        # If low confidence, use Bedrock for better accuracy
        if comprehend_result.confidence < 0.7:
            bedrock_result = await self._classify_with_bedrock(utterance)
            if bedrock_result.confidence > comprehend_result.confidence:
                return bedrock_result
        
        return comprehend_result
    
    async def _classify_with_comprehend(self, utterance: str) -> IntentClassification:
        """Classify using AWS Comprehend Custom Classifier."""
        # This requires a trained custom classifier
        response = self.comprehend.classify_document(
            Text=utterance,
            EndpointArn="arn:aws:comprehend:us-east-1:...",  # Custom classifier
        )
        
        classes = response['Classes']
        top_class = classes[0]
        
        intent = self._map_comprehend_class(top_class['Name'])
        confidence = top_class['Score']
        
        alternatives = [
            (self._map_comprehend_class(c['Name']), c['Score'])
            for c in classes[1:3]
        ]
        
        return IntentClassification(
            intent=intent,
            confidence=confidence,
            alternative_intents=alternatives,
            entities={},  # Comprehend doesn't extract entities for custom classifiers
            requires_authentication=intent in self.auth_required_intents,
            suggested_queue=self.intent_queues.get(intent, "general_queue"),
        )
    
    async def _classify_with_bedrock(self, utterance: str) -> IntentClassification:
        """Classify using Bedrock Claude (fallback for low confidence)."""
        
        prompt = f"""
        Classify the customer intent from this utterance.
        
        Customer: "{utterance}"
        
        Possible intents:
        - check_balance: Customer wants to know account balance
        - make_payment: Customer wants to pay a bill
        - billing_inquiry: Questions about charges, invoices
        - dispute_charge: Customer disagrees with a charge
        - troubleshoot: Technical problem or issue
        - report_outage: Service is down or not working
        - check_order_status: Wants to know about an order
        - track_shipment: Wants tracking information
        - book_appointment: Schedule a meeting or service
        - update_account: Change account information
        - reset_password: Forgot or needs to change password
        - speak_to_agent: Wants to talk to human
        - general_inquiry: General question not covered above
        
        Return JSON with:
        - intent: the classified intent
        - confidence: 0.0 to 1.0
        - entities: any extracted entities (order_id, account_number, etc.)
        """
        
        response = await self.bedrock.invoke_model(
            modelId="anthropic.claude-3-5-haiku-20241022-v1:0",
            body=json.dumps({
                "prompt": prompt,
                "max_tokens": 200,
                "temperature": 0.0,
            })
        )
        
        result = json.loads(response['body'].read())
        classification = json.loads(result['completion'])
        
        intent = classification['intent']
        
        return IntentClassification(
            intent=intent,
            confidence=classification['confidence'],
            alternative_intents=[],  # Bedrock doesn't provide alternatives
            entities=classification.get('entities', {}),
            requires_authentication=intent in self.auth_required_intents,
            suggested_queue=self.intent_queues.get(intent, "general_queue"),
        )
    
    def _map_comprehend_class(self, class_name: str) -> str:
        """Map Comprehend class name to intent enum."""
        mapping = {
            "billing": CustomerIntent.BILLING_INQUIRY.value,
            "payment": CustomerIntent.MAKE_PAYMENT.value,
            "technical": CustomerIntent.TROUBLESHOOT.value,
            "order": CustomerIntent.CHECK_ORDER_STATUS.value,
            "account": CustomerIntent.UPDATE_ACCOUNT.value,
            "agent": CustomerIntent.SPEAK_TO_AGENT.value,
        }
        return mapping.get(class_name, CustomerIntent.UNKNOWN.value)

# Integration with Pipeline

class IntentProcessor(FrameProcessor):
    """Pipeline processor for intent classification."""
    
    def __init__(self):
        self.intent_service = IntentClassificationService()
        self.current_intent = None
        self.intent_history = []
    
    async def process_frame(self, frame, direction):
        if isinstance(frame, TranscriptionFrame):
            # Classify intent
            intent_result = await self.intent_service.classify_intent(frame.text)
            
            self.current_intent = intent_result
            self.intent_history.append(intent_result)
            
            # Store in context for routing
            frame.metadata['intent'] = intent_result.intent
            frame.metadata['intent_confidence'] = intent_result.confidence
            frame.metadata['suggested_queue'] = intent_result.suggested_queue
            
            # Emit intent frame
            await self.push_frame(IntentFrame(
                intent=intent_result.intent,
                confidence=intent_result.confidence,
                entities=intent_result.entities,
            ))
        
        await self.push_frame(frame, direction)
```

### Routing Integration

```python
# In transfer tool

async def route_by_intent(self, context: ToolContext) -> str:
    """Route to appropriate queue based on detected intent."""
    intent = context.get_current_intent()
    confidence = context.get_intent_confidence()
    
    # Low confidence - general queue
    if confidence < 0.6:
        return "general_queue"
    
    # Map intent to queue
    queue_mapping = {
        "billing_inquiry": "billing_queue",
        "make_payment": "billing_queue",
        "troubleshoot": "technical_support",
        "report_outage": "technical_priority",
        "check_order_status": "order_support",
    }
    
    return queue_mapping.get(intent, "general_queue")
```

### Analytics

```python
# Intent analytics for reporting

class IntentAnalytics:
    """Track intent distribution and trends."""
    
    async def log_intent(self, session_id: str, intent: IntentClassification):
        """Log intent for analytics."""
        await self.analytics_client.log_event(
            event_type="intent_detected",
            session_id=session_id,
            intent=intent.intent,
            confidence=intent.confidence,
            suggested_queue=intent.suggested_queue,
            timestamp=datetime.now().isoformat(),
        )
    
    async def get_intent_distribution(self, days: int = 30) -> Dict:
        """Get distribution of intents over time."""
        # Query analytics for intent breakdown
        pass
```

## Acceptance Criteria

- [ ] Classifies customer utterances into standardized intents
- [ ] Provides confidence scores for each classification
- [ ] Suggests appropriate queue/skill for routing
- [ ] Identifies intents requiring authentication
- [ ] Extracts relevant entities (order IDs, account numbers)
- [ ] Falls back to general queue for low confidence
- [ ] Tracks intent analytics for reporting
- [ ] Latency < 300ms for classification

## Dependencies

- AWS Comprehend (custom classifier) or Bedrock LLM
- Pipeline processor framework
- Transfer tool for routing

## Notes

- Train custom Comprehend classifier on historical call transcripts
- Start with top 10-15 intents, expand over time
- Use intent data to identify self-service opportunities
- Intent analytics help optimize agent training and staffing
