from datetime import UTC, datetime
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from investment_os.api.app import create_app
from investment_os.infrastructure.report_delivery import DailyReportRead


class StubDailyReportReader:
    def __init__(self, report: DailyReportRead | None, error: Exception | None = None) -> None:
        self._report = report
        self._error = error
        self.requested_as_of: datetime | None = None

    async def latest(self) -> DailyReportRead | None:
        if self._error is not None:
            raise self._error
        return self._report

    async def as_of(self, as_of: datetime) -> DailyReportRead | None:
        self.requested_as_of = as_of
        return await self.latest()


def _report() -> DailyReportRead:
    return DailyReportRead(
        id=uuid4(),
        as_of=datetime(2026, 9, 20, 20, 0, tzinfo=UTC),
        content_hash="a" * 64,
        rendered_markdown="# Daily Report\n\n> **SIMULATION / NO AUTO TRADE**",
        simulation_only=True,
    )


async def test_latest_daily_report_is_read_only_and_keeps_simulation_state() -> None:
    app = create_app(daily_report_reader=StubDailyReportReader(_report()))  # type: ignore[arg-type]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/reports/daily/latest")

    assert response.status_code == 200
    assert response.json()["simulation_only"] is True
    assert "SIMULATION / NO AUTO TRADE" in response.json()["rendered_markdown"]


async def test_latest_daily_report_fails_closed_when_absent_or_malformed() -> None:
    missing = create_app(daily_report_reader=StubDailyReportReader(None))  # type: ignore[arg-type]
    malformed = create_app(  # type: ignore[arg-type]
        daily_report_reader=StubDailyReportReader(None, ValueError("malformed"))
    )

    async with AsyncClient(transport=ASGITransport(app=missing), base_url="http://test") as client:
        missing_response = await client.get("/api/v1/reports/daily/latest")
    async with AsyncClient(
        transport=ASGITransport(app=malformed), base_url="http://test"
    ) as client:
        malformed_response = await client.get("/api/v1/reports/daily/latest")

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "daily_report_not_found"
    assert malformed_response.status_code == 503
    assert malformed_response.json()["detail"] == "daily_report_unavailable"


async def test_daily_report_as_of_replays_only_the_requested_business_time() -> None:
    reader = StubDailyReportReader(_report())
    app = create_app(daily_report_reader=reader)  # type: ignore[arg-type]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/reports/daily", params={"as_of": "2026-09-20T20:00:00Z"}
        )

    assert response.status_code == 200
    assert reader.requested_as_of == datetime(2026, 9, 20, 20, 0, tzinfo=UTC)
    assert response.json()["as_of"] == "2026-09-20T20:00:00Z"
