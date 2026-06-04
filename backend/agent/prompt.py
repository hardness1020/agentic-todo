"""Dynamic system-prompt assembly.

Rebuilt fresh on every model call from live per-user state: identity, the tool
catalog, the current UTC time, this user's todo stats, and their injected
memories (length-capped to bound prompt size/cost). Mirrors the
``assemble_system_prompt`` pattern in the reference ``code.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from todos.models import Todo
from agent.memory import candidate_memories, format_memories
from agent.tools import TOOL_SCHEMAS

IDENTITY = (
    'You are ToDo, a warm, concise assistant embedded in a personal to-do app. '
    "You act on the signed-in user's behalf using the tools below. Prefer "
    'taking action over describing it: when the user asks for a change, call '
    'the matching tool rather than explaining how they could do it. Keep '
    'replies short and friendly.'
)

def _tool_signature(schema) -> str:
    """`name(param, optional?)` from a tool schema — optional params get a `?`."""
    props = schema['input_schema'].get('properties', {})
    required = set(schema['input_schema'].get('required', []))
    params = [name if name in required else f'{name}?' for name in props]
    return f"{schema['name']}({', '.join(params)})"


def build_tool_catalog() -> str:
    """Render the catalog from TOOL_SCHEMAS, the single source of truth, so the
    prompt can never drift from the tools actually handed to the model."""
    header = (
        'Tools (all scoped to the current user — you cannot see or touch anyone '
        "else's data):"
    )
    lines = [f'  {_tool_signature(s)} — {s["description"]}' for s in TOOL_SCHEMAS]
    return header + '\n' + '\n'.join(lines)


# Computed once at import — the schemas are static for the process lifetime.
TOOL_CATALOG = build_tool_catalog()

GUIDANCE = (
    'Scheduling: cron is 5 fields "minute hour day-of-month month day-of-week" '
    '(e.g. "0 * * * *" = every hour, "*/5 * * * *" = every 5 minutes, '
    '"0 9 * * 1-5" = weekdays at 9am). For a one-off reminder set recurring '
    'to false. When a scheduled job fires you will receive its prompt; respond '
    'by doing the work and calling notify_user so the person is alerted.'
)


def _todo_stats(user) -> str:
    qs = Todo.objects.filter(owner=user)
    total = qs.count()
    done = qs.filter(completed=True).count()
    return f'Todo stats: {total - done} open, {done} done, {total} total.'


def assemble_system_prompt(user, memory_block=None) -> str:
    """Build the system prompt from live state.

    ``memory_block`` is the already-retrieved (relevant) memory text — the
    runner computes it once per turn via the secondary-LLM pass and passes it
    in. When ``None`` (e.g. direct callers/tests), every fact is loaded.
    """
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    sections = [
        IDENTITY,
        TOOL_CATALOG,
        GUIDANCE,
        f'Current time (UTC): {now}',
        _todo_stats(user),
    ]
    if memory_block is None:
        memory_block = format_memories(candidate_memories(user))
    if memory_block:
        sections.append('What you remember about this user:\n' + memory_block)
    return '\n\n'.join(sections)
