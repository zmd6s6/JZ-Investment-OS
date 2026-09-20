"""Validated, human-readable reports that preserve the provenance of every statement."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4


class ReportKind(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class ReportStatementKind(StrEnum):
    FACT = "FACT"
    CALCULATION = "CALCULATION"
    AGENT_JUDGMENT = "AGENT_JUDGMENT"
    ASSUMPTION = "ASSUMPTION"
    HUMAN_DECISION = "HUMAN_DECISION"
    OPERATIONAL_EXCEPTION = "OPERATIONAL_EXCEPTION"


class DailyReportSectionKind(StrEnum):
    ACTION_REQUIRED = "ACTION_REQUIRED"
    CONTINUE_HOLDING = "CONTINUE_HOLDING"
    WATCH = "WATCH"
    NEW_DISCOVERIES = "NEW_DISCOVERIES"
    DATA_AND_OPERATIONAL_EXCEPTIONS = "DATA_AND_OPERATIONAL_EXCEPTIONS"


REPORT_KIND_TITLES = {
    ReportKind.DAILY: "日报",
    ReportKind.WEEKLY: "周报",
    ReportKind.MONTHLY: "月报",
}
STATEMENT_KIND_TITLES = {
    ReportStatementKind.FACT: "事实",
    ReportStatementKind.CALCULATION: "确定性计算",
    ReportStatementKind.AGENT_JUDGMENT: "Agent 判断",
    ReportStatementKind.ASSUMPTION: "假设",
    ReportStatementKind.HUMAN_DECISION: "人工决定",
    ReportStatementKind.OPERATIONAL_EXCEPTION: "运行异常",
}
DAILY_SECTION_TITLES = {
    DailyReportSectionKind.ACTION_REQUIRED: "需要处理",
    DailyReportSectionKind.CONTINUE_HOLDING: "继续持有",
    DailyReportSectionKind.WATCH: "观察",
    DailyReportSectionKind.NEW_DISCOVERIES: "新增发现",
    DailyReportSectionKind.DATA_AND_OPERATIONAL_EXCEPTIONS: "数据与运行异常",
}


@dataclass(frozen=True, slots=True)
class ReportStatement:
    """One labelled statement with the minimum provenance appropriate to its category."""

    kind: ReportStatementKind
    content: str
    evidence_ids: tuple[UUID, ...] = ()
    calculation_input_hash: str | None = None
    agent_opinion_id: UUID | None = None
    human_decision_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("report statement content must not be blank")
        if self.kind is ReportStatementKind.FACT and not self.evidence_ids:
            raise ValueError("facts require evidence references")
        if self.kind is ReportStatementKind.CALCULATION and not self.calculation_input_hash:
            raise ValueError("calculations require an input hash")
        if self.kind is ReportStatementKind.AGENT_JUDGMENT and self.agent_opinion_id is None:
            raise ValueError("Agent judgments require an AgentOpinion reference")
        if self.kind is ReportStatementKind.HUMAN_DECISION and self.human_decision_id is None:
            raise ValueError("human decisions require an approval or decision reference")


@dataclass(frozen=True, slots=True)
class HumanReport:
    """A synthetic-safe report rendered only from labelled, already-validated statements."""

    kind: ReportKind
    as_of: datetime
    statements: tuple[ReportStatement, ...]
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("report as_of must be timezone-aware")
        if not self.statements:
            raise ValueError("report must contain at least one statement")

    def render_markdown(self) -> str:
        """Render presentation only; it does not create or submit any execution instruction."""

        lines = [
            f"# {REPORT_KIND_TITLES[self.kind]}",
            "",
            "> **模拟运行 / 禁止自动交易 (SIMULATION / NO AUTO TRADE)** — 建议不是执行指令。",
            f"> 数据截至: `{self.as_of.astimezone(UTC).isoformat()}`",
            "",
        ]
        lines.extend(
            f"- **{STATEMENT_KIND_TITLES[statement.kind]}**: {statement.content}"
            for statement in self.statements
        )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class DailyReportSection:
    kind: DailyReportSectionKind
    statements: tuple[ReportStatement, ...]


@dataclass(frozen=True, slots=True)
class DailyOperatingReport:
    """The required one-page Daily operating loop, including explicit empty sections."""

    as_of: datetime
    sections: tuple[DailyReportSection, ...]
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("daily report as_of must be timezone-aware")
        kinds = {section.kind for section in self.sections}
        if len(kinds) != len(self.sections):
            raise ValueError("daily report sections must not be duplicated")
        missing = set(DailyReportSectionKind) - kinds
        if missing:
            raise ValueError("daily report must include every operating section")
        if tuple(section.kind for section in self.sections) != tuple(DailyReportSectionKind):
            raise ValueError("daily report sections must use the canonical operating order")

    def render_markdown(self) -> str:
        lines = [
            "# 日报",
            "",
            "> **模拟运行 / 禁止自动交易 (SIMULATION / NO AUTO TRADE)** — 建议不是执行指令。",
            f"> 数据截至: `{self.as_of.astimezone(UTC).isoformat()}`",
        ]
        for section in self.sections:
            lines.extend(("", f"## {DAILY_SECTION_TITLES[section.kind]}"))
            lines.extend(
                f"- **{STATEMENT_KIND_TITLES[statement.kind]}**: {statement.content}"
                for statement in section.statements
            )
            if not section.statements:
                lines.append("- 暂无记录。")
        return "\n".join(lines)

    def content_hash(self) -> str:
        """Return the immutable content address of this presentation artifact."""

        return sha256(self.render_markdown().encode("utf-8")).hexdigest()
