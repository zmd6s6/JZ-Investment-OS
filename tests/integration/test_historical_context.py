"""历史观察在模型前提交, 确定性重算拒绝伪造, 不调用真实来源。"""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_analysis_jobs import configure_markets
from test_analysis_research import configured
from test_execution_context_persistence import ProbeGateway, context_counts
from test_research_previews import Secrets

from investment_os.application.agent_runtime import AgentRuntime
from investment_os.application.analysis_market import AnalysisMarketConfiguration
from investment_os.application.analysis_orchestrator import default_registry
from investment_os.application.committee_runtime import CommitteeRuntime
from investment_os.application.market_data import MarketQuote
from investment_os.application.market_features import DailyMarketBar
from investment_os.application.market_history import MarketHistory
from investment_os.infrastructure.analysis_execution_context import SqlAnalysisExecutionContexts
from investment_os.infrastructure.analysis_market import PlannedMarketDataFactory


@pytest.mark.parametrize("tamper", [False, True])
async def test_historical_context_is_recomputed_committed_and_shared_without_requery(
    database_engine, tamper
):
    sessions, runs, product, port, jobs, inp, _ = await configured(database_engine)
    settings, profiles = await configure_markets(sessions)
    calls = []

    class Source:
        name = "SYNTHETIC"

        async def get_quotes(self, batch, *, as_of):
            calls.append(batch)
            return {
                q.instrument_id: MarketQuote(
                    q.instrument_id,
                    Decimal("10"),
                    q.expected_currency,
                    as_of,
                    self.name,
                    history=MarketHistory(
                        instrument_id=q.instrument_id,
                        reference_at=as_of,
                        status="RECEIVED",
                        bars=tuple(
                            DailyMarketBar(
                                instrument_id=q.instrument_id,
                                as_of=as_of - timedelta(days=19 - i),
                                close="10",
                                previous_close="10",
                                volume_shares="100",
                                turnover="1000",
                            )
                            for i in range(20)
                        ),
                    ),
                )
                for q in batch
            }

    product._market_factory = PlannedMarketDataFactory(
        settings, Secrets(), {"TUSHARE_MARKET": lambda *_: Source()}
    )
    product._markets = AnalysisMarketConfiguration(
        settings, product._market_factory.supported_types
    )

    class Contexts(SqlAnalysisExecutionContexts):
        async def save(self, run_id, valuation, *, worker_token=None):
            if tamper:
                features = valuation.target_historical_features
                valuation = valuation.model_copy(
                    update={
                        "target_historical_features": features.model_copy(
                            update={"mean_turnover": Decimal("999999")}
                        )
                    }
                )
            return await super().save(run_id, valuation, worker_token=worker_token)

    store = Contexts(sessions)
    product._execution_contexts = store
    gateway = ProbeGateway(store)
    product._committee = CommitteeRuntime(
        agent_runtime=AgentRuntime(registry=default_registry(), gateway=gateway)
    )
    inp = replace(inp, market_profile_ids=(profiles[0].id,), include_market_history=True)
    run = await jobs.submit(uuid4(), inp)
    assert run.payload["input_snapshot"]["market_plan"]["history_target_id"] == str(
        inp.instrument_id
    )
    assert await jobs.run_once()
    completed = await runs.get(run.id)
    assert len(calls) == 1 and calls[0][0].include_history
    if tamper:
        assert completed.status == "FAILED" and gateway.calls == 0
        assert await context_counts(sessions) == [0, 0, 0, 0]
        retry = await port.retry_input(run.id)
        assert retry.include_market_history and retry.market_profile_ids == (profiles[0].id,)
    else:
        assert completed.status == "SUCCEEDED" and gateway.calls == 8
        saved = await store.read(run.id)
        features = saved.valuation.target_historical_features
        assert features.sample_count == 20 and features.mean_turnover == 1000
        assert completed.payload["valuation"]["target_historical_features"] == features.model_dump(
            mode="json"
        )
        assert (
            len(gateway.receipts) == 8
            and len({r.runtime_input_hash for r in gateway.receipts}) == 1
        )
        assert (await store.read(run.id)).valuation == saved.valuation and len(calls) == 1
        assert completed.payload["sizing"]["status"] == "BLOCKED"
        assert "target_quantity" not in completed.payload["sizing"]
