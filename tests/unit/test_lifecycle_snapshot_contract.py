from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.opportunity_lifecycle import LifecycleSnapshot


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
        state="WATCH",
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
