"""Long-running poller that fires due cron jobs agentically.

Run alongside ``runserver``::

    python manage.py run_scheduler

Polls every ``AGENT_SCHEDULER_INTERVAL`` seconds (default 30), matching cron at
minute granularity. Jobs only fire while this process runs (no backfill). With
no ``ANTHROPIC_API_KEY`` set, it logs a warning and idles — the rest of the app
keeps working.
"""
import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from agent.llm import get_client
from agent.scheduler import run_due_jobs

logger = logging.getLogger('agent')


class Command(BaseCommand):
    help = 'Poll and agentically fire due scheduled cron jobs.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval', type=int, default=None,
            help='Override poll interval in seconds.',
        )
        parser.add_argument(
            '--once', action='store_true',
            help='Fire due jobs a single time and exit (useful for testing).',
        )

    def handle(self, *args, **options):
        interval = options['interval'] or getattr(settings, 'AGENT_SCHEDULER_INTERVAL', 30)

        if not get_client():
            self.stdout.write(self.style.WARNING(
                'No ANTHROPIC_API_KEY configured — scheduler will idle and skip '
                'firing jobs. The rest of the app is unaffected.'
            ))

        if options['once']:
            fired = run_due_jobs()
            self.stdout.write(f'Fired {len(fired)} job(s).')
            return

        self.stdout.write(self.style.SUCCESS(
            f'Scheduler running (every {interval}s). Press Ctrl-C to stop.'
        ))
        try:
            while True:
                try:
                    fired = run_due_jobs()
                    if fired:
                        self.stdout.write(f'Fired {len(fired)} job(s).')
                except Exception:  # pragma: no cover - keep the loop alive
                    logger.exception('Scheduler poll failed')
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write('\nScheduler stopped.')
