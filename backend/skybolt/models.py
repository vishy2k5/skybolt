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


class ChoreIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    member_id: int | None = None
    due: date | None = None
    repeat: Literal["none", "daily", "weekly"] = "none"


class ChoreOut(ChoreIn):
    id: int
    done: bool = False
    done_at: str | None = None


class ChoreDone(BaseModel):
    done: bool
