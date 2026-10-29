"""Human confirmation and exact manual facts are mandatory at the typed boundary."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.decision_center import (
    HumanCommand,
    ManualExecutionCommand,
    clean_text,
    command_hash,
)


def values():
    return {
        "request_id": uuid4(),
        "expected_revision": 1,
        "actor_id": "synthetic-human",
        "comment": "明确人工选择",
        "confirmed": True,
    }


@pytest.mark.parametrize(
    "field,value",
    [("confirmed", False), ("actor_id", "\x00\n"), ("comment", "\x00\n"), ("expected_revision", 0)],
)
def test_missing_explicit_human_confirmation_never_builds_command(field, value):
    command = values()
    command[field] = value
    with pytest.raises(ValidationError):
        HumanCommand(**command)


@pytest.mark.parametrize(
    "field,value",
    [
        ("fees", "-0.01"),
        ("fees", "NaN"),
        ("fees", "1e30"),
        ("price", "1e30"),
        ("quantity", "0.0000000000000000001"),
        ("quantity", "Infinity"),
        ("quantity", "0"),
        ("price", "0"),
        ("executed_at", "2026-01-01T00:00:00"),
        ("external_reference", "\x00"),
        ("note", "\x00"),
    ],
)
def test_manual_fee_time_quantity_and_reference_boundaries(field, value):
    command = {
        **values(),
        "approval_id": uuid4(),
        "quantity": "1",
        "price": "10.05",
        "fees": "0",
        "executed_at": "2026-10-28T10:00:00Z",
        "external_reference": "synthetic",
        "note": "manual",
    }
    command[field] = value
    with pytest.raises(ValidationError):
        ManualExecutionCommand(**command)


def test_exact_fee_and_idempotency_identity_preserve_user_input():
    command = HumanCommand(**values())
    assert command_hash("APPROVE", command) == command_hash("APPROVE", command)
    assert command_hash("REJECT", command) != command_hash("APPROVE", command)
    assert clean_text(" actor\x00\nname ") == "actor name"
