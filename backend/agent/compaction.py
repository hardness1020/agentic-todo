"""Rule-based context compaction for the tool-calling loop.

Ported from the reference ``code.py`` (``tool_result_budget`` /
``micro_compact`` / ``snip_compact``), but **rule-based only** — the
reference's LLM summarising compaction (``summarize_history``) is intentionally
left out. Auto-compaction runs once before every model call (see
``runner.run_loop``) and shrinks the *in-memory* working context with three
deterministic, cheap passes:

1. **Cap a single oversized tool result** — truncate any one ``tool_result``
   whose text exceeds :data:`TOOL_RESULT_MAX_CHARS` to a head preview, so one
   giant output can never dominate the window. Always applied.
2. **Compact old tool results** — once the whole context exceeds the char
   budget, collapse every ``tool_result`` except the most recent
   :data:`KEEP_RECENT_TOOL_RESULTS` to a short placeholder. Tool outputs are
   the bulk of context growth and are rarely needed verbatim once acted on.
3. **Trim old history** — if still over budget, drop the oldest turns, keeping
   the first prompt plus the suffix from the most recent real user prompt.

Two invariants make this safe to run every turn:

* **Non-mutating.** Every pass copies the messages/blocks it changes and leaves
  the originals untouched, so the persisted transcript and the chat-widget
  display (which alias the same block dicts) keep full fidelity — only the
  context handed to the model shrinks.
* **Boundary-preserving.** A ``tool_use`` block is never separated from its
  ``tool_result``; the message list always still starts on a real user turn.
  Compaction edits *content*, history trims only at user-prompt boundaries.
"""
from __future__ import annotations

import json

from django.conf import settings

from agent.llm import CONTINUATION_PROMPT

# A single tool result longer than this is truncated to a head preview.
TOOL_RESULT_MAX_CHARS = 6000
# Tool results past this many (most-recent-first) collapse to the placeholder.
KEEP_RECENT_TOOL_RESULTS = 3
COMPACTED_PLACEHOLDER = '[Earlier tool result compacted to save context.]'
TRIM_MARKER = '[Earlier conversation trimmed to fit the context window.]'


def _char_budget() -> int:
    return getattr(settings, 'AGENT_CONTEXT_CHAR_BUDGET', 60000)


def estimate_size(messages) -> int:
    """Cheap proxy for context size: the JSON length of the message list."""
    return len(json.dumps(messages, default=str))


def _truncate_preview(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    dropped = len(text) - max_chars
    return f'{text[:max_chars]}\n…[+{dropped} chars truncated]'


def _tool_result_locations(messages):
    """``(message_index, block_index)`` of every ``tool_result`` block, in order."""
    locs = []
    for mi, msg in enumerate(messages):
        content = msg.get('content')
        if msg.get('role') != 'user' or not isinstance(content, list):
            continue
        for bi, block in enumerate(content):
            if isinstance(block, dict) and block.get('type') == 'tool_result':
                locs.append((mi, bi))
    return locs


def _rewrite_tool_results(messages, edits):
    """Return a new message list with ``tool_result`` blocks rewritten.

    ``edits`` maps ``(message_index, block_index) -> new_content_string``. Only
    the touched messages and blocks are copied; everything else is shared, so
    callers that did not change keep object identity (and the originals are
    never mutated)."""
    by_msg = {}
    for (mi, bi), new_content in edits.items():
        by_msg.setdefault(mi, {})[bi] = new_content
    out = []
    for mi, msg in enumerate(messages):
        block_edits = by_msg.get(mi)
        if not block_edits:
            out.append(msg)
            continue
        new_content = list(msg['content'])
        for bi, new_text in block_edits.items():
            new_content[bi] = {**new_content[bi], 'content': new_text}
        out.append({**msg, 'content': new_content})
    return out


def cap_tool_result_content(messages, max_chars: int = TOOL_RESULT_MAX_CHARS):
    """Truncate any single ``tool_result`` whose text exceeds ``max_chars``."""
    edits = {}
    for mi, bi in _tool_result_locations(messages):
        text = messages[mi]['content'][bi].get('content')
        if isinstance(text, str) and len(text) > max_chars:
            edits[(mi, bi)] = _truncate_preview(text, max_chars)
    return _rewrite_tool_results(messages, edits) if edits else messages


def compact_old_tool_results(messages, keep_recent: int = KEEP_RECENT_TOOL_RESULTS):
    """Collapse all but the most recent ``keep_recent`` tool results."""
    locs = _tool_result_locations(messages)
    if len(locs) <= keep_recent:
        return messages
    stale = locs if keep_recent <= 0 else locs[:-keep_recent]
    edits = {}
    for mi, bi in stale:
        text = messages[mi]['content'][bi].get('content')
        if isinstance(text, str) and len(text) > len(COMPACTED_PLACEHOLDER):
            edits[(mi, bi)] = COMPACTED_PLACEHOLDER
    return _rewrite_tool_results(messages, edits) if edits else messages


def trim_history(messages):
    """Drop the oldest turns at a safe boundary, keeping the first prompt.

    A *safe boundary* is a user message with plain-string content (a real
    prompt) that is not the synthetic continuation prompt — never an assistant
    message or a ``tool_result`` carrier, either of which would orphan a
    ``tool_use`` pairing or start the request on an invalid turn. The result is
    ``[first prompt, trim-marker, <suffix from the most recent prompt>]``. With
    fewer than two such boundaries there is nothing to drop safely, so the list
    is returned unchanged."""
    boundaries = [
        i for i, m in enumerate(messages)
        if m.get('role') == 'user'
        and isinstance(m.get('content'), str)
        and m['content'] not in (CONTINUATION_PROMPT, TRIM_MARKER)
    ]
    if len(boundaries) < 2:
        return messages
    head_idx, tail_idx = boundaries[0], boundaries[-1]
    if head_idx >= tail_idx:
        return messages
    return (
        [messages[head_idx]]
        + [{'role': 'user', 'content': TRIM_MARKER}]
        + messages[tail_idx:]
    )


def prepare_context(messages):
    """Auto-compact the working context with the rule-based passes, in order.

    Returns a (possibly new) message list; the input is never mutated. Cheap
    when the context is small — the per-result cap only fires on oversized
    outputs, and the budget-gated passes are skipped entirely under budget."""
    budget = _char_budget()
    messages = cap_tool_result_content(messages)
    if estimate_size(messages) > budget:
        messages = compact_old_tool_results(messages)
    if estimate_size(messages) > budget:
        messages = trim_history(messages)
    return messages
