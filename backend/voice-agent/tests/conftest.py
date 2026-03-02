"""Shared test configuration and fixtures for voice-agent tests.

Registers custom pytest markers and provides skip logic for tests
that require container-only dependencies (pipecat, aiohttp, structlog, aioboto3).
"""

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "container: marks tests that require container-only dependencies (pipecat, aiohttp, etc.)",
    )
