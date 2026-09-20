"""Explicit market-calendar schedule contracts for durable job orchestration."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


class JobCadence(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


@dataclass(frozen=True, slots=True)
class TradingSession:
    """A known market session; callers must supply every tradable date explicitly."""

    business_date: date
    close_at: time

    def scheduled_for(self) -> datetime:
        return datetime.combine(self.business_date, self.close_at, tzinfo=NEW_YORK).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ExplicitTradingCalendar:
    """Calendar data with no implicit weekday or server-time assumptions."""

    sessions: tuple[TradingSession, ...]

    def __post_init__(self) -> None:
        dates = [session.business_date for session in self.sessions]
        if len(set(dates)) != len(dates):
            raise ValueError("trading calendar cannot contain duplicate business dates")
        if any(session.close_at.tzinfo is not None for session in self.sessions):
            raise ValueError("market close time must be a timezone-naive wall-clock time")

    def session_for(self, business_date: date) -> TradingSession | None:
        return next(
            (session for session in self.sessions if session.business_date == business_date), None
        )


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    """One durable business invocation, keyed by job name and explicit market session."""

    name: str
    cadence: JobCadence
    as_of: datetime
    scheduled_for: datetime

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("job name must not be blank")
        if self.as_of.tzinfo is None or self.scheduled_for.tzinfo is None:
            raise ValueError("as_of and scheduled_for must be timezone-aware")
        if self.as_of > self.scheduled_for:
            raise ValueError("as_of cannot be after the market session close")

    @property
    def idempotency_key(self) -> str:
        return f"{self.name}:{self.as_of.astimezone(UTC).isoformat()}"


def daily_job_for_session(*, name: str, session: TradingSession, as_of: datetime) -> ScheduledJob:
    """Create a Daily invocation only from a known session and business as-of instant."""

    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    scheduled_for = session.scheduled_for()
    if as_of.astimezone(NEW_YORK).date() != session.business_date:
        raise ValueError("as_of must belong to the supplied market business date")
    return ScheduledJob(
        name=name,
        cadence=JobCadence.DAILY,
        as_of=as_of.astimezone(UTC),
        scheduled_for=scheduled_for,
    )
