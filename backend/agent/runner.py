"""The agent runner: one tool-calling loop reused by chat and by fired cron jobs.

A turn rebuilds the system prompt each model call (live state), executes any
tool_use blocks against the per-user handler closure, feeds the results back,
and repeats until the model stops or a turn cap is hit. The same recovery
ladder as the reference ``code.py`` wraps it: 429 backoff, 529 fallback-model
switch, ``max_tokens`` escalation then bounded continuation, one reactive trim
on prompt-too-long, and a clean assistant error message for anything else.
"""
from __future__ import annotations

import logging

from django.conf import settings

from agent.compaction import prepare_context
from agent.llm import (
    CONTINUATION_PROMPT,
    DEFAULT_MAX_TOKENS,
    ESCALATED_MAX_TOKENS,
    MAX_RECOVERY_RETRIES,
    RecoveryState,
    is_prompt_too_long_error,
    with_retry,
)
from agent.memory import retrieve_relevant
from agent.models import ChatMessage
from agent.prompt import assemble_system_prompt
from agent.tools import TOOL_SCHEMAS, build_handlers

logger = logging.getLogger('agent')


# ── block helpers (tolerate both SDK objects and stored dicts) ──

def _block_attr(block, name, default=None):
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def blocks_to_dicts(content):
    """Normalize an assistant ``content`` (SDK blocks or dicts) to plain dicts."""
    out = []
    for block in content or []:
        btype = _block_attr(block, 'type')
        if btype == 'text':
            out.append({'type': 'text', 'text': _block_attr(block, 'text', '') or ''})
        elif btype == 'tool_use':
            out.append({
                'type': 'tool_use',
                'id': _block_attr(block, 'id'),
                'name': _block_attr(block, 'name'),
                'input': _block_attr(block, 'input', {}) or {},
            })
    return out


def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = [
        _block_attr(b, 'text', '') or ''
        for b in (content or [])
        if _block_attr(b, 'type') == 'text'
    ]
    return '\n'.join(p for p in parts if p).strip()


def has_tool_use(content) -> bool:
    return any(_block_attr(b, 'type') == 'tool_use' for b in (content or []))


def _call_handler(handler, args, name) -> str:
    """Invoke a tool handler, turning any failure into a string the model can
    recover from (never a raw exception into the loop)."""
    if handler is None:
        return f'Unknown tool: {name}'
    try:
        result = handler(**(args or {}))
    except TypeError as e:
        return f'Error calling {name}: {e}'
    except Exception as e:  # pragma: no cover - defensive; DB errors etc.
        logger.exception('tool %s raised', name)
        return f'Error in {name}: {e}'
    return result if isinstance(result, str) else str(result)


def _reactive_trim(messages):
    """Drop older history once on a prompt-too-long error.

    Keeps from the most recent *real* user prompt (role ``user`` with string
    content) to the end, so the retried request starts at a valid user turn
    boundary — never on an assistant message or an orphaned ``tool_result``,
    either of which Anthropic rejects. This preserves the in-progress turn
    (its tool_use/tool_result blocks) while shedding older history.
    """
    start = 0
    for i, m in enumerate(messages):
        if m.get('role') == 'user' and isinstance(m.get('content'), str):
            start = i
    trimmed = messages[start:]
    return trimmed or messages


def _max_turns() -> int:
    return getattr(settings, 'AGENT_MAX_TURNS', 8)


def _latest_user_text(messages) -> str:
    """The most recent real user prompt (string content) — what memory
    retrieval is keyed on. Empty string if none."""
    for m in reversed(messages):
        if m.get('role') == 'user' and isinstance(m.get('content'), str):
            return m['content']
    return ''


def run_loop(user, messages, client, persist, memory_block=None):
    """Drive the tool-calling loop in place over ``messages``.

    ``persist(role, content)`` is called for every new message the loop
    produces (a no-op for cron turns). ``memory_block`` is the retrieved
    relevant-memory text, computed once per turn and reused for every model
    call. Returns the shared ``actions`` list of mutations performed this turn.
    """
    handlers, actions = build_handlers(user)
    state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS
    max_turns = _max_turns()

    for _ in range(max_turns):
        # Auto-compact the working context before every model call (rule-based,
        # non-destructive: the stored transcript keeps full fidelity). This is
        # the proactive complement to the reactive prompt-too-long trim below.
        messages[:] = prepare_context(messages)
        system = assemble_system_prompt(user, memory_block)
        try:
            response = with_retry(
                lambda: client.messages.create(
                    model=state.current_model,
                    system=system,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    max_tokens=max_tokens,
                ),
                state,
            )
        except Exception as e:
            if is_prompt_too_long_error(e) and not state.has_attempted_reactive_trim:
                messages[:] = _reactive_trim(messages)
                state.has_attempted_reactive_trim = True
                continue
            logger.exception('agent turn failed')
            err = [{'type': 'text',
                    'text': "Sorry — I ran into a problem and couldn't finish that. "
                            'Please try again in a moment.'}]
            messages.append({'role': 'assistant', 'content': err})
            persist('assistant', err)
            return actions

        if getattr(response, 'stop_reason', None) == 'max_tokens':
            if not state.has_escalated:
                # Discard the truncated response and regenerate with a larger
                # budget. Nothing is appended, so the next call sees the same
                # (valid) message sequence — no orphaned blocks.
                max_tokens = ESCALATED_MAX_TOKENS
                state.has_escalated = True
                continue
            assistant = blocks_to_dicts(response.content)
            messages.append({'role': 'assistant', 'content': assistant})
            persist('assistant', assistant)
            if state.recovery_count >= MAX_RECOVERY_RETRIES:
                return actions
            state.recovery_count += 1
            # Every tool_use block MUST be answered with a tool_result or the
            # next Anthropic call is rejected. A response truncated at the token
            # limit may carry a partial/uncertain tool_use, so we do NOT execute
            # it — we answer each with a synthetic error and let the model retry.
            # With no tool_use, a plain continuation prompt is a valid next turn.
            pending = [b for b in assistant if b.get('type') == 'tool_use']
            if pending:
                results = [{
                    'type': 'tool_result',
                    'tool_use_id': b.get('id'),
                    'content': 'Tool not executed: the response was truncated at the '
                               'token limit. Please retry more concisely.',
                } for b in pending]
                messages.append({'role': 'user', 'content': results})
                persist('user', results)
            else:
                messages.append({'role': 'user', 'content': CONTINUATION_PROMPT})
                persist('user', CONTINUATION_PROMPT)
            continue

        max_tokens = DEFAULT_MAX_TOKENS
        state.has_escalated = False
        assistant = blocks_to_dicts(response.content)
        messages.append({'role': 'assistant', 'content': assistant})
        persist('assistant', assistant)

        if not has_tool_use(assistant):
            return actions

        results = []
        for block in assistant:
            if block.get('type') != 'tool_use':
                continue
            name = block.get('name')
            output = _call_handler(handlers.get(name), block.get('input'), name)
            logger.info('tool %s -> %s', name, str(output)[:120])
            results.append({
                'type': 'tool_result',
                'tool_use_id': block.get('id'),
                'content': output,
            })
        messages.append({'role': 'user', 'content': results})
        persist('user', results)

    # Turn cap reached mid-work: close with an assistant message so the
    # transcript stays role-alternating and the user gets a reply.
    logger.warning('agent turn hit the %d-turn cap', max_turns)
    closing = [{'type': 'text',
                'text': "I've done as much as I can for now — let me know if you'd "
                        'like me to continue.'}]
    messages.append({'role': 'assistant', 'content': closing})
    persist('assistant', closing)
    return actions


# ── display derivation (stored transcript -> frontend shape) ──

def conversation_display(stored_messages):
    """Turn an ordered list of :class:`ChatMessage` into the chat-widget shape:

      user      -> {'role': 'user', 'text': str}
      assistant -> {'role': 'assistant', 'text': str,
                    'steps': [{'tool', 'label', 'status': 'done'}]}

    Tool-result (user-role list) messages are folded into the preceding
    assistant message's step labels rather than shown as bubbles.
    """
    result_text = {}
    for msg in stored_messages:
        content = msg.content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'tool_result':
                    result_text[block.get('tool_use_id')] = block.get('content', '')

    display = []
    for msg in stored_messages:
        content = msg.content
        if msg.role == 'user':
            if isinstance(content, str) and content != CONTINUATION_PROMPT:
                display.append({'role': 'user', 'text': content})
            continue
        # assistant
        steps = []
        for block in (content if isinstance(content, list) else []):
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                steps.append({
                    'tool': block.get('name'),
                    'label': result_text.get(block.get('id'), ''),
                    'status': 'done',
                })
        display.append({
            'role': 'assistant',
            'text': extract_text(content),
            'steps': steps,
        })
    return display


# ── entry points ──

def run_agent_turn(user, conversation, client):
    """Run a chat turn. The caller has already persisted the user's message.

    Loads the full transcript as context, runs the loop persisting each new
    message, and returns ``{'messages': <new assistant display msgs>,
    'actions': [...]}``.
    """
    stored = list(conversation.messages.all())
    messages = [{'role': m.role, 'content': m.content} for m in stored]

    # Retrieve the memories relevant to this turn (secondary-LLM pass) once,
    # keyed on the message that triggered it (the latest user prompt).
    memory_block = retrieve_relevant(user, _latest_user_text(messages), client)

    created = []

    def persist(role, content):
        created.append(
            ChatMessage.objects.create(conversation=conversation, role=role, content=content)
        )

    actions = run_loop(user, messages, client, persist, memory_block=memory_block)
    return {'messages': conversation_display(created), 'actions': actions}


def run_cron_turn(user, prompt, client):
    """Run a standalone, self-contained agent turn for a fired cron job.

    Not persisted to the chat transcript; side effects (todos, memory,
    notifications) persist through the handlers. Returns the actions list.
    """
    messages = [{'role': 'user', 'content': prompt}]
    memory_block = retrieve_relevant(user, prompt, client)
    return run_loop(
        user, messages, client,
        persist=lambda role, content: None,
        memory_block=memory_block,
    )
