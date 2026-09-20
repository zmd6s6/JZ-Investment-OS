"""Validated, human-readable reports that preserve the provenance of every statement."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
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
            f"# {self.kind.value.title()} Report",
            "",
            "> **SIMULATION / NO AUTO TRADE** — recommendations are not execution instructions.",
            f"> Data as-of: `{self.as_of.astimezone(UTC).isoformat()}`",
            "",
        ]
        lines.extend(
            f"- **{statement.kind.value}**: {statement.content}" for statement in self.statements
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

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("daily report as_of must be timezone-aware")
        kinds = {section.kind for section in self.sections}
        if len(kinds) != len(self.sections):
            raise ValueError("daily report sections must not be duplicated")
        missing = set(DailyReportSectionKind) - kinds
        if missing:
            raise ValueError("daily report must include every operating section")

    def render_markdown(self) -> str:
        lines = [
            "# Daily Report",
            "",
            "> **SIMULATION / NO AUTO TRADE** — recommendations are not execution instructions.",
            f"> Data as-of: `{self.as_of.astimezone(UTC).isoformat()}`",
        ]
        for section in self.sections:
            lines.extend(("", f"## {section.kind.value.replace('_', ' ').title()}"))
            lines.extend(
                f"- **{statement.kind.value}**: {statement.content}"
                for statement in section.statements
            )
            if not section.statements:
                lines.append("- None recorded.")
        return "\n".join(lines)
