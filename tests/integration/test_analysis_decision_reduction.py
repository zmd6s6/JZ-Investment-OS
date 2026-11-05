"""Risk Veto reduction exception remains explicit and append-only through the bridge."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_analysis_decision_bridge import complete_analysis

from investment_os.infrastructure.analysis_decision_bridge import SqlAnalysisDecisionBridge
from investment_os.infrastructure.persistence.models import (
    InvestmentDecisionRecord,
    PositionSizingRunRecord,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("action", ["REDUCE", "EXIT"])
async def test_veto_reduction_bridge_requires_confirmation_and_preserves_original_sizer(
    database_engine, action
):
    (
        sessions,
        _store,
        original,
        command,
        _calls,
        client,
        _qualification,
        _strategy,
    ) = await complete_analysis(
        database_engine,
        liquidity="0",
        candidate_action=action,
    )
    try:
        assert original.risk_sizing.risk_gate == "VETO"
        assert original.risk_sizing.sizing_status == "COMPUTED"
        bridge = SqlAnalysisDecisionBridge(sessions)
        blocked = await bridge.prepare(command)
        assert blocked.status == "BLOCKED"
        assert "DECISION_RISK_REDUCTION_CONFIRMATION_REQUIRED" in blocked.blockers
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(InvestmentDecisionRecord))
                == 0
            )
            assert (
                await session.scalar(select(func.count()).select_from(PositionSizingRunRecord)) == 1
            )
        prepared = await bridge.prepare(
            command.model_copy(
                update={
                    "request_id": uuid4(),
                    "expected_revision": 1,
                    "confirm_risk_reduction_exception": True,
                }
            )
        )
        assert prepared.status == "PENDING_APPROVAL", prepared.model_dump(mode="json")
        async with sessions() as session:
            source = await session.get(PositionSizingRunRecord, original.risk_sizing.sizing_run_id)
            decision = await session.get(InvestmentDecisionRecord, prepared.decision_id)
            copy = await session.get(PositionSizingRunRecord, decision.position_sizing_run_id)
            assert source.id != copy.id
            assert source.input_json.get("risk_reduction_exception_recorded") is not True
            assert copy.input_json["risk_reduction_exception_recorded"] is True
            assert copy.metadata_json["source_sizing_run_id"] == str(source.id)
            assert copy.output_json == source.output_json
            assert (
                await session.scalar(select(func.count()).select_from(PositionSizingRunRecord)) == 2
            )
    finally:
        await client.aclose()
