"""Pure 5-field cron validation, matching, and humanization.

``validate_cron`` and ``cron_matches`` are ported from the reference
``code.py`` — notably the standard *day-of-month OR day-of-week* semantics:
when both fields are restricted, a match on either fires the job.
The humanizers produce the friendly schedule / next-fire strings the
Reminders sidebar shows.
"""
from __future__ import annotations

from datetime import datetime, timedelta

FIELD_BOUNDS = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
FIELD_NAMES = ['minute', 'hour', 'day-of-month', 'month', 'day-of-week']
WEEKDAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday',
                 'Thursday', 'Friday', 'Saturday']
MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


# ── Matching ──

def _cron_field_matches(field: str, value: int) -> bool:
    if field == '*':
        return True
    if field.startswith('*/'):
        step = int(field[2:])
        return step > 0 and value % step == 0
    if ',' in field:
        return any(_cron_field_matches(part.strip(), value)
                   for part in field.split(','))
    if '-' in field:
        lo, hi = field.split('-', 1)
        return int(lo) <= value <= int(hi)
    return value == int(field)


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    # cron day-of-week: 0 == Sunday; Python weekday(): 0 == Monday.
    dow_val = (dt.weekday() + 1) % 7
    m = _cron_field_matches(minute, dt.minute)
    h = _cron_field_matches(hour, dt.hour)
    dom_ok = _cron_field_matches(dom, dt.day)
    month_ok = _cron_field_matches(month, dt.month)
    dow_ok = _cron_field_matches(dow, dow_val)
    if not (m and h and month_ok):
        return False
    if dom == '*' and dow == '*':
        return True
    if dom == '*':
        return dow_ok
    if dow == '*':
        return dom_ok
    return dom_ok or dow_ok


# ── Validation ──

def _validate_cron_field(field: str, lo: int, hi: int):
    if field == '*':
        return None
    if field.startswith('*/'):
        step = field[2:]
        if not step.isdigit() or int(step) <= 0:
            return f'Invalid step: {field}'
        return None
    if ',' in field:
        for part in field.split(','):
            err = _validate_cron_field(part.strip(), lo, hi)
            if err:
                return err
        return None
    if '-' in field:
        left, right = field.split('-', 1)
        if not left.isdigit() or not right.isdigit():
            return f'Invalid range: {field}'
        a, b = int(left), int(right)
        if a < lo or a > hi or b < lo or b > hi:
            return f'Range {field} out of bounds [{lo}-{hi}]'
        if a > b:
            return f'Range start > end: {field}'
        return None
    if not field.isdigit():
        return f'Invalid field: {field}'
    value = int(field)
    if value < lo or value > hi:
        return f'Value {value} out of bounds [{lo}-{hi}]'
    return None


def validate_cron(cron_expr: str):
    """Return an error string if invalid, else ``None``."""
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return f'Expected 5 fields, got {len(fields)}'
    for field, (lo, hi), name in zip(fields, FIELD_BOUNDS, FIELD_NAMES):
        err = _validate_cron_field(field, lo, hi)
        if err:
            return f'{name}: {err}'
    return None


# ── Humanization (for the Reminders sidebar) ──

def _fmt_time(hour: int, minute: int) -> str:
    suffix = 'am' if hour < 12 else 'pm'
    h12 = hour % 12 or 12
    if hour == 0 and minute == 0:
        return 'midnight'
    if hour == 12 and minute == 0:
        return 'noon'
    if minute == 0:
        return f'{h12}{suffix}'
    return f'{h12}:{minute:02d}{suffix}'


def humanize_cron(cron_expr: str) -> str:
    """A friendly description, e.g. 'every hour', 'every weekday at 9am'."""
    if validate_cron(cron_expr):
        return cron_expr
    minute, hour, dom, month, dow = cron_expr.strip().split()

    if cron_expr.strip() == '* * * * *':
        return 'every minute'
    if minute.startswith('*/') and (hour, dom, month, dow) == ('*', '*', '*', '*'):
        return f'every {minute[2:]} minutes'
    if hour == '*' and minute == '0' and (dom, month, dow) == ('*', '*', '*'):
        return 'every hour'
    if hour.startswith('*/') and minute == '0' and (dom, month, dow) == ('*', '*', '*'):
        return f'every {hour[2:]} hours'

    # A single fixed time-of-day -> describe the day part.
    if minute.isdigit() and hour.isdigit():
        at = _fmt_time(int(hour), int(minute))
        if month == '*':
            if dom == '*' and dow == '*':
                return f'every day at {at}'
            if dom == '*' and dow == '1-5':
                return f'every weekday at {at}'
            if dom == '*' and dow in ('0,6', '6,0'):
                return f'every weekend at {at}'
            if dom == '*' and dow.isdigit():
                return f'every {WEEKDAY_NAMES[int(dow)]} at {at}'
            if dow == '*' and dom.isdigit():
                return f'on day {dom} at {at}'
        # A specific calendar date (e.g. a one-shot reminder): "Jun 4 at 5:36pm".
        elif month.isdigit() and dom.isdigit() and dow == '*':
            return f'on {MONTH_NAMES[int(month) - 1]} {int(dom)} at {at}'
    return cron_expr.strip()


def next_fire(cron_expr: str, now: datetime, horizon_minutes: int = 11520):
    """Next datetime (after ``now``) the cron matches, scanning minute by
    minute up to ``horizon_minutes`` (~8 days, covers minutely/hourly/daily/
    weekly). Returns ``None`` if none found within the horizon."""
    if validate_cron(cron_expr):
        return None
    cursor = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(horizon_minutes):
        if cron_matches(cron_expr, cursor):
            return cursor
        cursor += timedelta(minutes=1)
    return None


def next_fire_label(cron_expr: str, now: datetime) -> str:
    """A relative label for the next fire, e.g. 'next in ~2h', 'next at 9am'."""
    nxt = next_fire(cron_expr, now)
    if nxt is None:
        return 'scheduled'
    delta = nxt - now
    mins = int(delta.total_seconds() // 60)
    if mins <= 1:
        return 'next in ~1m'
    if mins < 60:
        return f'next in ~{mins}m'
    if mins < 60 * 24:
        return f'next in ~{mins // 60}h'
    return f'next at {_fmt_time(nxt.hour, nxt.minute)}'
