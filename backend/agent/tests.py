"""Offline, deterministic tests for the agent app.

A fake Anthropic client is injected everywhere a turn runs — the real API is
never called. Covers cron validate/match, a full chat turn (persistence +
actions), the no-key 503 path, agent-tool per-user isolation, memory
upsert/isolation/prompt-injection, scheduler firing semantics, and owner-scoped
endpoints with 401 gating.
"""
import copy
from datetime import datetime
from unittest import mock

from django.contrib.auth.models import User
from django.test import override_settings, SimpleTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from todos.models import Todo
from agent.cron import cron_matches, validate_cron, humanize_cron, next_fire
from agent.models import (
    ChatMessage,
    Conversation,
    Memory,
    Notification,
    ScheduledJob,
)
from agent.prompt import assemble_system_prompt
from agent.runner import run_agent_turn, run_cron_turn
from agent.scheduler import run_due_jobs
from agent import compaction as compaction_mod
from agent import memory as memory_mod
from agent.llm import CONTINUATION_PROMPT


# ───────────────────────── Fake Anthropic client ─────────────────────────

class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def text_block(text):
    return _Block(type='text', text=text)


def tool_use_block(tool_use_id, name, tool_input):
    return _Block(type='tool_use', id=tool_use_id, name=name, input=tool_input)


class _Response:
    def __init__(self, content, stop_reason='end_turn'):
        self.content = content
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._scripted:
            return self._scripted.pop(0)
        # Default: nothing more to do — end the turn cleanly.
        return _Response([text_block('Done.')])


class FakeAnthropic:
    """Replays a scripted list of ``_Response`` objects, one per model call."""

    def __init__(self, scripted=None):
        self.messages = _FakeMessages(scripted or [])


def tool_then_text(tool_name, tool_input, final_text='Done.', tool_use_id='tu_1'):
    """A two-call turn: call one tool, then reply with text."""
    return FakeAnthropic([
        _Response([tool_use_block(tool_use_id, tool_name, tool_input)],
                  stop_reason='tool_use'),
        _Response([text_block(final_text)], stop_reason='end_turn'),
    ])


# ───────────────────────────── Cron logic ─────────────────────────────

class CronValidationTests(APITestCase):
    def test_accepts_common_expressions(self):
        for expr in ['* * * * *', '0 * * * *', '*/5 * * * *',
                     '0 9 * * 1-5', '30 8 1 * *', '0 10 * * 0,6']:
            self.assertIsNone(validate_cron(expr), expr)

    def test_rejects_wrong_field_count(self):
        self.assertIn('5 fields', validate_cron('* * * *'))

    def test_rejects_out_of_bounds_and_garbage(self):
        self.assertIsNotNone(validate_cron('60 * * * *'))   # minute > 59
        self.assertIsNotNone(validate_cron('0 24 * * *'))   # hour > 23
        self.assertIsNotNone(validate_cron('0 9 * * 7'))    # dow > 6
        self.assertIsNotNone(validate_cron('x * * * *'))    # non-numeric
        self.assertIsNotNone(validate_cron('0 9-5 * * *'))  # range start > end

    def test_humanize(self):
        self.assertEqual(humanize_cron('0 * * * *'), 'every hour')
        self.assertEqual(humanize_cron('*/5 * * * *'), 'every 5 minutes')
        self.assertEqual(humanize_cron('0 9 * * 1-5'), 'every weekday at 9am')

    def test_humanize_specific_calendar_date(self):
        # A one-shot at a specific date/time must not leak the raw cron to the UI.
        self.assertEqual(humanize_cron('36 17 4 6 *'), 'on Jun 4 at 5:36pm')
        self.assertEqual(humanize_cron('0 12 25 12 *'), 'on Dec 25 at noon')
        self.assertEqual(humanize_cron('0 9 15 * *'), 'on day 15 at 9am')


class CronMatchTests(APITestCase):
    def test_wildcards_and_steps(self):
        self.assertTrue(cron_matches('* * * * *', datetime(2024, 1, 3, 13, 7)))
        self.assertTrue(cron_matches('*/15 * * * *', datetime(2024, 1, 3, 13, 30)))
        self.assertFalse(cron_matches('*/15 * * * *', datetime(2024, 1, 3, 13, 7)))
        self.assertFalse(cron_matches('bad expr', datetime(2024, 1, 3, 13, 7)))

    def test_day_of_month_or_day_of_week_semantics(self):
        # "0 9 1 * 1": at 09:00 on the 1st OR on a Monday (Jan 1 2024 is a Mon).
        expr = '0 9 1 * 1'
        # day-of-month hit (Feb 1 2024 is a Thursday, not Monday):
        self.assertTrue(cron_matches(expr, datetime(2024, 2, 1, 9, 0)))
        # day-of-week hit (Jan 8 2024 is a Monday, day 8):
        self.assertTrue(cron_matches(expr, datetime(2024, 1, 8, 9, 0)))
        # neither (Jan 3 2024 is a Wednesday, day 3):
        self.assertFalse(cron_matches(expr, datetime(2024, 1, 3, 9, 0)))
        # right day, wrong hour:
        self.assertFalse(cron_matches(expr, datetime(2024, 2, 1, 10, 0)))

    def test_weekday_range_excludes_weekend(self):
        expr = '0 9 * * 1-5'
        self.assertTrue(cron_matches(expr, datetime(2024, 1, 1, 9, 0)))   # Mon
        self.assertFalse(cron_matches(expr, datetime(2024, 1, 6, 9, 0)))  # Sat

    def test_next_fire_advances(self):
        nxt = next_fire('0 * * * *', datetime(2024, 1, 1, 13, 30))
        self.assertEqual(nxt, datetime(2024, 1, 1, 14, 0))


# ───────────────────────────── Chat turn ─────────────────────────────

CHAT_URL = '/api/chat/messages/'


class ChatTurnTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='sup3rSecret!')
        self.client.force_authenticate(self.user)

    def test_turn_persists_messages_creates_todo_and_returns_action(self):
        fake = tool_then_text('create_todo', {'title': 'Buy milk'},
                              final_text='Added it.')
        with mock.patch('agent.views.get_client', return_value=fake):
            resp = self.client.post(CHAT_URL, {'content': 'add buy milk'}, format='json')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        # A todo owned by the caller was actually created.
        todo = Todo.objects.get(title='Buy milk')
        self.assertEqual(todo.owner, self.user)
        # The mutation is reported in actions for the reactive highlight.
        self.assertIn(
            {'action': 'create', 'resource': 'todo', 'id': todo.id},
            resp.data['actions'],
        )
        # The transcript persisted user + assistant(tool_use) + tool_result + assistant(text).
        conv = Conversation.objects.get(owner=self.user)
        roles = list(conv.messages.values_list('role', flat=True))
        self.assertEqual(roles, ['user', 'assistant', 'user', 'assistant'])
        # A tool_use block was stored verbatim in an assistant message.
        tool_uses = [
            block
            for m in conv.messages.filter(role='assistant')
            for block in (m.content if isinstance(m.content, list) else [])
            if isinstance(block, dict) and block.get('type') == 'tool_use'
        ]
        self.assertEqual(tool_uses, [
            {'type': 'tool_use', 'id': 'tu_1', 'name': 'create_todo',
             'input': {'title': 'Buy milk'}},
        ])
        # A matching tool_result block (same id) was persisted as a user message.
        tool_results = [
            block
            for m in conv.messages.filter(role='user')
            for block in (m.content if isinstance(m.content, list) else [])
            if isinstance(block, dict) and block.get('type') == 'tool_result'
        ]
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(tool_results[0]['tool_use_id'], 'tu_1')

    def test_get_returns_display_transcript(self):
        fake = tool_then_text('create_todo', {'title': 'Walk'}, final_text='Done!')
        with mock.patch('agent.views.get_client', return_value=fake):
            self.client.post(CHAT_URL, {'content': 'add walk'}, format='json')
        resp = self.client.get(CHAT_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        msgs = resp.data['messages']
        self.assertEqual(msgs[0], {'role': 'user', 'text': 'add walk'})
        # An assistant message carries a finished create_todo step.
        steps = [s for m in msgs if m['role'] == 'assistant' for s in m['steps']]
        self.assertTrue(any(s['tool'] == 'create_todo' and s['status'] == 'done'
                            for s in steps))

    def test_reset_clears_transcript(self):
        fake = tool_then_text('get_todo_stats', {})
        with mock.patch('agent.views.get_client', return_value=fake):
            self.client.post(CHAT_URL, {'content': 'stats?'}, format='json')
        self.assertTrue(ChatMessage.objects.filter(conversation__owner=self.user).exists())
        resp = self.client.post(CHAT_URL + 'reset/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ChatMessage.objects.filter(conversation__owner=self.user).exists())

    def test_empty_message_rejected(self):
        resp = self.client.post(CHAT_URL, {'content': '   '}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_api_key_returns_503_but_persists_user_message(self):
        with mock.patch('agent.views.get_client', return_value=None):
            resp = self.client.post(CHAT_URL, {'content': 'add buy milk'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        conv = Conversation.objects.get(owner=self.user)
        self.assertEqual(
            list(conv.messages.values_list('role', flat=True)), ['user'],
        )
        # No assistant action ran.
        self.assertEqual(Todo.objects.count(), 0)

    def test_prompt_too_long_triggers_one_trim_then_succeeds(self):
        # First model call raises a prompt-too-long error; after the reactive
        # trim the retry succeeds and the turn completes normally.
        class _Boom(Exception):
            pass

        calls = {'n': 0}

        class _TrimFake:
            def __init__(self):
                self.messages = self

            def create(self, **kwargs):
                calls['n'] += 1
                if calls['n'] == 1:
                    raise _Boom('prompt is too long: 999999 tokens')
                # After the trim, the retried request must start at a user turn.
                assert kwargs['messages'][0]['role'] == 'user'
                assert isinstance(kwargs['messages'][0]['content'], str)
                return _Response([text_block('Recovered.')], stop_reason='end_turn')

        with mock.patch('agent.views.get_client', return_value=_TrimFake()):
            resp = self.client.post(CHAT_URL, {'content': 'hello'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(calls['n'], 2)
        texts = [m['text'] for m in resp.data['messages'] if m['role'] == 'assistant']
        self.assertIn('Recovered.', texts)

    def test_max_tokens_with_tool_use_answers_with_tool_result(self):
        # max_tokens on a response carrying a tool_use must NOT be followed by a
        # plain-string continuation (that orphans the tool_use and 400s the next
        # call). It must be answered with a tool_result. We hit max_tokens twice
        # (escalation, then post-escalation) and assert the recovery sequence.
        seen = {}

        class _MaxTokensFake:
            def __init__(self):
                self.messages = self
                self.n = 0

            def create(self, **kwargs):
                self.n += 1
                if self.n <= 2:
                    # First call escalates; second call is post-escalation.
                    return _Response(
                        [tool_use_block('tt', 'get_todo_stats', {})],
                        stop_reason='max_tokens',
                    )
                # Third call: the recovery turn. The last message must be a
                # user message whose tool_result answers the orphaned tool_use.
                msgs = kwargs['messages']
                seen['last'] = msgs[-1]
                seen['prev'] = msgs[-2]
                return _Response([text_block('Recovered after truncation.')],
                                 stop_reason='end_turn')

        with mock.patch('agent.views.get_client', return_value=_MaxTokensFake()):
            resp = self.client.post(CHAT_URL, {'content': 'stats'}, format='json')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        # The assistant tool_use was answered by a user tool_result with the same id.
        self.assertEqual(seen['prev']['role'], 'assistant')
        self.assertTrue(any(b.get('type') == 'tool_use' and b.get('id') == 'tt'
                            for b in seen['prev']['content']))
        self.assertEqual(seen['last']['role'], 'user')
        self.assertEqual(
            [b['tool_use_id'] for b in seen['last']['content']
             if b.get('type') == 'tool_result'],
            ['tt'],
        )

    def test_chat_requires_auth(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(CHAT_URL).status_code,
                         status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.client.post(CHAT_URL, {'content': 'x'}, format='json').status_code,
                         status.HTTP_401_UNAUTHORIZED)


# ─────────────────────── Agent tool isolation ───────────────────────

class AgentToolIsolationTests(APITestCase):
    """Alice cannot touch Bob's data through any tool, even with his real id."""

    def setUp(self):
        self.alice = User.objects.create_user('alice', password='sup3rSecret!')
        self.bob = User.objects.create_user('bob', password='sup3rSecret!')
        self.bob_todo = Todo.objects.create(owner=self.bob, title='bob secret')
        self.client.force_authenticate(self.alice)

    def _run(self, tool_name, tool_input):
        fake = tool_then_text(tool_name, tool_input)
        with mock.patch('agent.views.get_client', return_value=fake):
            return self.client.post(CHAT_URL, {'content': 'go'}, format='json')

    def test_update_other_users_todo_does_nothing(self):
        resp = self._run('update_todo', {'id': self.bob_todo.id, 'title': 'hacked'})
        self.bob_todo.refresh_from_db()
        self.assertEqual(self.bob_todo.title, 'bob secret')
        self.assertEqual(resp.data['actions'], [])

    def test_complete_other_users_todo_does_nothing(self):
        self._run('complete_todo', {'id': self.bob_todo.id})
        self.bob_todo.refresh_from_db()
        self.assertFalse(self.bob_todo.completed)

    def test_delete_other_users_todo_does_nothing(self):
        self._run('delete_todo', {'id': self.bob_todo.id})
        self.assertTrue(Todo.objects.filter(pk=self.bob_todo.pk).exists())

    def test_list_todos_never_crosses_users(self):
        Todo.objects.create(owner=self.alice, title='alice only')
        fake = tool_then_text('list_todos', {})
        with mock.patch('agent.views.get_client', return_value=fake):
            self.client.post(CHAT_URL, {'content': 'list'}, format='json')
        # The tool result stored in the transcript must not mention bob's todo.
        tool_results = ChatMessage.objects.filter(
            conversation__owner=self.alice, role='user',
        )
        blob = str([m.content for m in tool_results])
        self.assertIn('alice only', blob)
        self.assertNotIn('bob secret', blob)

    def test_cancel_other_users_cron_does_nothing(self):
        job = ScheduledJob.objects.create(
            owner=self.bob, cron='0 * * * *', prompt='p', label='bob job')
        self._run('cancel_cron', {'id': job.id})
        self.assertTrue(ScheduledJob.objects.filter(pk=job.pk, active=True).exists())


# ───────────────────────────── Memory ─────────────────────────────

class MemoryTests(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user('alice', password='sup3rSecret!')
        self.bob = User.objects.create_user('bob', password='sup3rSecret!')

    def test_remember_upserts_by_owner_and_key(self):
        fake1 = tool_then_text('remember', {'key': 'titles', 'value': 'short'})
        self.client.force_authenticate(self.alice)
        with mock.patch('agent.views.get_client', return_value=fake1):
            self.client.post(CHAT_URL, {'content': 'remember short titles'}, format='json')
        fake2 = tool_then_text('remember', {'key': 'titles', 'value': 'lowercase'})
        with mock.patch('agent.views.get_client', return_value=fake2):
            self.client.post(CHAT_URL, {'content': 'change it'}, format='json')
        mems = Memory.objects.filter(owner=self.alice, key='titles')
        self.assertEqual(mems.count(), 1)
        self.assertEqual(mems.first().value, 'lowercase')

    def test_memory_is_per_user_isolated(self):
        Memory.objects.create(owner=self.alice, key='k', value='alice fact')
        Memory.objects.create(owner=self.bob, key='k', value='bob fact')
        self.assertEqual(Memory.objects.filter(owner=self.alice).count(), 1)
        # Same key, different owners, both exist (constraint is per-owner).
        self.assertEqual(Memory.objects.filter(key='k').count(), 2)

    def test_memory_appears_in_assembled_prompt_for_owner_only(self):
        Memory.objects.create(owner=self.alice, key='style', value='alice prefers short titles')
        Memory.objects.create(owner=self.bob, key='style', value='bob prefers emojis')
        prompt = assemble_system_prompt(self.alice)
        self.assertIn('alice prefers short titles', prompt)
        self.assertNotIn('bob prefers emojis', prompt)


# ──────────────────── Secondary-LLM memory retrieval ────────────────────

class _RecordingFake:
    """A fake client that records calls and returns one scripted text reply."""

    def __init__(self, reply_text='none', raises=False):
        self.messages = self
        self.calls = []
        self.reply_text = reply_text
        self.raises = raises

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError('secondary model unavailable')
        return _Response([text_block(self.reply_text)])


@override_settings(AGENT_MEMORY_RETRIEVAL_THRESHOLD=2)
class MemoryRetrievalTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='sup3rSecret!')

    def _make(self, n):
        # Created oldest→newest, so candidate order (most-recent-first) is kN..k1.
        return [Memory.objects.create(owner=self.user, key=f'k{i}', value=f'fact {i}')
                for i in range(1, n + 1)]

    def test_no_memories_returns_empty_without_calling_secondary(self):
        fake = _RecordingFake()
        self.assertEqual(memory_mod.retrieve_relevant(self.user, 'hi', fake), '')
        self.assertEqual(fake.calls, [])

    def test_at_or_below_threshold_injects_all_without_calling_secondary(self):
        self._make(2)
        fake = _RecordingFake()
        block = memory_mod.retrieve_relevant(self.user, 'hi', fake)
        self.assertIn('k1', block)
        self.assertIn('k2', block)
        self.assertEqual(fake.calls, [])  # short-circuited; no secondary call

    def test_above_threshold_uses_secondary_selection(self):
        self._make(4)  # candidate order: k4, k3, k2, k1
        fake = _RecordingFake(reply_text='1, 3')  # selects k4 and k2
        block = memory_mod.retrieve_relevant(self.user, 'about k4', fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertIn('k4', block)
        self.assertIn('k2', block)
        self.assertNotIn('k3', block)
        self.assertNotIn('k1', block)

    def test_above_threshold_none_selects_nothing(self):
        self._make(4)
        fake = _RecordingFake(reply_text='none')
        self.assertEqual(memory_mod.retrieve_relevant(self.user, 'unrelated', fake), '')

    def test_secondary_failure_falls_back_to_all(self):
        self._make(4)
        fake = _RecordingFake(raises=True)
        block = memory_mod.retrieve_relevant(self.user, 'x', fake)
        for k in ('k1', 'k2', 'k3', 'k4'):
            self.assertIn(k, block)

    def test_unparseable_reply_falls_back_to_all(self):
        self._make(4)
        fake = _RecordingFake(reply_text='hmm, probably all of them')
        block = memory_mod.retrieve_relevant(self.user, 'x', fake)
        for k in ('k1', 'k2', 'k3', 'k4'):
            self.assertIn(k, block)

    def test_no_client_injects_all(self):
        self._make(4)
        block = memory_mod.retrieve_relevant(self.user, 'x', None)
        for k in ('k1', 'k2', 'k3', 'k4'):
            self.assertIn(k, block)


@override_settings(AGENT_MEMORY_RETRIEVAL_THRESHOLD=2)
class MemoryRetrievalChatTests(APITestCase):
    """End-to-end: the secondary model's selection drives which fact the main
    model actually sees in its system prompt."""

    def setUp(self):
        self.user = User.objects.create_user('alice', password='sup3rSecret!')
        self.client.force_authenticate(self.user)

    def test_only_selected_memory_is_injected_into_system_prompt(self):
        for i in range(1, 5):
            Memory.objects.create(owner=self.user, key=f'k{i}', value=f'fact number {i}')
        # candidate order: k4, k3, k2, k1 — secondary selects "1" => k4.
        captured = {}

        class _Fake:
            def __init__(s):
                s.messages = s

            def create(s, **kwargs):
                # The memory-retrieval call is identifiable by its system prompt.
                if kwargs.get('system') == memory_mod._SELECT_SYSTEM:
                    return _Response([text_block('1')])
                captured['system'] = kwargs.get('system')
                return _Response([text_block('Done.')], stop_reason='end_turn')

        with mock.patch('agent.views.get_client', return_value=_Fake()):
            resp = self.client.post(CHAT_URL, {'content': 'what about fact 4?'}, format='json')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('fact number 4', captured['system'])
        for other in ('fact number 1', 'fact number 2', 'fact number 3'):
            self.assertNotIn(other, captured['system'])


# ──────────────────────────── Scheduler ────────────────────────────

class SchedulerTests(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user('alice', password='sup3rSecret!')

    def _notify_turn(self):
        return tool_then_text('notify_user', {'title': 'Stretch', 'body': 'time to move'})

    def test_matching_job_fires_once_and_creates_owned_notification(self):
        now = timezone.now()
        job = ScheduledJob.objects.create(
            owner=self.alice, cron='* * * * *', prompt='nudge', label='stretch')
        fired = run_due_jobs(now=now, client=self._notify_turn())
        self.assertEqual([j.id for j in fired], [job.id])
        note = Notification.objects.get(owner=self.alice)
        self.assertEqual(note.title, 'Stretch')
        job.refresh_from_db()
        self.assertEqual(job.last_fired_marker, now.strftime('%Y-%m-%d %H:%M'))
        self.assertIsNotNone(job.last_fired_at)

    def test_double_fire_guard_same_minute(self):
        now = timezone.now()
        ScheduledJob.objects.create(
            owner=self.alice, cron='* * * * *', prompt='nudge', label='stretch')
        run_due_jobs(now=now, client=self._notify_turn())
        again = run_due_jobs(now=now, client=self._notify_turn())
        self.assertEqual(again, [])
        self.assertEqual(Notification.objects.filter(owner=self.alice).count(), 1)

    def test_one_shot_deactivates_recurring_stays_active(self):
        now = timezone.now()
        one_shot = ScheduledJob.objects.create(
            owner=self.alice, cron='* * * * *', prompt='p', label='once', recurring=False)
        recurring = ScheduledJob.objects.create(
            owner=self.alice, cron='* * * * *', prompt='p', label='loop', recurring=True)
        run_due_jobs(now=now, client=FakeAnthropic())
        one_shot.refresh_from_db()
        recurring.refresh_from_db()
        self.assertFalse(one_shot.active)
        self.assertTrue(recurring.active)

    def test_non_matching_job_does_not_fire(self):
        # Cron fixed to minute 0; pick a now whose minute is not 0.
        now = timezone.now().replace(minute=37)
        ScheduledJob.objects.create(
            owner=self.alice, cron='0 0 * * *', prompt='p', label='midnight')
        self.assertEqual(run_due_jobs(now=now, client=FakeAnthropic()), [])

    def test_no_client_skips_without_stamping(self):
        now = timezone.now()
        job = ScheduledJob.objects.create(
            owner=self.alice, cron='* * * * *', prompt='p', label='x')
        with mock.patch('agent.scheduler.get_client', return_value=None):
            fired = run_due_jobs(now=now)
        self.assertEqual(fired, [])
        job.refresh_from_db()
        self.assertEqual(job.last_fired_marker, '')  # untouched; can fire later

    def test_cron_turn_runs_for_job_owner(self):
        # A fired cron turn that creates a todo persists it for the job owner.
        fake = tool_then_text('create_todo', {'title': 'from cron'})
        run_cron_turn(self.alice, 'make a todo', fake)
        self.assertEqual(Todo.objects.get(title='from cron').owner, self.alice)


# ─────────────────────── Endpoint owner-scoping ───────────────────────

class EndpointScopingTests(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user('alice', password='sup3rSecret!')
        self.bob = User.objects.create_user('bob', password='sup3rSecret!')

    def test_memories_endpoint_is_owner_scoped(self):
        Memory.objects.create(owner=self.alice, key='a', value='alice')
        Memory.objects.create(owner=self.bob, key='b', value='bob')
        self.client.force_authenticate(self.alice)
        resp = self.client.get('/api/memories/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        keys = [m['key'] for m in resp.data['results']]
        self.assertEqual(keys, ['a'])

    def test_cannot_delete_other_users_memory_404(self):
        bob_mem = Memory.objects.create(owner=self.bob, key='b', value='bob')
        self.client.force_authenticate(self.alice)
        resp = self.client.delete(f'/api/memories/{bob_mem.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Memory.objects.filter(pk=bob_mem.pk).exists())

    def test_scheduled_jobs_endpoint_is_owner_scoped(self):
        ScheduledJob.objects.create(owner=self.alice, cron='0 * * * *', prompt='p', label='a')
        ScheduledJob.objects.create(owner=self.bob, cron='0 * * * *', prompt='p', label='b')
        self.client.force_authenticate(self.alice)
        resp = self.client.get('/api/scheduled-jobs/')
        labels = [j['label'] for j in resp.data['results']]
        self.assertEqual(labels, ['a'])

    def test_cannot_cancel_other_users_job_404(self):
        bob_job = ScheduledJob.objects.create(owner=self.bob, cron='0 * * * *', prompt='p', label='b')
        self.client.force_authenticate(self.alice)
        resp = self.client.delete(f'/api/scheduled-jobs/{bob_job.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_notifications_endpoint_scoped_and_mark_all_read(self):
        Notification.objects.create(owner=self.alice, title='a1')
        Notification.objects.create(owner=self.alice, title='a2')
        Notification.objects.create(owner=self.bob, title='b1')
        self.client.force_authenticate(self.alice)
        resp = self.client.get('/api/notifications/')
        self.assertEqual(len(resp.data['results']), 2)
        marked = self.client.post('/api/notifications/mark-all-read/')
        self.assertEqual(marked.data['updated'], 2)
        self.assertFalse(Notification.objects.filter(owner=self.alice, read=False).exists())
        self.assertTrue(Notification.objects.filter(owner=self.bob, read=False).exists())

    def test_cannot_mark_other_users_notification_read_via_patch_404(self):
        bob_note = Notification.objects.create(owner=self.bob, title='b1')
        self.client.force_authenticate(self.alice)
        resp = self.client.patch(f'/api/notifications/{bob_note.id}/', {'read': True}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_stats_action_is_owner_scoped(self):
        Todo.objects.create(owner=self.alice, title='t1')
        Todo.objects.create(owner=self.alice, title='t2', completed=True)
        for i in range(5):
            Todo.objects.create(owner=self.bob, title=f'b{i}')
        self.client.force_authenticate(self.alice)
        resp = self.client.get('/api/todos/stats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, {'open': 1, 'done': 1, 'total': 2})

    def test_agent_endpoints_require_auth(self):
        for url in ['/api/memories/', '/api/scheduled-jobs/',
                    '/api/notifications/', '/api/todos/stats/']:
            self.assertEqual(self.client.get(url).status_code,
                             status.HTTP_401_UNAUTHORIZED, url)


# ─────────────────────── Rule-based auto-compaction ───────────────────────

def _user(text):
    return {'role': 'user', 'content': text}


def _assistant_tool(tool_use_id, name, tool_input=None):
    return {'role': 'assistant',
            'content': [{'type': 'tool_use', 'id': tool_use_id,
                         'name': name, 'input': tool_input or {}}]}


def _tool_result(tool_use_id, content):
    return {'role': 'user',
            'content': [{'type': 'tool_result',
                         'tool_use_id': tool_use_id, 'content': content}]}


def _assistant_text(text):
    return {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}


def _tool_pairs_balanced(messages):
    """Every tool_use is answered by a tool_result with the same id (no orphans)."""
    use_ids, result_ids = set(), set()
    for msg in messages:
        content = msg.get('content')
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get('type') == 'tool_use':
                use_ids.add(block['id'])
            elif block.get('type') == 'tool_result':
                result_ids.add(block['tool_use_id'])
    return use_ids == result_ids


class CompactionUnitTests(SimpleTestCase):
    """The deterministic passes in :mod:`agent.compaction` (no DB, no LLM)."""

    def test_cap_truncates_only_oversized_results_and_preserves_pairing(self):
        big = 'x' * (compaction_mod.TOOL_RESULT_MAX_CHARS + 500)
        messages = [
            _user('hi'),
            _assistant_tool('t1', 'list_todos'),
            _tool_result('t1', big),
            _assistant_tool('t2', 'get_todo_stats'),
            _tool_result('t2', 'small'),
        ]
        snapshot = copy.deepcopy(messages)
        out = compaction_mod.cap_tool_result_content(messages)

        capped = out[2]['content'][0]
        self.assertLess(len(capped['content']), len(big))
        self.assertIn('truncated', capped['content'])
        self.assertEqual(capped['tool_use_id'], 't1')        # pairing intact
        self.assertEqual(out[4]['content'][0]['content'], 'small')  # small untouched
        self.assertEqual(messages, snapshot)                 # input not mutated

    def test_compact_old_results_keeps_recent_intact(self):
        messages = [_user('go')]
        for i in range(5):
            messages.append(_assistant_tool(f't{i}', 'list_todos'))
            messages.append(_tool_result(f't{i}', f'result-body-{i} ' * 10))
        snapshot = copy.deepcopy(messages)

        out = compaction_mod.compact_old_tool_results(messages, keep_recent=2)
        bodies = [b['content'] for m in out if isinstance(m['content'], list)
                  for b in m['content'] if b.get('type') == 'tool_result']
        # 5 results: first 3 collapsed, last 2 kept verbatim.
        self.assertEqual(bodies[:3], [compaction_mod.COMPACTED_PLACEHOLDER] * 3)
        self.assertNotIn(compaction_mod.COMPACTED_PLACEHOLDER, bodies[3:])
        self.assertTrue(_tool_pairs_balanced(out))
        self.assertEqual(messages, snapshot)                 # input not mutated

    def test_compact_old_results_noop_at_or_below_keep_recent(self):
        messages = [_user('go'),
                    _assistant_tool('t1', 'list_todos'),
                    _tool_result('t1', 'body ' * 20)]
        out = compaction_mod.compact_old_tool_results(messages, keep_recent=3)
        self.assertIs(out, messages)

    def test_trim_history_keeps_first_prompt_and_recent_turn(self):
        messages = [
            _user('first ask'),
            _assistant_tool('t1', 'list_todos'),
            _tool_result('t1', 'a'),
            _assistant_text('done one'),
            _user('second ask'),
            _assistant_tool('t2', 'get_todo_stats'),
            _tool_result('t2', 'b'),
            _user('third ask'),
            _assistant_text('working'),
        ]
        out = compaction_mod.trim_history(messages)
        self.assertEqual(out[0], _user('first ask'))         # first prompt kept
        self.assertEqual(out[1]['content'], compaction_mod.TRIM_MARKER)
        self.assertEqual(out[2], _user('third ask'))         # suffix from latest prompt
        self.assertEqual(out[-1], _assistant_text('working'))
        self.assertEqual(out[0]['role'], 'user')             # valid start boundary
        self.assertIsInstance(out[0]['content'], str)
        self.assertTrue(_tool_pairs_balanced(out))

    def test_trim_history_unchanged_with_single_boundary(self):
        messages = [_user('only ask'),
                    _assistant_tool('t1', 'list_todos'),
                    _tool_result('t1', 'x')]
        self.assertIs(compaction_mod.trim_history(messages), messages)

    def test_trim_history_ignores_continuation_prompt_as_boundary(self):
        # The synthetic continuation prompt is a string user message but must
        # NOT be treated as a real boundary to anchor the kept suffix on.
        messages = [_user('real ask'),
                    _assistant_text('partial'),
                    _user(CONTINUATION_PROMPT),
                    _assistant_text('more')]
        self.assertIs(compaction_mod.trim_history(messages), messages)

    @override_settings(AGENT_CONTEXT_CHAR_BUDGET=10_000_000)
    def test_prepare_context_under_budget_only_caps_oversized(self):
        # Well under budget: old tool results are NOT collapsed; a single huge
        # one is still hard-capped.
        big = 'y' * (compaction_mod.TOOL_RESULT_MAX_CHARS + 100)
        messages = [_user('go')]
        for i in range(5):
            messages.append(_assistant_tool(f't{i}', 'list_todos'))
            messages.append(_tool_result(f't{i}', big if i == 0 else f'small-{i}'))
        out = compaction_mod.prepare_context(messages)

        bodies = [b['content'] for m in out if isinstance(m['content'], list)
                  for b in m['content'] if b.get('type') == 'tool_result']
        self.assertIn('truncated', bodies[0])                # oversized capped
        self.assertNotIn(compaction_mod.COMPACTED_PLACEHOLDER, bodies)  # none collapsed

    @override_settings(AGENT_CONTEXT_CHAR_BUDGET=400)
    def test_prepare_context_over_budget_compacts_then_trims_safely(self):
        messages = [_user('first ' * 30)]
        for i in range(6):
            messages.append(_assistant_tool(f't{i}', 'list_todos'))
            messages.append(_tool_result(f't{i}', f'body-{i} ' * 20))
            messages.append(_user(f'follow-up number {i} ' * 5))
            messages.append(_assistant_text(f'reply {i}'))
        snapshot = copy.deepcopy(messages)

        out = compaction_mod.prepare_context(messages)
        self.assertLess(compaction_mod.estimate_size(out),
                        compaction_mod.estimate_size(messages))
        self.assertEqual(out[0]['role'], 'user')             # still a valid start
        self.assertIsInstance(out[0]['content'], str)
        self.assertTrue(_tool_pairs_balanced(out))           # no orphaned blocks
        self.assertEqual(messages, snapshot)                 # input not mutated

        # Idempotent / convergent: re-compacting its own output (the trim marker
        # is not mistaken for a real boundary) does not keep shrinking or break.
        again = compaction_mod.prepare_context(out)
        self.assertEqual(again[0]['role'], 'user')
        self.assertEqual(
            [m['content'] for m in again if isinstance(m.get('content'), str)].count(
                compaction_mod.TRIM_MARKER), 1)
        self.assertTrue(_tool_pairs_balanced(again))


class CompactionLoopTests(APITestCase):
    """Auto-compaction is wired into the real loop and preserves the transcript."""

    @override_settings(AGENT_CONTEXT_CHAR_BUDGET=900)
    def test_loop_compacts_context_but_keeps_full_stored_transcript(self):
        user = User.objects.create_user('carol', password='sup3rSecret!')
        conversation = Conversation.for_user(user)
        big = 'todo-line ' * 40  # ~400 chars, < the per-result hard cap
        ChatMessage.objects.create(conversation=conversation, role='user', content='start')
        for i in range(5):
            ChatMessage.objects.create(
                conversation=conversation, role='assistant',
                content=[{'type': 'tool_use', 'id': f't{i}',
                          'name': 'list_todos', 'input': {}}])
            ChatMessage.objects.create(
                conversation=conversation, role='user',
                content=[{'type': 'tool_result', 'tool_use_id': f't{i}',
                          'content': big}])
        ChatMessage.objects.create(conversation=conversation, role='user', content='now what')

        class _Capture:
            def __init__(self):
                self.messages = self
                self.seen = []

            def create(self, **kwargs):
                self.seen.append(copy.deepcopy(kwargs['messages']))
                return _Response([text_block('All set.')], stop_reason='end_turn')

        fake = _Capture()
        result = run_agent_turn(user, conversation, fake)

        # The model saw a within-budget, still-valid context...
        sent = fake.seen[0]
        self.assertLessEqual(compaction_mod.estimate_size(sent), 900)
        self.assertEqual(sent[0]['role'], 'user')
        self.assertIsInstance(sent[0]['content'], str)
        self.assertTrue(_tool_pairs_balanced(sent))
        self.assertTrue(any('All set.' in m['text']
                            for m in result['messages'] if m['role'] == 'assistant'))

        # ...even though the full stored transcript is over budget and every
        # original tool result is still full-fidelity in the DB (compaction
        # only shrinks the in-memory context, never the persisted history).
        stored = ChatMessage.objects.filter(conversation=conversation)
        full = [{'role': m.role, 'content': m.content} for m in stored]
        self.assertGreater(compaction_mod.estimate_size(full), 900)
        stored_results = [
            b['content'] for m in stored if isinstance(m.content, list)
            for b in m.content if b.get('type') == 'tool_result'
        ]
        self.assertEqual(stored_results, [big] * 5)
        self.assertNotIn(compaction_mod.COMPACTED_PLACEHOLDER, stored_results)
