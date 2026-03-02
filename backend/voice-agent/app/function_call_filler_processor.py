"""Filler phrase processor for function call delays.

This module provides a FrameProcessor that injects contextual filler phrases
when function calls are about to execute, maintaining natural conversation flow
during tool execution delays.

The processor intercepts FunctionCallsStartedFrame and pushes a TTSSpeakFrame
with an appropriate filler phrase before the function call begins execution.
"""

import random
from typing import Dict, List, Optional

import structlog
from pipecat.frames.frames import (
    Frame,
    FunctionCallsStartedFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)


class FunctionCallFillerProcessor(FrameProcessor):
    """Injects filler phrases when function calls are about to execute.

    This processor intercepts FunctionCallsStartedFrame (emitted when the LLM
    decides to call a tool) and pushes a TTSSpeakFrame with a contextual filler
    phrase. The filler plays while the tool executes, maintaining natural
    conversation flow.

    The approach differs from post-hoc audio injection:
    - The LLM has already decided to call a tool
    - The filler is spoken as part of the normal pipeline flow
    - The filler becomes part of the conversation context (which is appropriate
      since the assistant is saying "let me look that up")
    - No timing/race condition issues with the tool response

    Example usage::

        filler_processor = FunctionCallFillerProcessor()

        pipeline = Pipeline([
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            filler_processor,  # Place after LLM, before TTS
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ])

    Attributes:
        enabled: Whether filler phrases are enabled
        _last_phrase: Most recently used phrase (for deduplication)
        _phrase_history: Recent phrases for broader deduplication
    """

    # Function name to specific phrases mapping
    FUNCTION_PHRASES: Dict[str, List[str]] = {
        "get_customer_info": [
            "Let me pull up your account...",
            "I'm looking up your account now...",
        ],
        "check_order_status": [
            "Let me check on that order...",
            "I'm looking up your order now...",
        ],
        "get_current_time": [
            "Let me check the time...",
        ],
    }

    # Generic phrases for any function call
    GENERIC_PHRASES: List[str] = [
        "Let me look that up for you...",
        "One moment while I check on that...",
        "Let me check on that...",
        "Just a moment...",
        "I'm looking into that now...",
    ]

    def __init__(
        self,
        enabled: bool = True,
        name: Optional[str] = None,
        **kwargs,
    ):
        """Initialize the filler processor.

        Args:
            enabled: Whether filler phrases are enabled
            name: Processor name (optional)
            **kwargs: Additional arguments for FrameProcessor
        """
        super().__init__(name=name, **kwargs)
        self.enabled = enabled
        self._last_phrase: Optional[str] = None
        self._phrase_history: List[str] = []
        self._max_history = 5

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process frames, injecting fillers when function calls start.

        When a FunctionCallsStartedFrame is received, a contextual filler
        phrase is pushed as a TTSSpeakFrame before passing the original
        frame downstream.

        Args:
            frame: The frame to process
            direction: Direction of frame flow
        """
        await super().process_frame(frame, direction)

        if isinstance(frame, FunctionCallsStartedFrame) and self.enabled:
            # Get function names for context
            function_names = [fc.function_name for fc in frame.function_calls]

            # Get appropriate filler phrase
            phrase = self._get_phrase(function_names)

            logger.info(
                "function_call_filler_injecting",
                functions=function_names,
                phrase=phrase,
            )

            # Push filler phrase before the function call frame
            await self.push_frame(TTSSpeakFrame(text=phrase))

        # Always pass the original frame through
        await self.push_frame(frame, direction)

    def _get_phrase(self, function_names: List[str]) -> str:
        """Get a contextual filler phrase for the function call.

        Attempts to find a function-specific phrase first, then falls back
        to generic phrases. Avoids recently used phrases for variety.

        Args:
            function_names: Names of functions being called

        Returns:
            A filler phrase string
        """
        # Try to find a function-specific phrase
        for name in function_names:
            if name in self.FUNCTION_PHRASES:
                candidates = self.FUNCTION_PHRASES[name].copy()
                phrase = self._select_phrase(candidates)
                if phrase:
                    return phrase

        # Fall back to generic phrases
        return self._select_phrase(self.GENERIC_PHRASES.copy())

    def _select_phrase(self, candidates: List[str]) -> str:
        """Select a phrase from candidates, avoiding recent ones.

        Args:
            candidates: List of possible phrases

        Returns:
            Selected phrase
        """
        # Filter out recently used phrases
        available = [p for p in candidates if p not in self._phrase_history]

        # If all have been used, reset and use all candidates
        if not available:
            available = candidates

        # Select randomly from available
        phrase = random.choice(available)

        # Record in history
        self._last_phrase = phrase
        self._phrase_history.append(phrase)
        if len(self._phrase_history) > self._max_history:
            self._phrase_history = self._phrase_history[-self._max_history:]

        return phrase

    def reset(self) -> None:
        """Reset phrase history for a new conversation."""
        self._last_phrase = None
        self._phrase_history = []
