"""Owner-scoped agent endpoints.

Everything here inherits the base DRF defaults (JWT + ``IsAuthenticated``) and
filters every query by ``owner == request.user`` — a cross-user id yields 404,
never a 403, so existence never leaks (the same rule as the base ``todos`` app).
"""
import logging

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from agent.llm import get_client
from agent.models import Conversation, Memory, Notification, ScheduledJob
from agent.runner import conversation_display, run_agent_turn
from agent.serializers import (
    MemorySerializer,
    NotificationSerializer,
    ScheduledJobSerializer,
)

logger = logging.getLogger('agent')


class ChatMessageViewSet(viewsets.ViewSet):
    """``/api/chat/messages/`` — persisted single-conversation chat.

    * ``GET``  -> ``{'messages': [...display...]}`` (full transcript, in order).
    * ``POST`` -> persist the user message, run a synchronous agent turn, and
      return ``{'messages': [...new...], 'actions': [...]}``. With no API key,
      the user message is still persisted and the call returns ``503``.
    * ``POST .../reset/`` -> clear the transcript back to empty.
    """

    def list(self, request):
        conversation = Conversation.for_user(request.user)
        messages = list(conversation.messages.all())
        return Response({'messages': conversation_display(messages)})

    def create(self, request):
        text = (
            request.data.get('content')
            or request.data.get('message')
            or request.data.get('text')
            or ''
        ).strip()
        if not text:
            return Response(
                {'detail': 'Message content is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        conversation = Conversation.for_user(request.user)
        conversation.messages.create(role='user', content=text)

        client = get_client()
        if client is None:
            # Graceful degradation: the user message is persisted; the rest of
            # the app is unaffected. The frontend surfaces a clear notice.
            return Response(
                {'detail': 'The assistant is unavailable: no ANTHROPIC_API_KEY is '
                           'configured. Your message was saved.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        result = run_agent_turn(request.user, conversation, client)
        return Response(result, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def reset(self, request):
        conversation = Conversation.for_user(request.user)
        conversation.messages.all().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemoryViewSet(mixins.ListModelMixin,
                    mixins.DestroyModelMixin,
                    viewsets.GenericViewSet):
    """``/api/memories/`` — list and forget remembered facts."""

    serializer_class = MemorySerializer

    def get_queryset(self):
        return Memory.objects.filter(owner=self.request.user)


class ScheduledJobViewSet(mixins.ListModelMixin,
                          mixins.DestroyModelMixin,
                          viewsets.GenericViewSet):
    """``/api/scheduled-jobs/`` — list active reminders and cancel them."""

    serializer_class = ScheduledJobSerializer

    def get_queryset(self):
        return ScheduledJob.objects.filter(owner=self.request.user, active=True)


class NotificationViewSet(mixins.ListModelMixin,
                          mixins.UpdateModelMixin,
                          mixins.DestroyModelMixin,
                          viewsets.GenericViewSet):
    """``/api/notifications/`` — list, mark read, clear."""

    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(owner=self.request.user)

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        updated = self.get_queryset().filter(read=False).update(read=True)
        return Response({'updated': updated})

    @action(detail=False, methods=['post'])
    def clear(self, request):
        deleted, _ = self.get_queryset().delete()
        return Response({'deleted': deleted})
