"""Serializers for the agent's read endpoints (sidebar/notification polling).

The chat transcript is serialized by the runner's display derivation, not these
— these power the Reminders, Memory, and Notifications surfaces and add the
human-readable cron strings the Reminders sidebar shows.
"""
from rest_framework import serializers

from django.utils import timezone

from agent.cron import humanize_cron, next_fire_label
from agent.models import Memory, Notification, ScheduledJob


class MemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Memory
        fields = ['id', 'key', 'value', 'created_at', 'updated_at']
        read_only_fields = fields


class ScheduledJobSerializer(serializers.ModelSerializer):
    schedule_human = serializers.SerializerMethodField()
    next_fire = serializers.SerializerMethodField()

    class Meta:
        model = ScheduledJob
        fields = [
            'id', 'cron', 'prompt', 'label', 'recurring', 'active',
            'schedule_human', 'next_fire', 'last_fired_at', 'created_at',
        ]
        read_only_fields = fields

    def get_schedule_human(self, obj):
        return humanize_cron(obj.cron)

    def get_next_fire(self, obj):
        return next_fire_label(obj.cron, timezone.now())


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'title', 'body', 'read', 'created_at']
        read_only_fields = ['id', 'title', 'body', 'created_at']
