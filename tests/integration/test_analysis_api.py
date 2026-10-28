"""Real SQL-backed API authorization, strict consent and immutable request replay."""

from uuid import uuid4

import httpx
import pytest
from test_analysis_pipeline import stack

from investment_os.api.app import create_app
from investment_os.application.analysis_choices import AnalysisChoicesService
from investment_os.infrastructure.analysis_choices import SqlAnalysisChoices

pytestmark = pytest.mark.integration


async def test_analysis_api_requires_auth_and_literal_consent_without_read_egress(
    database_engine,
):
    sessions, store, providers, _, budget, service, _, command, calls, model_client = await stack(
        database_engine
    )
    app = create_app(
        analysis_start=service,
        analysis_store=store,
        analysis_choices=AnalysisChoicesService(SqlAnalysisChoices(sessions), providers, budget),
        write_api_token="synthetic-analysis-api",
    )
    headers = {"Authorization": "Bearer synthetic-analysis-api"}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            choice = await client.get(
                f"/api/v1/analysis/choices?instrument_id={command.instrument_id}"
            )
            assert choice.status_code == 200 and calls == []
            assert "credential" not in choice.text and "synthetic-not-a-real-key" not in choice.text
            assert choice.json()["roles"] and choice.json()["budget_configured"]
            assert choice.json()["budget_currency"] == "CNY"
            assert choice.json()["task_token_limit"] == 2000000
            body = command.model_dump(mode="json")
            assert (await client.post("/api/v1/analysis/runs", json=body)).status_code == 401
            for consent in [False, 1, "true", None]:
                invalid = await client.post(
                    "/api/v1/analysis/runs",
                    headers=headers,
                    json={**body, "allow_model_calls": consent},
                )
                assert invalid.status_code == 422
            first = await client.post("/api/v1/analysis/runs", headers=headers, json=body)
            assert first.status_code == 202
            run_id = first.json()["run_id"]
            assert first.json()["status"] == "QUEUED" and calls == []
            repeat = await client.post("/api/v1/analysis/runs", headers=headers, json=body)
            assert repeat.json()["run_id"] == run_id
            conflict = await client.post(
                "/api/v1/analysis/runs",
                headers=headers,
                json={**body, "market_source_name": "changed"},
            )
            assert conflict.status_code == 409
            assert (await client.get(f"/api/v1/analysis/runs/{uuid4()}")).status_code == 404
            assert (await client.post(f"/api/v1/analysis/runs/{run_id}/cancel")).status_code == 401
            cancelled = await client.post(f"/api/v1/analysis/runs/{run_id}/cancel", headers=headers)
            assert cancelled.json()["status"] == "CANCELLED"
            assert cancelled.json()["request"] == body
            assert await store.claim_next() is None and calls == []
    finally:
        await model_client.aclose()
