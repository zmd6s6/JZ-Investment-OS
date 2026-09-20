"""Explicit market-calendar schedule contracts for durable job orchestration."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
SHANGHAI = ZoneInfo("Asia/Shanghai")


class MarketVenue(StrEnum):
    """Supported synthetic calendar venues; exchange dates are always caller-supplied."""

    US_EQUITIES = "US_EQUITIES"
    SSE = "SSE"
    SZSE = "SZSE"

    @property
    def timezone(self) -> ZoneInfo:
        if self is MarketVenue.US_EQUITIES:
            return NEW_YORK
        return SHANGHAI


class JobCadence(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


@dataclass(frozen=True, slots=True)
class JobDefinition:
    """A named workflow that is eligible at a specific market-session boundary."""

    name: str
    cadence: JobCadence

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("job name must not be blank")


DAILY_JOB = JobDefinition("daily", JobCadence.DAILY)
WEEKLY_JOB = JobDefinition("weekly", JobCadence.WEEKLY)
MONTHLY_JOB = JobDefinition("monthly", JobCadence.MONTHLY)
QUARTERLY_JOB = JobDefinition("quarterly", JobCadence.QUARTERLY)


@dataclass(frozen=True, slots=True)
class TradingSession:
    """A known market session; callers must supply every tradable date explicitly."""

    business_date: date
    close_at: time

    def scheduled_for(self, *, market_timezone: ZoneInfo) -> datetime:
        return datetime.combine(
            self.business_date, self.close_at, tzinfo=market_timezone
        ).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ExplicitTradingCalendar:
    """Calendar data with no implicit weekday or server-time assumptions."""

    sessions: tuple[TradingSession, ...]
    venue: MarketVenue = MarketVenue.US_EQUITIES

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

    @property
    def timezone(self) -> ZoneInfo:
        return self.venue.timezone

    def contains(self, session: TradingSession) -> bool:
        return self.session_for(session.business_date) == session

    def is_final_session_of_week(self, session: TradingSession) -> bool:
        return not any(
            candidate.business_date.isocalendar()[:2] == session.business_date.isocalendar()[:2]
            and candidate.business_date > session.business_date
            for candidate in self.sessions
        )

    def is_final_session_of_month(self, session: TradingSession) -> bool:
        return not any(
            candidate.business_date.year == session.business_date.year
            and candidate.business_date.month == session.business_date.month
            and candidate.business_date > session.business_date
            for candidate in self.sessions
        )

    def is_final_session_of_quarter(self, session: TradingSession) -> bool:
        quarter = (session.business_date.month - 1) // 3
        return not any(
            candidate.business_date.year == session.business_date.year
            and (candidate.business_date.month - 1) // 3 == quarter
            and candidate.business_date > session.business_date
            for candidate in self.sessions
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


def daily_job_for_session(
    *, calendar: ExplicitTradingCalendar, name: str, session: TradingSession, as_of: datetime
) -> ScheduledJob:
    """Create a Daily invocation only from a known session and business as-of instant."""

    return _job_for_session(
        definition=JobDefinition(name=name, cadence=JobCadence.DAILY),
        calendar=calendar,
        session=session,
        as_of=as_of,
    )


def _job_for_session(
    *,
    definition: JobDefinition,
    calendar: ExplicitTradingCalendar,
    session: TradingSession,
    as_of: datetime,
) -> ScheduledJob:
    """Bind a named cadence to a market session after validating business-time boundaries."""

    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if not calendar.contains(session):
        raise ValueError("session must be present in the explicit trading calendar")
    scheduled_for = session.scheduled_for(market_timezone=calendar.timezone)
    if as_of.astimezone(calendar.timezone).date() != session.business_date:
        raise ValueError("as_of must belong to the supplied market business date")
    return ScheduledJob(
        name=definition.name,
        cadence=definition.cadence,
        as_of=as_of.astimezone(UTC),
        scheduled_for=scheduled_for,
    )


def jobs_for_session(
    *, calendar: ExplicitTradingCalendar, session: TradingSession
) -> tuple[ScheduledJob, ...]:
    """Plan Daily through Quarterly jobs at explicit final market-session boundaries only."""

    if not calendar.contains(session):
        raise ValueError("session must be present in the explicit trading calendar")
    as_of = session.scheduled_for(market_timezone=calendar.timezone)
    definitions = [DAILY_JOB]
    if calendar.is_final_session_of_week(session):
        definitions.append(WEEKLY_JOB)
    if calendar.is_final_session_of_month(session):
        definitions.append(MONTHLY_JOB)
    if calendar.is_final_session_of_quarter(session):
        definitions.append(QUARTERLY_JOB)
    return tuple(
        _job_for_session(definition=definition, calendar=calendar, session=session, as_of=as_of)
        for definition in definitions
    )
