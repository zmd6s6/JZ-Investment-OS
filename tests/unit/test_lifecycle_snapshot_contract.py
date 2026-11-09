from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.opportunity_lifecycle import LifecycleSnapshot
from investment_os.domain.enums import InstrumentLifecycleState


def test_unknown_snapshot_cannot_claim_state_or_source():
    with pytest.raises(ValidationError):
        LifecycleSnapshot(
            instrument_id=uuid4(),
            as_of=datetime.now(UTC),
            status="UNKNOWN",
            reason="STATE_NOT_PROVIDED",
            state="BUYABLE",
        )


def test_recorded_snapshot_rejects_future_and_hash_tampering():
    now = datetime.now(UTC)
    values = dict(
        instrument_id=uuid4(),
        as_of=now,
        status="AVAILABLE",
        reason="RECORDED_INITIAL_STATE",
        state=InstrumentLifecycleState.WATCH,
        source_record_id=uuid4(),
        source_version=1,
        effective_at=now,
        recorded_at=now,
    )
    partial = LifecycleSnapshot.model_construct(**values)
    raw = {**values, "source_hash": partial.fingerprint()}
    value = LifecycleSnapshot.model_validate(raw)
    assert value.state == "WATCH"
    with pytest.raises(ValidationError):
        LifecycleSnapshot.model_validate({**raw, "state": "BUYABLE"})
    with pytest.raises(ValidationError):
        LifecycleSnapshot.model_validate({**raw, "source_version": 2})


def test_legacy_event_without_lifecycle_snapshot_keeps_original_payload_hash():
    from test_opportunities import NOW, inputs

    from investment_os.application.opportunities import (
        FunnelRun,
        bound_global_candidates,
        evaluate,
        query_rule_hash,
    )
    from investment_os.infrastructure.opportunities import SqlOpportunityStore, digest
    from investment_os.infrastructure.persistence.models import EventLogRecord

    entry, quote, facts, query = inputs()
    rows, candidates = bound_global_candidates([evaluate(entry, quote, facts, query)], 2)
    run = FunnelRun(
        run_id=query.request_id,
        query=query,
        ingested_at=NOW,
        query_rule_hash=query_rule_hash(query),
        status="COMPLETE",
        rows=rows,
        candidate_ids=candidates,
    )
    raw = run.model_dump(mode="json")
    raw["rows"][0].pop("lifecycle_snapshot")
    original_hash = digest(raw)
    event = EventLogRecord(
        aggregate_type="opportunity_funnel_run",
        aggregate_id=run.run_id,
        payload_json={
            "run": raw,
            "snapshot_hash": original_hash,
            "request_hash": digest(query.model_dump(mode="json")),
        },
    )
    replay = SqlOpportunityStore._read_run(event)
    assert replay.rows[0].lifecycle_snapshot is None
    assert event.payload_json["snapshot_hash"] == original_hash
    assert "lifecycle_snapshot" not in event.payload_json["run"]["rows"][0]
