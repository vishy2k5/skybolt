"""Expand iCalendar recurrence lines (as Google sends them) in local wall-clock time."""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dateutil.rrule import rruleset, rrulestr

MAX_OCCURRENCES = 1000


def _local(dt: datetime) -> datetime:
    return dt.astimezone().replace(tzinfo=None)


def _ical_dt(value: str, tzid: str | None = None) -> datetime:
    if len(value) == 8:  # all-day date
        return datetime.strptime(value, "%Y%m%d")
    if value.endswith("Z"):
        return _local(datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc))
    dt = datetime.strptime(value, "%Y%m%dT%H%M%S")
    return _local(dt.replace(tzinfo=ZoneInfo(tzid))) if tzid else dt


def _build(lines: str, start: datetime) -> rruleset:
    rs = rruleset()
    for line in lines.splitlines():
        name, _, value = line.partition(":")
        key, *params = name.split(";")
        key = key.upper()
        if key == "RRULE":  # UNTIL comes in UTC; make it local like dtstart
            value = re.sub(r"UNTIL=(\d{8}T\d{6}Z)",
                           lambda m: "UNTIL=" + _ical_dt(m.group(1)).strftime("%Y%m%dT%H%M%S"), value)
            rs.rrule(rrulestr(value, dtstart=start))
        elif key in ("EXDATE", "RDATE"):
            tzid = next((p.split("=", 1)[1] for p in params if p.upper().startswith("TZID=")), None)
            for v in filter(None, (x.strip() for x in value.split(","))):
                dt = _ical_dt(v, tzid)
                if len(v) == 8:
                    dt = dt.replace(hour=start.hour, minute=start.minute)
                (rs.exdate if key == "EXDATE" else rs.rdate)(dt)
    return rs


def occurrences(lines: str, start: datetime, dur: timedelta, ws: datetime, we: datetime) -> list[datetime]:
    """Start times of the occurrences that overlap [ws, we)."""
    out = []
    for s in _build(lines, start).xafter(ws - dur, count=MAX_OCCURRENCES, inc=True):
        if s >= we:
            break
        if s + dur >= ws:
            out.append(s)
    return out
