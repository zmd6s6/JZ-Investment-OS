"""Calendar transport keeps authentication and never echoes untrusted uploaded content."""

from uuid import uuid4

import httpx
from fastapi import FastAPI

from investment_os.api.calendar_routes import create_calendar_router
from investment_os.api.write_auth import WriteApiAuthMiddleware
from investment_os.application.calendar_product import CalendarProductService


class UnavailablePort:
    async def overview(self):
        raise RuntimeError("synthetic-private-fragment")

    async def import_calendar(self, command, preview):
        raise AssertionError("preview must not write")

    async def set_mode(self, venue, command):
        raise AssertionError("invalid mode must not write")


def app(service):
    value = FastAPI()
    value.add_middleware(WriteApiAuthMiddleware, token="synthetic-calendar-only")
    value.include_router(create_calendar_router(service))
    return value


async def test_calendar_preview_requires_auth_and_does_not_write():
    service = CalendarProductService(UnavailablePort())
    payload = {
        "venue": "SSE",
        "source_name": "合成来源",
        "source_version": "fixture-v1",
        "confirmed_source": True,
        "csv_text": "business_date,close_at\n2026-10-23,15:00",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(service)), base_url="http://test"
    ) as client:
        assert (await client.post("/api/v1/calendar/preview", json=payload)).status_code == 401
        response = await client.post(
            "/api/v1/calendar/preview",
            json=payload,
            headers={"Authorization": "Bearer synthetic-calendar-only"},
        )
        assert response.status_code == 200
        assert response.json()["sessions"][0]["close_at_utc"] == "2026-10-23T07:00:00Z"


async def test_calendar_unavailable_and_invalid_fields_are_sanitized():
    service = CalendarProductService(UnavailablePort())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(service)), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/calendar")
        assert response.status_code == 503 and "synthetic-private-fragment" not in response.text
        response = await client.post(
            "/api/v1/calendar/imports",
            json={"csv_text": "synthetic-secret-fragment"},
            headers={"Authorization": "Bearer synthetic-calendar-only"},
        )
        assert response.status_code == 422 and "synthetic-secret-fragment" not in response.text
        response = await client.post(
            "/api/v1/calendar/SSE/mode",
            json={
                "request_id": str(uuid4()),
                "expected_version": 1,
                "enabled": True,
                "status_only_acknowledgement": 1,
            },
            headers={"Authorization": "Bearer synthetic-calendar-only"},
        )
        assert response.status_code == 422
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(None)), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/calendar")
        assert (
            response.status_code == 503
            and response.json()["detail"]["code"] == "CALENDAR_SERVICE_UNAVAILABLE"
        )
