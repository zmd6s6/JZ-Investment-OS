"""Policy selection, frozen queued inputs and fail-closed governance, synthetic only."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_analysis_jobs import jobs_setup

from investment_os.api.app import create_app
from investment_os.application.analysis_governance import policy_config_hash
from investment_os.application.analysis_orchestrator import AnalysisRunResult
from investment_os.application.errors import ApplicationError
from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.infrastructure.analysis_policy import SqlAnalysisPolicies
from investment_os.infrastructure.persistence.models import (
    AnalysisJobRecord,
    InvestmentPolicyRecord,
    InvestmentPolicyVersionRecord,
    PortfolioRecord,
)

TEST_POLICY_DOCUMENT = Path("config/investment-policy.test-default.json").read_text(
    encoding="utf-8"
)


async def approved_policy(sessions, name="合成政策", cap="8"):
    payload = json.loads(TEST_POLICY_DOCUMENT)
    payload["metadata"] = {"name": name, "status": "ACTIVE"}
    payload["position"]["single_instrument_max_pct"] = cap
    config = InvestmentPolicySchema.model_validate_json(json.dumps(payload))
    now = datetime.now(UTC)
    policy_id, version_id = uuid4(), uuid4()
    async with sessions() as session, session.begin():
        policy = InvestmentPolicyRecord(
            id=policy_id,
            name=name,
            status="ACTIVE",
            current_version_id=None,
            created_by="synthetic",
            correlation_id=uuid4(),
        )
        session.add(policy)
        await session.flush()
        session.add(
            InvestmentPolicyVersionRecord(
                id=version_id,
                policy_id=policy_id,
                version=1,
                config_json=config.model_dump(mode="json"),
                content_hash=policy_config_hash(config),
                effective_from=now - timedelta(days=1),
                approved_by="synthetic-owner",
                approved_at=now - timedelta(days=2),
                created_by="synthetic",
                correlation_id=uuid4(),
                metadata_json={"approved_by_actor": "HUMAN"},
            )
        )
        await session.flush()
        policy.current_version_id = version_id
    return policy_id, version_id


async def test_policy_review_and_prepared_inputs_use_same_test_document(database_engine):
    sessions, _, runs, product, _, jobs, inp = await jobs_setup(database_engine)
    prepared = await product.prepare(inp)
    app = create_app(
        analysis_product_service=product, analysis_run_service=runs, analysis_job_service=jobs
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        review = await client.get(
            "/api/v1/policy/review", params={"portfolio_id": str(inp.portfolio_id)}
        )
        assert review.status_code == 200
        body = review.json()
        assert (
            body["is_test_default"]
            and body["active_policy_version"]
            == prepared.request.policy_version_label
            == "TEST_DEFAULT"
        )
        assert (
            body["snapshot"]["content_hash"]
            == prepared.snapshot["governance"]["policy"]["content_hash"]
        )
        assert {entry["key"]: entry["value"] for entry in body["limits"]}[
            "single_instrument_max_pct"
        ] == "8"
    assert (
        await SqlAnalysisPolicies(sessions).policy(inp.portfolio_id, as_of=prepared.request.as_of)
    ).label == "TEST_DEFAULT"


async def test_queued_policy_version_does_not_drift_and_retry_refreezes_current_version(
    database_engine, monkeypatch
):
    sessions, _, runs, product, _, jobs, inp = await jobs_setup(database_engine)
    policy_id, first_id = await approved_policy(sessions)
    original = await jobs.submit(uuid4(), inp)
    frozen = original.payload["input_snapshot"]["governance"]
    assert frozen["policy"]["policy_version_id"] == str(first_id)
    second_id = uuid4()
    config = InvestmentPolicySchema.model_validate_json(json.dumps(frozen["policy"]["config"]))
    next_payload = config.model_dump(mode="json")
    next_payload["position"]["single_instrument_max_pct"] = "6"
    next_config = InvestmentPolicySchema.model_validate_json(json.dumps(next_payload))
    async with sessions() as session, session.begin():
        session.add(
            InvestmentPolicyVersionRecord(
                id=second_id,
                policy_id=policy_id,
                version=2,
                config_json=next_config.model_dump(mode="json"),
                content_hash=policy_config_hash(next_config),
                effective_from=datetime.now(UTC) - timedelta(hours=1),
                approved_by="synthetic-owner",
                approved_at=datetime.now(UTC) - timedelta(hours=2),
                created_by="synthetic",
                correlation_id=uuid4(),
                metadata_json={"approved_by_actor": "HUMAN"},
            )
        )
        row = await session.get(InvestmentPolicyRecord, policy_id)
        row.current_version_id = second_id
    calls = []

    async def execute(request, **kwargs):
        calls.append(request)
        assert request.governance.policy.policy_version_id == first_id
        assert request.governance.policy.config.position.single_instrument_max_pct == 8
        assert request.input_snapshot_hash == original.payload["input_snapshot"]["input_hash"]
        return AnalysisRunResult("FAILED", None, "SYNTHETIC", "合成结束")

    monkeypatch.setattr("investment_os.application.analysis_product.execute_analysis", execute)
    assert await jobs.run_once() and len(calls) == 1
    assert (await runs.get(original.id)).payload["input_snapshot"]["governance"] == frozen
    retried = await jobs.retry(original.id, uuid4())
    assert retried.payload["retry_of"] == str(original.id)
    assert retried.payload["input_snapshot"]["governance"]["policy"]["policy_version_id"] == str(
        second_id
    )
    assert retried.policy_version_label.endswith("@2")
    assert (await product.review_policy(inp.portfolio_id)).policy_version_id == second_id


async def test_explicit_portfolio_binding_wins_but_unbound_ambiguous_policy_is_rejected(
    database_engine,
):
    sessions, _, _, product, _, _, inp = await jobs_setup(database_engine)
    first, version = await approved_policy(sessions, "合成组合政策")
    await approved_policy(sessions, "合成其他政策")
    with pytest.raises(ApplicationError):
        await product.prepare(inp)
    async with sessions() as session, session.begin():
        portfolio = await session.get(PortfolioRecord, inp.portfolio_id)
        portfolio.policy_id = first
    assert (await product.prepare(inp)).request.governance.policy.policy_version_id == version
    assert (await product.review_policy(inp.portfolio_id)).policy_version_id == version


@pytest.mark.parametrize(
    "bad",
    [
        "approval",
        "actor",
        "hash",
        "future",
        "missing_version",
        "foreign_version",
        "bound_inactive",
        "invalid_config",
    ],
)
async def test_invalid_policy_rejects_submission_before_paid_calls_without_fallback(
    database_engine, bad
):
    sessions, _, runs, product, _, jobs, inp = await jobs_setup(database_engine)
    policy_id, version_id = await approved_policy(sessions)
    foreign = await approved_policy(sessions, "合成他方政策") if bad == "foreign_version" else None
    async with sessions() as session, session.begin():
        portfolio = await session.get(PortfolioRecord, inp.portfolio_id)
        portfolio.policy_id = policy_id
        policy = await session.get(InvestmentPolicyRecord, policy_id)
        version = await session.get(InvestmentPolicyVersionRecord, version_id)
        # Create malformed *new* fixture rows only; versions are already immutable.
        values = {
            "config_json": version.config_json,
            "content_hash": version.content_hash,
            "approved_by": version.approved_by,
            "approved_at": version.approved_at,
            "effective_from": version.effective_from,
            "metadata_json": dict(version.metadata_json),
        }
        if bad == "approval":
            values["approved_by"] = None
        elif bad == "actor":
            values["metadata_json"] = {}
        elif bad == "hash":
            values["content_hash"] = "0" * 64
        elif bad == "future":
            values["effective_from"] = datetime.now(UTC) + timedelta(days=1)
        elif bad == "invalid_config":
            values["config_json"] = {"unrecognized": "synthetic"}
        invalid_id = uuid4()
        session.add(
            InvestmentPolicyVersionRecord(
                id=invalid_id,
                policy_id=policy_id,
                version=2,
                created_by="synthetic",
                correlation_id=uuid4(),
                **values,
            )
        )
        await session.flush()
        policy.current_version_id = (
            None if bad == "missing_version" else foreign[1] if foreign else invalid_id
        )
        if bad == "bound_inactive":
            policy.status = "RETIRED"
    with pytest.raises(ApplicationError) as failure:
        await jobs.submit(uuid4(), inp)
    assert failure.value.code.value == "ANALYSIS_POLICY_INVALID"
    assert product._committee is None  # Reaching a model would fail, never pass silently.
    app = create_app(
        analysis_product_service=product,
        analysis_run_service=runs,
        analysis_job_service=jobs,
        write_api_token="synthetic-policy-auth",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/analysis-jobs",
            headers={"Authorization": "Bearer synthetic-policy-auth"},
            json={
                "request_id": str(uuid4()),
                "portfolio_id": str(inp.portfolio_id),
                "instrument_id": str(inp.instrument_id),
            },
        )
        assert (
            response.status_code == 422 and response.json()["detail"] == "ANALYSIS_POLICY_INVALID"
        )
        review = await client.get(
            "/api/v1/policy/review", params={"portfolio_id": str(inp.portfolio_id)}
        )
        assert review.json()["policy_status"] == "INVALID" and review.json()["limits"] == []
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AnalysisJobRecord)) == 0
