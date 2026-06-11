"""Agent API routes, included additively under ``/api/`` by ``config.urls``."""
from rest_framework.routers import DefaultRouter

from agent.views import (
    ChatMessageViewSet,
    MemoryViewSet,
    NotificationViewSet,
    ScheduledJobViewSet,
)

router = DefaultRouter()
router.register('chat/messages', ChatMessageViewSet, basename='chat-message')
router.register('memories', MemoryViewSet, basename='memory')
router.register('scheduled-jobs', ScheduledJobViewSet, basename='scheduled-job')
router.register('notifications', NotificationViewSet, basename='notification')

urlpatterns = router.urls
