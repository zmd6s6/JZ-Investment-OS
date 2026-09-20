from datetime import UTC, datetime
from uuid import uuid4

import pytest

from investment_os.application.reports import (
    DailyOperatingReport,
    DailyReportSection,
    DailyReportSectionKind,
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
    assert "建议不是执行指令" in rendered
    for kind in (
        "事实",
        "确定性计算",
        "Agent 判断",
        "假设",
        "人工决定",
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


def test_daily_operating_report_keeps_all_required_sections_and_labels() -> None:
    sections = tuple(
        DailyReportSection(
            kind=kind,
            statements=(
                ReportStatement(
                    kind=ReportStatementKind.OPERATIONAL_EXCEPTION,
                    content="Synthetic scheduler status is unavailable.",
                ),
            )
            if kind is DailyReportSectionKind.DATA_AND_OPERATIONAL_EXCEPTIONS
            else (),
        )
        for kind in DailyReportSectionKind
    )

    rendered = DailyOperatingReport(
        as_of=datetime(2026, 9, 20, 20, 0, tzinfo=UTC), sections=sections
    ).render_markdown()

    assert "SIMULATION / NO AUTO TRADE" in rendered
    assert "## 需要处理" in rendered
    assert "## 继续持有" in rendered
    assert "## 数据与运行异常" in rendered
    assert "**运行异常**" in rendered
    assert rendered.count("暂无记录。") == 4


def test_daily_operating_report_rejects_missing_or_duplicate_sections() -> None:
    section = DailyReportSection(DailyReportSectionKind.ACTION_REQUIRED, ())

    with pytest.raises(ValueError, match="every operating section"):
        DailyOperatingReport(as_of=datetime(2026, 9, 20, tzinfo=UTC), sections=(section,))
    with pytest.raises(ValueError, match="duplicated"):
        DailyOperatingReport(
            as_of=datetime(2026, 9, 20, tzinfo=UTC),
            sections=(
                *tuple(DailyReportSection(kind, ()) for kind in DailyReportSectionKind),
                section,
            ),
        )


def test_daily_operating_report_rejects_noncanonical_section_order() -> None:
    sections = list(DailyReportSection(kind, ()) for kind in DailyReportSectionKind)
    sections[0], sections[1] = sections[1], sections[0]

    with pytest.raises(ValueError, match="canonical operating order"):
        DailyOperatingReport(as_of=datetime(2026, 9, 20, tzinfo=UTC), sections=tuple(sections))
