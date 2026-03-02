"""Unit tests for filler phrase management."""

import pytest

try:
    from app.filler_phrases import (
        FillerPhraseManager,
        get_filler_manager,
        reset_filler_manager,
    )
    from app.tools.schema import ToolCategory
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (structlog)", allow_module_level=True
    )


class TestFillerPhraseManager:
    """Tests for FillerPhraseManager class."""

    def test_get_phrase_returns_string(self):
        """Test that get_phrase returns a non-empty string."""
        manager = FillerPhraseManager()
        phrase = manager.get_phrase()

        assert isinstance(phrase, str)
        assert len(phrase) > 0

    def test_get_phrase_with_category(self):
        """Test that category-specific phrases are returned."""
        manager = FillerPhraseManager()

        # Test customer info category
        phrase = manager.get_phrase(ToolCategory.CUSTOMER_INFO)
        assert isinstance(phrase, str)
        assert len(phrase) > 0

        # Test order management category
        phrase = manager.get_phrase(ToolCategory.ORDER_MANAGEMENT)
        assert isinstance(phrase, str)
        assert len(phrase) > 0

    def test_get_phrase_for_tool(self):
        """Test get_phrase_for_tool method."""
        manager = FillerPhraseManager()

        phrase = manager.get_phrase_for_tool("get_current_time", ToolCategory.SYSTEM)
        assert isinstance(phrase, str)
        assert len(phrase) > 0

    def test_phrase_deduplication(self):
        """Test that consecutive phrases are different when possible."""
        manager = FillerPhraseManager()

        # Get multiple phrases
        phrases = [manager.get_phrase() for _ in range(10)]

        # Check that we have variety (not all the same)
        unique_phrases = set(phrases)
        assert len(unique_phrases) > 1, "Should have variety in phrases"

    def test_phrase_history_tracking(self):
        """Test that phrase history is tracked correctly."""
        manager = FillerPhraseManager()

        # Initially empty
        assert len(manager.phrase_history) == 0
        assert manager.last_phrase is None

        # Get a phrase
        phrase1 = manager.get_phrase()
        assert manager.last_phrase == phrase1
        assert len(manager.phrase_history) == 1

        # Get another phrase
        phrase2 = manager.get_phrase()
        assert manager.last_phrase == phrase2
        assert len(manager.phrase_history) == 2

    def test_phrase_history_max_size(self):
        """Test that phrase history doesn't grow beyond max_history."""
        manager = FillerPhraseManager(max_history=3)

        # Get more phrases than max_history
        for _ in range(10):
            manager.get_phrase()

        assert len(manager.phrase_history) <= 3

    def test_reset_clears_history(self):
        """Test that reset clears phrase history."""
        manager = FillerPhraseManager()

        # Build up some history
        for _ in range(5):
            manager.get_phrase()

        assert len(manager.phrase_history) > 0

        # Reset
        manager.reset()

        assert len(manager.phrase_history) == 0
        assert manager.last_phrase is None

    def test_all_categories_have_phrases(self):
        """Test that all tool categories have associated phrases."""
        manager = FillerPhraseManager()

        for category in ToolCategory:
            phrase = manager.get_phrase(category)
            assert isinstance(phrase, str)
            assert len(phrase) > 0

    def test_generic_phrases_used_for_none_category(self):
        """Test that generic phrases are used when no category specified."""
        manager = FillerPhraseManager()

        phrase = manager.get_phrase(None)
        assert phrase in manager.GENERIC_PHRASES

    def test_category_phrases_are_contextual(self):
        """Test that category phrases are contextually appropriate."""
        manager = FillerPhraseManager()

        # Customer info phrases should mention account
        customer_phrases = manager.CATEGORY_PHRASES[ToolCategory.CUSTOMER_INFO]
        assert any("account" in p.lower() for p in customer_phrases)

        # Order management phrases should mention order
        order_phrases = manager.CATEGORY_PHRASES[ToolCategory.ORDER_MANAGEMENT]
        assert any("order" in p.lower() for p in order_phrases)


class TestGlobalFillerManager:
    """Tests for global filler manager functions."""

    def test_get_filler_manager_returns_instance(self):
        """Test that get_filler_manager returns a FillerPhraseManager."""
        reset_filler_manager()  # Start fresh

        manager = get_filler_manager()
        assert isinstance(manager, FillerPhraseManager)

    def test_get_filler_manager_returns_same_instance(self):
        """Test that get_filler_manager returns the same instance."""
        reset_filler_manager()  # Start fresh

        manager1 = get_filler_manager()
        manager2 = get_filler_manager()

        assert manager1 is manager2

    def test_reset_filler_manager_creates_new_instance(self):
        """Test that reset creates a new instance on next get."""
        reset_filler_manager()

        manager1 = get_filler_manager()
        # Build some history
        manager1.get_phrase()
        manager1.get_phrase()

        # Reset
        reset_filler_manager()

        manager2 = get_filler_manager()
        assert manager2 is not manager1
        assert len(manager2.phrase_history) == 0


class TestFillerPhraseContent:
    """Tests for filler phrase content quality."""

    def test_phrases_are_natural(self):
        """Test that phrases sound natural for voice output."""
        manager = FillerPhraseManager()

        all_phrases = list(manager.GENERIC_PHRASES)
        for category_phrases in manager.CATEGORY_PHRASES.values():
            all_phrases.extend(category_phrases)

        for phrase in all_phrases:
            # Should end with ellipsis (natural pause)
            assert phrase.endswith("..."), f"Phrase should end with ellipsis: {phrase}"

            # Should not contain technical jargon
            assert "API" not in phrase
            assert "database" not in phrase.lower()
            assert "error" not in phrase.lower()

            # Should be reasonably short (voice-friendly)
            word_count = len(phrase.split())
            assert word_count <= 10, f"Phrase too long: {phrase}"

    def test_phrases_are_reassuring(self):
        """Test that phrases reassure the caller."""
        manager = FillerPhraseManager()

        all_phrases = list(manager.GENERIC_PHRASES)
        for category_phrases in manager.CATEGORY_PHRASES.values():
            all_phrases.extend(category_phrases)

        # At least some phrases should indicate action being taken
        action_words = [
            "let me",
            "checking",
            "looking",
            "searching",
            "moment",
            "second",
        ]
        has_action = any(
            any(word in phrase.lower() for word in action_words)
            for phrase in all_phrases
        )
        assert has_action, "Phrases should indicate action is being taken"
