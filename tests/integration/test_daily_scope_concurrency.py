"""Real PostgreSQL membership inserts cannot cross daily scope admission."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from investment_os.application.daily_runtime import DailyError
from investment_os.infrastructure.daily_runtime_setup import capture_scope
from investment_os.infrastructure.persistence.models import (
    InstrumentRecord,
    PortfolioRecord,
    PositionRecord,
)

pytestmark = pytest.mark.integration


def audit():
    return dict(
        created_by="synthetic_daily", correlation_id=uuid4(), schema_version="1.0", metadata_json={}
    )


@pytest.mark.parametrize("change", ["INSERT", "UPDATE", "DELETE"])
async def test_daily_scope_lock_blocks_concurrent_position_writes_until_admission_ends(
    database_engine, change
):
    sessions = async_sessionmaker(database_engine, expire_on_commit=False)
    portfolio_id, instrument_id, position_id, added_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with sessions() as session, session.begin():
        session.add(
            PortfolioRecord(id=portfolio_id, name="synthetic", base_currency="CNY", **audit())
        )
        session.add(
            InstrumentRecord(
                id=instrument_id,
                symbol="DAILY",
                exchange="SSE",
                asset_type="EQUITY",
                currency="CNY",
                **audit(),
            )
        )
        session.add(
            PositionRecord(
                id=position_id, portfolio_id=portfolio_id, instrument_id=instrument_id, **audit()
            )
        )
    async with sessions() as session, session.begin():
        session.add(
            InstrumentRecord(
                id=added_id,
                symbol="ADDED",
                exchange="SSE",
                asset_type="EQUITY",
                currency="CNY",
                **audit(),
            )
        )
    command = SimpleNamespace(
        portfolio_id=portfolio_id,
        portfolio_instrument_ids=(instrument_id,),
        watchlist_instrument_ids=(),
        instrument_ids=(instrument_id,),
        market="SSE",
    )
    entered = asyncio.Event()
    writer_pid = []

    async def writer():
        async with sessions() as session, session.begin():
            writer_pid.append(await session.scalar(text("SELECT pg_backend_pid()")))
            entered.set()
            if change == "INSERT":
                session.add(
                    PositionRecord(portfolio_id=portfolio_id, instrument_id=added_id, **audit())
                )
                await session.flush()
            elif change == "UPDATE":
                await session.execute(
                    text('UPDATE "position" SET core_quantity=7 WHERE id=:id'), {"id": position_id}
                )
            else:
                await session.execute(
                    text('DELETE FROM "position" WHERE id=:id'), {"id": position_id}
                )

    task = None
    try:
        async with sessions() as admission, admission.begin():
            members = await capture_scope(admission, command, lock=True)
            assert len(members) == 1
            task = asyncio.create_task(writer())
            await asyncio.wait_for(entered.wait(), 3)
            async with sessions() as observer:
                async with asyncio.timeout(3):
                    # PostgreSQL owns this lock wait; an asyncio Event cannot signal it.
                    while (  # noqa: ASYNC110
                        await observer.scalar(
                            text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"),
                            {"pid": writer_pid[0]},
                        )
                        != "Lock"
                    ):
                        await asyncio.sleep(0.01)
            assert not task.done()
            assert await capture_scope(admission, command, lock=True) == members
        await asyncio.wait_for(task, 3)
        async with sessions() as session:
            if change == "UPDATE":
                assert (await session.get(PositionRecord, position_id)).core_quantity == 7
                assert await capture_scope(session, command, lock=True) == members
            else:
                with pytest.raises(DailyError, match="DAILY_PORTFOLIO_SCOPE_CHANGED"):
                    await capture_scope(session, command, lock=True)
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
