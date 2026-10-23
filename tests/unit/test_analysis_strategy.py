"""Exact source identity and snapshot compatibility, no database or external calls."""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_analysis_governance import frozen_policy

from investment_os.application.analysis_governance import (
    AnalysisGovernancePlan,
    FrozenAnalysisStrategy,
)
from investment_os.application.analysis_models import digest
from investment_os.application.analysis_orchestrator import freeze_governance
from investment_os.infrastructure.analysis_strategy import runtime_code_ref


def test_code_fingerprint_normalizes_newlines_but_tracks_paths_and_content(tmp_path):
    first = tmp_path / "a.py"
    first.write_bytes(b"x = 1\r\n")
    original = runtime_code_ref(tmp_path)
    first.write_bytes(b"x = 1\n")
    assert runtime_code_ref(tmp_path) == original
    (tmp_path / "ignored.txt").write_bytes(b"not runtime code")
    assert runtime_code_ref(tmp_path) == original
    first.rename(tmp_path / "b.py")
    assert runtime_code_ref(tmp_path) != original
    (tmp_path / "b.py").write_bytes(b"x = 2\n")
    changed = runtime_code_ref(tmp_path)
    assert changed != original
    (tmp_path / "a.py").write_bytes(b"x = 1\n")
    assert runtime_code_ref(tmp_path) != changed


def test_no_source_means_no_invented_code_identity(tmp_path):
    with pytest.raises(ValueError, match="unavailable"):
        runtime_code_ref(tmp_path)


def test_strategy_snapshot_requires_consistent_unapproved_actual_artifacts():
    plan = freeze_governance(frozen_policy())
    rules = {
        "schema_version": "1.0",
        "mode": "TEST_DEFAULT",
        "code_ref": "sha256:" + "a" * 64,
        "formula": plan.formula.model_dump(mode="json"),
        "prompts": [p.model_dump(mode="json") for p in plan.prompts],
    }
    strategy = FrozenAnalysisStrategy(id=uuid4(), version=1, content_hash=digest(rules), **rules)
    payload = {
        **plan.model_dump(),
        "strategy_status": "TEST_DEFAULT",
        "strategy": strategy.model_dump(mode="json"),
    }
    valid = AnalysisGovernancePlan.model_validate(payload)
    assert not valid.allows_new_exposure
    for change in (
        {"strategy_status": "NOT_CONFIGURED"},
        {"strategy": None},
        {"formula": plan.formula.model_copy(update={"version": "bad"})},
    ):
        with pytest.raises(ValidationError):
            AnalysisGovernancePlan.model_validate({**payload, **change})
    for change in (
        {"status": "ACTIVE"},
        {"content_hash": "0" * 64},
        {"approved_by": "synthetic-owner"},
    ):
        with pytest.raises(ValidationError):
            FrozenAnalysisStrategy.model_validate({**strategy.model_dump(mode="json"), **change})


def test_legacy_governance_hash_does_not_gain_a_null_strategy():
    plan = freeze_governance(frozen_policy())
    assert "strategy" not in plan.snapshot()
    assert plan.content_hash == digest(plan.snapshot())
