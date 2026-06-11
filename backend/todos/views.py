from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from todos.models import Todo
from todos.serializers import TodoSerializer


class TodoViewSet(viewsets.ModelViewSet):
    serializer_class = TodoSerializer

    def get_queryset(self):
        # Scope every query to the authenticated user; a mismatch yields 404.
        return Todo.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Open / done / total counts for the dashboard stat cards."""
        qs = self.get_queryset()
        total = qs.count()
        done = qs.filter(completed=True).count()
        return Response({'open': total - done, 'done': done, 'total': total})
