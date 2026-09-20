from datetime import UTC, datetime
from uuid import uuid4

import pytest

from investment_os.application.reports import (
    HumanReport,
    ReportKind,
    ReportStatement,
    ReportStatementKind,
)


def test_report_renders_provenance_labels_and_simulation_warning() -> None:
    report = HumanReport(
        kind=ReportKind.DAILY,
        as_of=datetime(2026, 9, 20, 20, 0, tzinfo=UTC),
        statements=(
            ReportStatement(
                kind=ReportStatementKind.FACT,
                content="Synthetic revenue evidence was refreshed.",
                evidence_ids=(uuid4(),),
            ),
            ReportStatement(
                kind=ReportStatementKind.CALCULATION,
                content="Concentration is below the TEST_DEFAULT cap.",
                calculation_input_hash="a" * 64,
            ),
            ReportStatement(
                kind=ReportStatementKind.AGENT_JUDGMENT,
                content="The synthetic thesis remains valid.",
                agent_opinion_id=uuid4(),
            ),
            ReportStatement(
                kind=ReportStatementKind.ASSUMPTION,
                content="No unobserved data is inferred.",
            ),
            ReportStatement(
                kind=ReportStatementKind.HUMAN_DECISION,
                content="No approval has been granted.",
                human_decision_id=uuid4(),
            ),
        ),
    )

    rendered = report.render_markdown()

    assert "SIMULATION / NO AUTO TRADE" in rendered
    assert "recommendations are not execution instructions" in rendered
    for kind in (
        "FACT",
        "CALCULATION",
        "AGENT_JUDGMENT",
        "ASSUMPTION",
        "HUMAN_DECISION",
    ):
        assert f"**{kind}**" in rendered


def test_report_allows_assumption_without_external_reference() -> None:
    statement = ReportStatement(ReportStatementKind.ASSUMPTION, "synthetic assumption")

    assert statement.content == "synthetic assumption"


@pytest.mark.parametrize(
    ("kind", "kwargs", "message"),
    [
        (ReportStatementKind.FACT, {}, "evidence"),
        (ReportStatementKind.CALCULATION, {}, "input hash"),
        (ReportStatementKind.AGENT_JUDGMENT, {}, "AgentOpinion"),
        (ReportStatementKind.HUMAN_DECISION, {}, "approval or decision"),
    ],
)
def test_report_rejects_missing_required_provenance(
    kind: ReportStatementKind, kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ReportStatement(kind=kind, content="synthetic statement", **kwargs)


def test_report_rejects_naive_as_of_and_empty_content() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        HumanReport(
            kind=ReportKind.WEEKLY,
            as_of=datetime(2026, 9, 20, 20, 0),
            statements=(ReportStatement(ReportStatementKind.ASSUMPTION, "synthetic"),),
        )
    with pytest.raises(ValueError, match="blank"):
        ReportStatement(ReportStatementKind.ASSUMPTION, " ")
