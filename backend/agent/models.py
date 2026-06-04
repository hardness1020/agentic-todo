"""Owner-scoped models backing the AI agent.

Every model carries an ``owner`` FK exactly like ``todos.Todo`` — per-user
isolation is enforced structurally (querysets are always filtered by
``owner == request.user``) just as in the base app.
"""
from django.conf import settings
from django.db import models


class Conversation(models.Model):
    """One persisted chat thread per user (history seeds context each turn)."""

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversation',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def for_user(cls, user):
        conversation, _ = cls.objects.get_or_create(owner=user)
        return conversation

    def __str__(self):
        return f'Conversation<{self.owner_id}>'


class ChatMessage(models.Model):
    """A single message in the Anthropic transcript.

    ``content`` stores the native Anthropic shape so the transcript can be
    replayed verbatim across turns:
      * ``role='user'``      -> a plain string (the user's prompt) **or** a
                                list of ``tool_result`` blocks.
      * ``role='assistant'`` -> a list of ``text`` / ``tool_use`` blocks.
    """

    ROLE_CHOICES = (('user', 'user'), ('assistant', 'assistant'))

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.role} #{self.pk}'


class Memory(models.Model):
    """A durable per-user fact, upserted by ``(owner, key)``."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memories',
    )
    key = models.CharField(max_length=128)
    value = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'key'], name='unique_owner_memory_key'
            ),
        ]

    def __str__(self):
        return f'{self.key}={self.value[:40]}'


class ScheduledJob(models.Model):
    """A 5-field cron job that fires an agentic turn for its owner.

    ``last_fired_marker`` (``"%Y-%m-%d %H:%M"``) is the minute-granular
    double-fire guard: the scheduler stamps it before firing so a job runs at
    most once per matching minute even across overlapping polls.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='scheduled_jobs',
    )
    cron = models.CharField(max_length=128)
    prompt = models.TextField()
    label = models.CharField(max_length=255)
    recurring = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    last_fired_marker = models.CharField(max_length=20, blank=True, default='')
    last_fired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.cron} -> {self.label}'


class Notification(models.Model):
    """A message surfaced in the dashboard (bell popover + toast)."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default='')
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title
