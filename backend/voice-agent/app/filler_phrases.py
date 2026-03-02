"""Filler phrase management for conversational delay handling.

This module provides contextually appropriate filler phrases that play during
tool execution delays to maintain natural conversation flow.
"""

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.tools.schema import ToolCategory


@dataclass
class FillerPhraseManager:
    """Manages filler phrase selection with deduplication.

    Selects contextually appropriate filler phrases based on tool category
    and ensures consecutive phrases don't repeat.

    Attributes:
        last_phrase: The most recently used phrase (for deduplication)
        phrase_history: Recent phrases used (for broader deduplication)
        max_history: Maximum number of phrases to track for deduplication
    """

    last_phrase: Optional[str] = None
    phrase_history: List[str] = field(default_factory=list)
    max_history: int = 5

    # Tool category to specific phrases mapping
    CATEGORY_PHRASES: Dict[ToolCategory, List[str]] = field(default_factory=lambda: {
        ToolCategory.CUSTOMER_INFO: [
            "Let me pull up your account information...",
            "I'm looking up your account now...",
            "Just a moment while I access your account...",
        ],
        ToolCategory.ORDER_MANAGEMENT: [
            "I'm checking on that order for you now...",
            "Let me look up your order status...",
            "One moment while I find your order...",
        ],
        ToolCategory.CRM: [
            "I'm creating that for you now...",
            "Let me set that up for you...",
            "Just a moment while I process that...",
        ],
        ToolCategory.KNOWLEDGE_BASE: [
            "Let me search our knowledge base...",
            "I'm looking that up for you...",
            "One moment while I find that information...",
        ],
        ToolCategory.SYSTEM: [
            "One moment while I look that up...",
            "Let me check on that for you...",
            "Just a second...",
        ],
        ToolCategory.TESTING: [
            "Processing your request...",
            "One moment please...",
        ],
    })

    # Generic phrases used as fallback
    GENERIC_PHRASES: List[str] = field(default_factory=lambda: [
        "Just a moment...",
        "Let me check on that...",
        "One second while I look into this...",
        "Bear with me for just a moment...",
        "Let me look that up for you...",
        "I'm working on that now...",
    ])

    def get_phrase(self, category: Optional[ToolCategory] = None) -> str:
        """Get a contextually appropriate filler phrase.

        Selects a phrase based on tool category, avoiding recently used phrases
        to maintain variety in the conversation.

        Args:
            category: The tool category for context-specific phrases.
                     If None, uses generic phrases.

        Returns:
            A filler phrase string suitable for TTS synthesis.
        """
        # Get candidate phrases based on category
        if category and category in self.CATEGORY_PHRASES:
            candidates = self.CATEGORY_PHRASES[category].copy()
        else:
            candidates = self.GENERIC_PHRASES.copy()

        # Filter out recently used phrases if we have enough alternatives
        available = [p for p in candidates if p not in self.phrase_history]

        # If all phrases have been used recently, reset and use all candidates
        if not available:
            available = candidates

        # Select a random phrase from available options
        phrase = random.choice(available)

        # Update history
        self._record_phrase(phrase)

        return phrase

    def get_phrase_for_tool(self, tool_name: str, category: ToolCategory) -> str:
        """Get a filler phrase for a specific tool.

        This method allows for tool-specific customization in the future
        while currently delegating to category-based selection.

        Args:
            tool_name: The name of the tool being executed.
            category: The tool's category.

        Returns:
            A filler phrase string.
        """
        # Future: Could add tool-specific phrases here
        # tool_phrases = {
        #     "get_customer_info": "Let me pull up your account...",
        #     "check_order_status": "I'm checking on your order...",
        # }
        # if tool_name in tool_phrases:
        #     return tool_phrases[tool_name]

        return self.get_phrase(category)

    def _record_phrase(self, phrase: str) -> None:
        """Record a phrase in history for deduplication.

        Args:
            phrase: The phrase that was just used.
        """
        self.last_phrase = phrase
        self.phrase_history.append(phrase)

        # Trim history to max size
        if len(self.phrase_history) > self.max_history:
            self.phrase_history = self.phrase_history[-self.max_history:]

    def reset(self) -> None:
        """Reset phrase history.

        Call this at the start of a new conversation to allow
        phrase reuse across conversations.
        """
        self.last_phrase = None
        self.phrase_history = []


# Global instance for use across a session
_session_manager: Optional[FillerPhraseManager] = None


def get_filler_manager() -> FillerPhraseManager:
    """Get or create the session's filler phrase manager.

    Returns:
        The FillerPhraseManager instance for this session.
    """
    global _session_manager
    if _session_manager is None:
        _session_manager = FillerPhraseManager()
    return _session_manager


def reset_filler_manager() -> None:
    """Reset the global filler manager.

    Call at the start of each new call/session.
    """
    global _session_manager
    _session_manager = None
