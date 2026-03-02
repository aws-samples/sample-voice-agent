"""ECS Task Scale-in Protection client.

Uses the ECS Agent API available at $ECS_AGENT_URI to set/clear
task protection during voice call handling. Protection prevents
Application Auto Scaling from selecting this task for termination
during scale-in events while active voice calls are in progress.

Protection lifecycle is dict-boundary driven:
- When active_sessions transitions from 0 → 1: protection ON
- When active_sessions transitions from 1 → 0: protection OFF
- Individual calls don't touch protection (no per-call API calls)

This is race-safe because pop() and len() checks are synchronous
in the asyncio event loop -- no await between them means no interleaving.

Reference: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-scale-in-protection-endpoint.html
"""

import asyncio
import os

import aiohttp
import structlog

logger = structlog.get_logger(__name__)

PROTECTION_EXPIRY_MINUTES = (
    30  # Safety net for stuck sessions; renewed every 30s via heartbeat
)
MAX_RETRIES = 3
RETRY_BASE_DELAY = 0.1  # 100ms


class TaskProtection:
    """Manages ECS Task Scale-in Protection for voice call handling.

    Uses a single reusable aiohttp.ClientSession for connection pooling
    to the local ECS Agent API ($ECS_AGENT_URI).
    """

    # Escalate renewal failures to ERROR after this many consecutive failures
    RENEWAL_ESCALATION_THRESHOLD = 3

    def __init__(self) -> None:
        self._agent_uri = os.environ.get("ECS_AGENT_URI")
        self._protected = False
        self._session: aiohttp.ClientSession | None = None
        self._consecutive_renewal_failures = 0

    @property
    def is_available(self) -> bool:
        """Check if ECS Agent API is available (not available in local dev)."""
        return self._agent_uri is not None

    @property
    def is_protected(self) -> bool:
        """Whether task scale-in protection is currently enabled."""
        return self._protected

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create a reusable HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            )
        return self._session

    async def set_protected(self, protected: bool, retry: bool = True) -> bool:
        """Set or clear task scale-in protection.

        Args:
            protected: True to enable protection, False to allow termination.
            retry: Whether to retry on failure (default True for critical path).

        Returns:
            True if successfully set, False if unavailable or failed.
        """
        if not self.is_available:
            logger.debug("task_protection_unavailable", reason="local_dev")
            return False

        if protected == self._protected:
            logger.debug(
                "task_protection_no_change",
                protection_enabled=protected,
            )
            return True

        endpoint = f"{self._agent_uri}/task-protection/v1/state"
        payload: dict = {"ProtectionEnabled": protected}
        if protected:
            payload["ExpiresInMinutes"] = PROTECTION_EXPIRY_MINUTES

        max_attempts = MAX_RETRIES if retry else 1
        for attempt in range(max_attempts):
            try:
                session = await self._get_session()
                async with session.put(endpoint, json=payload) as resp:
                    if resp.status == 200:
                        self._protected = protected
                        logger.info(
                            "task_protection_updated",
                            protection_enabled=protected,
                        )
                        return True
                    else:
                        body = await resp.text()
                        logger.error(
                            "task_protection_api_error",
                            status=resp.status,
                            body=body,
                            attempt=attempt + 1,
                        )
            except Exception:
                logger.exception(
                    "task_protection_api_exception",
                    attempt=attempt + 1,
                )

            if attempt < max_attempts - 1:
                delay = RETRY_BASE_DELAY * (2**attempt)
                await asyncio.sleep(delay)

        logger.error(
            "task_protection_all_retries_exhausted",
            protected=protected,
            attempts=max_attempts,
        )
        return False

    async def renew_if_protected(self) -> bool:
        """Renew protection if currently protected.

        Called from the heartbeat loop (every 30s) to ensure protection
        never lapses during long calls. The ExpiresInMinutes timer is
        reset on each renewal.

        Retries up to MAX_RETRIES times with exponential backoff (matching
        set_protected()). Tracks consecutive failures and escalates to
        ERROR after RENEWAL_ESCALATION_THRESHOLD consecutive failures.

        Returns:
            True if renewed, False if not protected or failed.
        """
        if not self.is_available or not self._protected:
            return False

        endpoint = f"{self._agent_uri}/task-protection/v1/state"
        payload = {
            "ProtectionEnabled": True,
            "ExpiresInMinutes": PROTECTION_EXPIRY_MINUTES,
        }

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.put(endpoint, json=payload) as resp:
                    if resp.status == 200:
                        if self._consecutive_renewal_failures > 0:
                            logger.info(
                                "task_protection_renewal_recovered",
                                previous_failures=self._consecutive_renewal_failures,
                            )
                        self._consecutive_renewal_failures = 0
                        logger.debug("task_protection_renewed")
                        return True
                    else:
                        body = await resp.text()
                        logger.warning(
                            "task_protection_renewal_failed",
                            status=resp.status,
                            body=body,
                            attempt=attempt + 1,
                        )
            except Exception as e:
                logger.warning(
                    "task_protection_renewal_exception",
                    error=str(e),
                    error_type=type(e).__name__,
                    attempt=attempt + 1,
                )

            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2**attempt)
                await asyncio.sleep(delay)

        # All retries exhausted
        self._consecutive_renewal_failures += 1

        if self._consecutive_renewal_failures >= self.RENEWAL_ESCALATION_THRESHOLD:
            logger.error(
                "task_protection_renewal_persistent_failure",
                consecutive_failures=self._consecutive_renewal_failures,
                attempts=MAX_RETRIES,
                note="Protection may lapse if failures continue",
            )
        else:
            logger.warning(
                "task_protection_renewal_all_retries_exhausted",
                consecutive_failures=self._consecutive_renewal_failures,
                attempts=MAX_RETRIES,
            )

        return False

    async def close(self) -> None:
        """Close the HTTP session. Call during shutdown."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
