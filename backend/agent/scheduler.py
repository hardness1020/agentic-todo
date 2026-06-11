"""Cron firing logic, shared by the ``run_scheduler`` command and the tests.

``run_due_jobs`` is the testable core: it finds active jobs whose cron matches
the current minute, sets the minute marker and deactivates one-shots **before**
firing (the double-fire guard), then runs an agentic turn per job via the
shared runner. Recurring jobs stay active; one-shots deactivate. Jobs only fire
while the scheduler process is running — there is no missed-minute backfill.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from agent.cron import cron_matches
from agent.llm import get_client
from agent.models import ScheduledJob
from agent.runner import run_cron_turn

logger = logging.getLogger('agent')


def run_due_jobs(now=None, client=None):
    """Fire every active job matching ``now`` (default: current time).

    ``client`` may be injected (tests pass a fake); otherwise it is resolved
    once via :func:`get_client`. With no client configured, due jobs are
    skipped with a warning and their markers are left untouched so they can
    fire later once the key is set. Returns the list of fired jobs.
    """
    now = now or timezone.now()
    marker = now.strftime('%Y-%m-%d %H:%M')

    candidates = [
        job for job in ScheduledJob.objects.filter(active=True)
        if cron_matches(job.cron, now) and job.last_fired_marker != marker
    ]
    if not candidates:
        return []

    if client is None:
        client = get_client()
    if client is None:
        logger.warning('Scheduler: %d job(s) due but no API key configured; skipping.',
                       len(candidates))
        return []

    fired = []
    for job in candidates:
        # Stamp the marker and deactivate one-shots BEFORE firing so a crash or
        # an overlapping poll cannot double-fire the same minute.
        job.last_fired_marker = marker
        job.last_fired_at = now
        if not job.recurring:
            job.active = False
        job.save(update_fields=['last_fired_marker', 'last_fired_at', 'active'])

        logger.info('Cron fire job #%s (%s) for user %s', job.id, job.cron, job.owner_id)
        try:
            run_cron_turn(job.owner, job.prompt, client)
        except Exception:  # pragma: no cover - defensive; a turn must not stop others
            logger.exception('Cron job #%s turn failed', job.id)
        fired.append(job)
    return fired
