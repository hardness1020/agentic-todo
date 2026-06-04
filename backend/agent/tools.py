"""The agent's fixed tool catalog and per-user handler closures.

``TOOL_SCHEMAS`` is the static schema list handed to Anthropic. ``build_handlers``
returns callables **closed over a single user** — this closure is the isolation
guardrail: the model is given no user/owner/id field it can override, every ORM
query is filtered by ``owner=user``, and any id outside the caller's scope
resolves to a benign "not found" (the agent-layer analog of the base app's
404-on-mismatch). Handlers return short descriptive strings the model can act on
and never raise raw DB errors into the loop.

Each mutation also appends to a shared ``actions`` list so the runner can tell
the frontend which rows to reactively highlight:
``{'action': create|update|complete|delete, 'resource': todo|memory|reminder|notification, 'id': int}``.
"""
from __future__ import annotations

from todos.models import Todo
from todos.serializers import TodoSerializer
from agent.models import Memory, Notification, ScheduledJob
from agent.cron import humanize_cron, validate_cron


TOOL_SCHEMAS = [
    {
        'name': 'create_todo',
        'description': "Create a new todo for the user.",
        'input_schema': {
            'type': 'object',
            'properties': {
                'title': {'type': 'string', 'description': 'Short todo title (1-255 chars).'},
                'description': {'type': 'string', 'description': 'Optional details.'},
            },
            'required': ['title'],
        },
    },
    {
        'name': 'list_todos',
        'description': "List the user's todos.",
        'input_schema': {
            'type': 'object',
            'properties': {
                'include_completed': {
                    'type': 'boolean',
                    'description': 'Include completed todos (default true).',
                },
            },
        },
    },
    {
        'name': 'update_todo',
        'description': "Edit a todo's title and/or description.",
        'input_schema': {
            'type': 'object',
            'properties': {
                'id': {'type': 'integer', 'description': 'The todo id.'},
                'title': {'type': 'string'},
                'description': {'type': 'string'},
            },
            'required': ['id'],
        },
    },
    {
        'name': 'complete_todo',
        'description': 'Mark a todo as completed.',
        'input_schema': {
            'type': 'object',
            'properties': {'id': {'type': 'integer', 'description': 'The todo id.'}},
            'required': ['id'],
        },
    },
    {
        'name': 'delete_todo',
        'description': 'Delete a todo.',
        'input_schema': {
            'type': 'object',
            'properties': {'id': {'type': 'integer', 'description': 'The todo id.'}},
            'required': ['id'],
        },
    },
    {
        'name': 'get_todo_stats',
        'description': 'Get the open / done / total counts for the user.',
        'input_schema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'remember',
        'description': 'Store a durable fact about the user, keyed for later recall. '
                       'Re-using a key overwrites the previous value.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'key': {'type': 'string', 'description': 'Short stable key, e.g. "title_style".'},
                'value': {'type': 'string', 'description': 'The fact to remember.'},
            },
            'required': ['key', 'value'],
        },
    },
    {
        'name': 'recall',
        'description': 'Read back facts remembered about the user.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Optional filter substring.'},
            },
        },
    },
    {
        'name': 'schedule_cron',
        'description': 'Schedule a 5-field cron job that later fires an agent turn for '
                       'this user. Use for reminders and recurring tasks.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'cron': {'type': 'string', 'description': '5-field cron: "min hour dom month dow".'},
                'prompt': {'type': 'string', 'description': 'What the agent should do when it fires.'},
                'label': {'type': 'string', 'description': 'Short human label for the reminder row.'},
                'recurring': {'type': 'boolean', 'description': 'False for a one-shot (default true).'},
            },
            'required': ['cron', 'prompt'],
        },
    },
    {
        'name': 'list_crons',
        'description': "List the user's scheduled cron jobs.",
        'input_schema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'cancel_cron',
        'description': 'Cancel (delete) a scheduled cron job by id.',
        'input_schema': {
            'type': 'object',
            'properties': {'id': {'type': 'integer', 'description': 'The scheduled job id.'}},
            'required': ['id'],
        },
    },
    {
        'name': 'notify_user',
        'description': 'Push a notification to the user\'s dashboard (bell + toast).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'body': {'type': 'string'},
            },
            'required': ['title'],
        },
    },
]

TOOL_NAMES = [t['name'] for t in TOOL_SCHEMAS]


def _flatten_errors(errors) -> str:
    parts = []
    if isinstance(errors, dict):
        for field, msgs in errors.items():
            joined = ' '.join(str(m) for m in (msgs if isinstance(msgs, list) else [msgs]))
            parts.append(f'{field}: {joined}')
    else:
        parts.append(str(errors))
    return ' '.join(parts)


def _as_int(value):
    """Coerce a tool-supplied id to int, or ``None`` if not an integer."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_handlers(user):
    """Return ``(handlers, actions)`` bound to ``user``.

    ``handlers`` maps tool name -> callable; ``actions`` is the shared list each
    mutating handler appends to.
    """
    actions = []

    # ---- todos ----
    def create_todo(title=None, description=''):
        serializer = TodoSerializer(data={'title': title or '', 'description': description or ''})
        if not serializer.is_valid():
            return _flatten_errors(serializer.errors)
        todo = serializer.save(owner=user)
        actions.append({'action': 'create', 'resource': 'todo', 'id': todo.id})
        return f'Created todo #{todo.id}: "{todo.title}".'

    def list_todos(include_completed=True):
        qs = Todo.objects.filter(owner=user)
        if not include_completed:
            qs = qs.filter(completed=False)
        todos = list(qs)
        if not todos:
            return 'No todos.'
        lines = [
            f'#{t.id} [{"x" if t.completed else " "}] {t.title}'
            for t in todos
        ]
        return 'Todos:\n' + '\n'.join(lines)

    def update_todo(id=None, title=None, description=None):
        pk = _as_int(id)
        todo = Todo.objects.filter(owner=user, pk=pk).first() if pk else None
        if todo is None:
            return f'Todo {id} not found.'
        data = {}
        if title is not None:
            data['title'] = title
        if description is not None:
            data['description'] = description
        if not data:
            return 'Nothing to update; provide a title or description.'
        serializer = TodoSerializer(todo, data=data, partial=True)
        if not serializer.is_valid():
            return _flatten_errors(serializer.errors)
        serializer.save()
        actions.append({'action': 'update', 'resource': 'todo', 'id': todo.id})
        return f'Updated todo #{todo.id}: "{todo.title}".'

    def complete_todo(id=None):
        pk = _as_int(id)
        todo = Todo.objects.filter(owner=user, pk=pk).first() if pk else None
        if todo is None:
            return f'Todo {id} not found.'
        if not todo.completed:
            todo.completed = True
            todo.save(update_fields=['completed', 'updated_at'])
        actions.append({'action': 'complete', 'resource': 'todo', 'id': todo.id})
        return f'Completed todo #{todo.id}: "{todo.title}".'

    def delete_todo(id=None):
        pk = _as_int(id)
        todo = Todo.objects.filter(owner=user, pk=pk).first() if pk else None
        if todo is None:
            return f'Todo {id} not found.'
        title, tid = todo.title, todo.id
        todo.delete()
        actions.append({'action': 'delete', 'resource': 'todo', 'id': tid})
        return f'Deleted todo #{tid}: "{title}".'

    def get_todo_stats():
        qs = Todo.objects.filter(owner=user)
        total = qs.count()
        done = qs.filter(completed=True).count()
        return f'{total - done} open, {done} done, {total} total.'

    # ---- memory ----
    def remember(key=None, value=None):
        if not key or not str(key).strip():
            return 'A non-empty key is required to remember a fact.'
        if value is None or not str(value).strip():
            return 'A non-empty value is required to remember a fact.'
        memory, created = Memory.objects.update_or_create(
            owner=user, key=str(key).strip(), defaults={'value': str(value).strip()},
        )
        actions.append({
            'action': 'create' if created else 'update',
            'resource': 'memory', 'id': memory.id,
        })
        verb = 'Remembered' if created else 'Updated memory'
        return f'{verb} "{memory.key}": {memory.value}'

    def recall(query=None):
        qs = Memory.objects.filter(owner=user)
        if query:
            qs = qs.filter(value__icontains=query) | qs.filter(key__icontains=query)
        facts = list(qs.distinct())
        if not facts:
            return 'Nothing remembered yet.'
        return 'Remembered facts:\n' + '\n'.join(f'- {m.key}: {m.value}' for m in facts)

    # ---- scheduling ----
    def schedule_cron(cron=None, prompt=None, label=None, recurring=True):
        cron = (cron or '').strip()
        err = validate_cron(cron)
        if err:
            return f'Invalid cron expression: {err}'
        if not prompt or not str(prompt).strip():
            return 'A prompt describing what to do is required.'
        prompt = str(prompt).strip()
        clean_label = (label or '').strip() or (prompt[:80])
        job = ScheduledJob.objects.create(
            owner=user, cron=cron, prompt=prompt, label=clean_label,
            recurring=bool(recurring),
        )
        actions.append({'action': 'create', 'resource': 'reminder', 'id': job.id})
        return (f'Scheduled job #{job.id} ({humanize_cron(cron)}): "{clean_label}" '
                f'[{"recurring" if job.recurring else "one-shot"}].')

    def list_crons():
        jobs = list(ScheduledJob.objects.filter(owner=user, active=True))
        if not jobs:
            return 'No scheduled jobs.'
        return 'Scheduled jobs:\n' + '\n'.join(
            f'#{j.id} {j.cron} ({humanize_cron(j.cron)}) -> {j.label} '
            f'[{"recurring" if j.recurring else "one-shot"}]'
            for j in jobs
        )

    def cancel_cron(id=None):
        pk = _as_int(id)
        job = ScheduledJob.objects.filter(owner=user, pk=pk).first() if pk else None
        if job is None:
            return f'Scheduled job {id} not found.'
        label, jid = job.label, job.id
        job.delete()
        actions.append({'action': 'delete', 'resource': 'reminder', 'id': jid})
        return f'Cancelled scheduled job #{jid}: "{label}".'

    # ---- notifications ----
    def notify_user(title=None, body=''):
        if not title or not str(title).strip():
            return 'A notification title is required.'
        notification = Notification.objects.create(
            owner=user, title=str(title).strip(), body=str(body or '').strip(),
        )
        actions.append({'action': 'create', 'resource': 'notification', 'id': notification.id})
        return f'Notified the user: "{notification.title}".'

    handlers = {
        'create_todo': create_todo,
        'list_todos': list_todos,
        'update_todo': update_todo,
        'complete_todo': complete_todo,
        'delete_todo': delete_todo,
        'get_todo_stats': get_todo_stats,
        'remember': remember,
        'recall': recall,
        'schedule_cron': schedule_cron,
        'list_crons': list_crons,
        'cancel_cron': cancel_cron,
        'notify_user': notify_user,
    }
    return handlers, actions
