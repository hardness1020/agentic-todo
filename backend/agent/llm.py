"""Anthropic client factory + LLM error recovery.

Ported from the reference ``code.py``: exponential backoff with jitter on
429s, fallback-model switch after repeated 529/overloaded errors, and
prompt-too-long detection (handled one level up by a reactive trim).

The ``anthropic`` import is lazy so the whole app boots — and the test suite
runs — without the package installed or any API key configured. When no key
(or no package) is present, :func:`get_client` returns ``None`` and the chat
endpoint degrades to ``503`` while the rest of the app keeps working.
"""
from __future__ import annotations

import logging
import random
import time

from django.conf import settings

logger = logging.getLogger('agent')

MAX_RETRIES = 3
MAX_CONSECUTIVE_529 = 2
BASE_DELAY_MS = 500
MAX_DELAY_MS = 32000
DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 16000
MAX_RECOVERY_RETRIES = 2
CONTINUATION_PROMPT = 'Continue from the previous response. Do not repeat completed work.'


def get_client():
    """Return an Anthropic client, or ``None`` if unavailable.

    ``None`` is returned when no API key is configured or the ``anthropic``
    package is not installed — both are graceful-degradation paths, never an
    error. The key is read from settings and is never logged.
    """
    api_key = getattr(settings, 'ANTHROPIC_API_KEY', '')
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        logger.warning('anthropic package not installed; assistant disabled.')
        return None
    return Anthropic(api_key=api_key)


class RecoveryState:
    """Per-turn recovery bookkeeping shared across the tool loop."""

    def __init__(self):
        self.has_escalated = False
        self.recovery_count = 0
        self.consecutive_529 = 0
        self.has_attempted_reactive_trim = False
        self.current_model = settings.ANTHROPIC_MODEL
        self.fallback_model = getattr(settings, 'ANTHROPIC_FALLBACK_MODEL', '')


def retry_delay(attempt: int) -> float:
    base = min(BASE_DELAY_MS * (2 ** attempt), MAX_DELAY_MS) / 1000
    return base + random.uniform(0, base * 0.25)


def is_prompt_too_long_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (('prompt' in msg and 'long' in msg)
            or 'context_length_exceeded' in msg
            or 'max_context_window' in msg)


def with_retry(fn, state: RecoveryState):
    """Call ``fn`` with bounded retries.

    * 429 / rate-limit  -> exponential backoff + jitter, then retry.
    * 529 / overloaded  -> retry; after ``MAX_CONSECUTIVE_529`` switch to the
                           fallback model (if one is configured).
    * anything else      -> re-raised for the caller to handle.
    """
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            state.consecutive_529 = 0
            return result
        except Exception as e:
            name = type(e).__name__.lower()
            msg = str(e).lower()
            if 'ratelimit' in name or '429' in msg:
                delay = retry_delay(attempt)
                logger.warning('[429] retry %d/%d after %.1fs',
                               attempt + 1, MAX_RETRIES, delay)
                time.sleep(delay)
                continue
            if 'overloaded' in name or '529' in msg:
                state.consecutive_529 += 1
                if (state.consecutive_529 >= MAX_CONSECUTIVE_529
                        and state.fallback_model):
                    state.current_model = state.fallback_model
                    state.consecutive_529 = 0
                    logger.warning('[529] switching to fallback model %s',
                                   state.fallback_model)
                delay = retry_delay(attempt)
                logger.warning('[529] retry %d/%d after %.1fs',
                               attempt + 1, MAX_RETRIES, delay)
                time.sleep(delay)
                continue
            raise
    raise RuntimeError(f'Max retries ({MAX_RETRIES}) exceeded')
