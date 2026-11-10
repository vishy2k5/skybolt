from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    start: datetime
    end: datetime
    all_day: bool = False
    description: str = Field(default="", max_length=10000)
    location: str = Field(default="", max_length=1000)
    calendar_id: str = "local"
    member_id: int | None = None
    repeat: Literal["none", "daily", "weekly", "monthly", "yearly", "custom"] = "none"  # custom: rule set in Google

    @model_validator(mode="after")
    def _check_range(self):
        if self.end < self.start:
            raise ValueError("end must not be before start")
        return self


class EventOut(EventIn):
    id: int
    google_id: str | None = None
    series_gid: str | None = None  # set when this is one changed occurrence of a Google series


class MemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class MemberOut(BaseModel):
    id: int
    name: str
    color: str


TIME_RE = r"^([01]\d|2[0-3]):[0-5]\d$"  # HH:MM, 24-hour


class ChoreIn(BaseModel):
    """member_id None means the whole family ("Everyone"). No start_time means an all-day chore."""
    title: str = Field(min_length=1, max_length=200)
    member_id: int | None = None
    due: date | None = None  # the day, or the first day of a repeating chore
    start_time: str | None = Field(default=None, pattern=TIME_RE)
    end_time: str | None = Field(default=None, pattern=TIME_RE)
    repeat: Literal["none", "daily", "weekly"] = "none"

    @model_validator(mode="after")
    def _check(self):
        if self.end_time and not self.start_time:
            raise ValueError("end_time needs a start_time")
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        if self.due is None and (self.start_time or self.repeat != "none"):
            raise ValueError("a timed or repeating chore needs a date")
        return self


class ChoreOut(ChoreIn):
    id: int
    day: date | None = None  # which day this occurrence is on (repeating chores appear once per day)
    done: bool = False
    done_at: str | None = None


class ChoreDone(BaseModel):
    done: bool
    day: date | None = None  # required for repeating chores: which day was ticked off
