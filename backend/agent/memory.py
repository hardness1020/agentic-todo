"""Per-user memory loading and secondary-LLM retrieval.

Instead of dumping every stored fact into the system prompt, a turn retrieves
only the facts relevant to the current message. The ``Secondary LLM → Memory``
(load / retrieval) path in the design:

* At most ``RETRIEVAL_THRESHOLD`` facts → inject them all (no extra LLM call —
  it would cost more than it saves).
* More than that → call a secondary (cheaper/faster) Claude model **once** to
  pick the relevant facts, and inject only those.

Retrieval is **best-effort**: a missing client, an LLM error, or an unparseable
reply all fall back to injecting the full (length-capped) set, so the agent
never loses access to memory and the no-key path is unaffected.
"""
from __future__ import annotations

import logging
import re

from django.conf import settings

from agent.models import Memory

logger = logging.getLogger('agent')

MEMORY_CHAR_CAP = 2000


def _threshold() -> int:
    return getattr(settings, 'AGENT_MEMORY_RETRIEVAL_THRESHOLD', 5)


def candidate_memories(user):
    """All of the user's facts, most-recently-updated first."""
    return list(Memory.objects.filter(owner=user).order_by('-updated_at'))


def format_memories(mems) -> str:
    """Render facts as a length-capped ``- key: value`` block."""
    lines = []
    used = 0
    for mem in mems:
        line = f'- {mem.key}: {mem.value}'
        if used + len(line) + 1 > MEMORY_CHAR_CAP:
            break
        lines.append(line)
        used += len(line) + 1
    return '\n'.join(lines)


_SELECT_SYSTEM = (
    "You decide which of a user's stored facts are relevant to their current message. "
    'Reply with ONLY the numbers of the relevant facts, comma-separated (e.g. "1, 3"), '
    'or the single word "none". Do not explain.'
)


def _parse_selection(text: str, count: int):
    """Map a selection reply to 0-based indices.

    Returns a list of indices, or ``None`` when the reply gives no usable
    signal (so the caller can fall back to injecting everything). An explicit
    "none" returns ``[]`` (a valid empty selection).
    """
    nums = re.findall(r'\d+', text or '')
    if nums:
        seen, out = set(), []
        for n in nums:
            i = int(n) - 1
            if 0 <= i < count and i not in seen:
                seen.add(i)
                out.append(i)
        return out
    if 'none' in (text or '').lower():
        return []
    return None


def _select_relevant(mems, query, client, model):
    """Ask the secondary model which facts matter. Raises on any failure so the
    caller can fall back."""
    listing = '\n'.join(f'{i + 1}. [{m.key}] {m.value}' for i, m in enumerate(mems))
    prompt = (
        f"User message:\n{query}\n\n"
        f"Stored facts:\n{listing}\n\n"
        'Relevant fact numbers:'
    )
    response = client.messages.create(
        model=model,
        system=_SELECT_SYSTEM,
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=100,
    )
    text = ''.join(
        getattr(b, 'text', '') or ''
        for b in (response.content or [])
        if getattr(b, 'type', None) == 'text'
    )
    indices = _parse_selection(text, len(mems))
    if indices is None:
        raise ValueError(f'Unparseable memory selection: {text!r}')
    return [mems[i] for i in indices]


def retrieve_relevant(user, query, client) -> str:
    """Return the system-prompt memory block for ``query``.

    Short-circuits to "inject all" below the threshold or without a client;
    otherwise uses the secondary model and degrades to "inject all" on failure.
    """
    mems = candidate_memories(user)
    if not mems:
        return ''
    if client is None or len(mems) <= _threshold():
        return format_memories(mems)

    model = getattr(settings, 'ANTHROPIC_SECONDARY_MODEL', '') or settings.ANTHROPIC_MODEL
    try:
        selected = _select_relevant(mems, query, client, model)
    except Exception:
        logger.warning('Memory retrieval failed; injecting all facts.', exc_info=True)
        return format_memories(mems)
    logger.info('Memory retrieval: selected %d/%d facts.', len(selected), len(mems))
    return format_memories(selected)
