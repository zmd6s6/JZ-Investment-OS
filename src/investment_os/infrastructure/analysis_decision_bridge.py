"""Atomic explicit preparation from immutable Analysis facts to an unapproved Decision."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_decision_bridge import (
    DecisionBridgeScope,
    DecisionBridgeView,
    DecisionQualification,
    PrepareAnalysisDecision,
    StrategyDecisionSnapshot,
    evaluate_decision_readiness,
)
from investment_os.application.analysis_risk_sizing import (
    RiskSizingView,
    portfolio_identity,
    utc_now,
)
from investment_os.application.analysis_runs import (
    AnalysisFrozenInput,
    CioProposal,
    PortfolioIntent,
)
from investment_os.application.decision_center import clean_text
from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.domain.decision import DecisionClaim, DecisionPosition, InvestmentDecision
from investment_os.domain.enums import Action, BucketAction, DecisionState
from investment_os.domain.sizing import SizingRequest
from investment_os.domain.values import UtcTimestamp, Weight
from investment_os.infrastructure.analysis_decision_models import (
    AnalysisDecisionBridgeRecord,
    BridgeStrategyVersionRecord,
    DecisionQualificationRecord,
)
from investment_os.infrastructure.analysis_decision_sources import SqlDecisionQualifications
from investment_os.infrastructure.analysis_risk_sizing import pending_capacity
from investment_os.infrastructure.analysis_risk_sizing_models import AnalysisSizingResultRecord
from investment_os.infrastructure.analysis_runs import audit, emit
from investment_os.infrastructure.decision_center import SqlDecisionCenter, ledger_fingerprint
from investment_os.infrastructure.decision_center_validation import (
    agent_opinion,
    sizing_request,
    thesis_content,
)
from investment_os.infrastructure.persistence.analysis_models import (
    AnalysisInputRecord,
    AnalysisRoleOutputRecord,
    AnalysisRunRecord,
)
from investment_os.infrastructure.persistence.models import (
    AgentOpinionRecord,
    AgentRunRecord,
    CommitteeMessageRecord,
    InvestmentDecisionRecord,
    InvestmentPolicyRecord,
    InvestmentPolicyVersionRecord,
    PortfolioRecord,
    PositionSizingRunRecord,
    RiskAssessmentRecord,
    ThesisVersionRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork


class CandidateBlocked(ValueError):
    def __init__(self, *blockers: str):
        self.blockers = tuple(blockers)
        super().__init__("DECISION_CANDIDATE_BLOCKED")


class SqlAnalysisDecisionBridge:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, now: Callable[[], datetime] = utc_now
    ):
        self._sessions, self._now = sessions, now
        self._sources = SqlDecisionQualifications(sessions, now=now)
        self._center = SqlDecisionCenter(sessions, now=now)

    async def history(self, run_id: UUID) -> tuple[DecisionBridgeView, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(AnalysisDecisionBridgeRecord)
                    .where(AnalysisDecisionBridgeRecord.run_id == run_id)
                    .order_by(AnalysisDecisionBridgeRecord.revision)
                )
            ).all()
            return tuple(DecisionBridgeView.model_validate(row.payload_json) for row in rows)

    async def get(self, run_id: UUID) -> DecisionBridgeView | None:
        rows = await self.history(run_id)
        return rows[-1] if rows else None

    async def prepare(self, command: PrepareAnalysisDecision) -> DecisionBridgeView:
        actor = clean_text(command.actor_id)
        if not actor:
            raise ValueError("DECISION_PREPARATION_ACTOR_REQUIRED")
        digest = fingerprint(command.model_dump(mode="json"))
        async with SqlAlchemyUnitOfWork(self._sessions) as uow:
            session = uow.session
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 0))"),
                {"id": f"analysis-decision-preparation:{command.request_id}"},
            )
            replay = await session.get(AnalysisDecisionBridgeRecord, command.request_id)
            if replay is not None:
                if replay.run_id != command.run_id or replay.request_hash != digest:
                    raise ValueError("DECISION_PREPARATION_REQUEST_CONFLICT")
                return DecisionBridgeView.model_validate(replay.payload_json)
            run = await session.get(AnalysisRunRecord, command.run_id, with_for_update=True)
            if run is None:
                raise LookupError("ANALYSIS_NOT_FOUND")
            if run.status not in {"SUCCEEDED", "DEGRADED"} or run.cancel_requested:
                raise ValueError("DECISION_PREPARATION_REQUIRES_FINISHED_ANALYSIS")
            if run.input_hash != command.expected_input_hash:
                raise ValueError("DECISION_PREPARATION_INPUT_CONFLICT")
            prior = (
                await session.scalars(
                    select(AnalysisDecisionBridgeRecord)
                    .where(AnalysisDecisionBridgeRecord.run_id == run.id)
                    .order_by(AnalysisDecisionBridgeRecord.revision)
                )
            ).all()
            revision = prior[-1].revision if prior else 0
            if command.expected_revision != revision:
                raise ValueError("DECISION_PREPARATION_REVISION_CONFLICT")
            if any(row.decision_id is not None for row in prior):
                raise ValueError("ANALYSIS_ALREADY_HAS_INVESTMENT_DECISION")
            # Parent first, then a short table SHARE lock: Position has no Portfolio FK.
            # This closes insert phantoms as well as changes to existing quantities.
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            await session.get(PortfolioRecord, run.portfolio_id, with_for_update=True)
            await session.execute(text("LOCK TABLE position IN SHARE MODE"))
            await session.execute(
                text("LOCK TABLE decision_approval, decision_execution IN SHARE MODE")
            )
            qualification_row = await session.get(
                DecisionQualificationRecord, command.qualification_id
            )
            source: DecisionQualification | None = None
            strategy: StrategyDecisionSnapshot | None = None
            try:
                command_payload = run.queued_input_json.get("command")
                if not isinstance(command_payload, dict):
                    raise CandidateBlocked("DECISION_ANALYSIS_ORIGIN_UNAVAILABLE")
                if command_payload.get("runtime_authorization") is not None:
                    raise CandidateBlocked("SCHEDULED_SHADOW_CANNOT_CREATE_INVESTMENT_DECISION")
                stored = await session.scalar(
                    select(AnalysisInputRecord).where(AnalysisInputRecord.run_id == run.id)
                )
                if stored is None:
                    raise CandidateBlocked("DECISION_FROZEN_INPUT_UNAVAILABLE")
                frozen = AnalysisFrozenInput.model_validate(stored.payload_json)
                if (
                    frozen.run_id != run.id
                    or frozen.input_hash != run.input_hash
                    or stored.input_hash != frozen.input_hash
                    or fingerprint(frozen.model_dump(mode="json", exclude={"input_hash"}))
                    != frozen.input_hash
                ):
                    raise CandidateBlocked("DECISION_FROZEN_INPUT_HASH_MISMATCH")
                if qualification_row is None:
                    raise CandidateBlocked("DECISION_QUALIFICATION_NOT_FOUND")
                source = await self._sources.read(session, qualification_row)
                await session.get(
                    BridgeStrategyVersionRecord,
                    source.strategy_version_id,
                    with_for_update={"read": True},
                )
                strategy = await self._sources.read_strategy(session, source.strategy_version_id)
                frozen_evidence = {item.evidence_id: item.content_hash for item in frozen.evidence}
                if any(
                    frozen_evidence.get(fact.evidence_id) != fact.evidence_content_hash
                    for fact in source.facts
                ):
                    raise CandidateBlocked("DECISION_GATE_EVIDENCE_NOT_IN_FROZEN_ANALYSIS")
                numeric_row = await session.get(AnalysisSizingResultRecord, run.id)
                numeric = (
                    RiskSizingView.model_validate(numeric_row.payload_json) if numeric_row else None
                )
                proposal, intent = await self._proposals(session, run)
                scope = DecisionBridgeScope(
                    portfolio_id=run.portfolio_id,
                    instrument_id=run.instrument_id,
                    policy_version_id=run.policy_version_id,
                    numeric_snapshot_id=frozen.queued.command.numeric_snapshot_id,
                    portfolio_identity_hash=portfolio_identity(
                        frozen.queued.valuation.input_snapshot
                    ),
                    captured_at=frozen.queued.valuation.input_snapshot.captured_at,
                    queued_at=run.queued_at,
                    scheduled_shadow=False,
                )
                view = evaluate_decision_readiness(
                    scope=scope,
                    qualification=source,
                    strategy=strategy,
                    numeric=numeric,
                    action=proposal.proposed_action,
                    evaluated_at=self._now(),
                )
                if view.blockers:
                    raise CandidateBlocked(*view.blockers)
                assert numeric is not None
                try:
                    async with session.begin_nested():
                        decision = await self._append_candidate(
                            uow, run, frozen, numeric, view, source, proposal, intent, command
                        )
                        (
                            blockers,
                            _lineage,
                            _quantity,
                        ) = await self._center.validate_proposal_lineage(
                            session, decision, self._now()
                        )
                        if blockers:
                            raise CandidateBlocked(*blockers)
                        final_now = self._now()
                        if (
                            view.expires_at is None
                            or final_now >= view.expires_at
                            or final_now >= decision.next_review_at
                        ):
                            raise CandidateBlocked("DECISION_QUALIFICATION_EXPIRED_BEFORE_WRITE")
                    view = view.model_copy(
                        update={
                            "status": "PENDING_APPROVAL",
                            "decision_id": decision.id,
                            "evaluated_at": final_now,
                        }
                    )
                except CandidateBlocked:
                    raise
            except CandidateBlocked as error:
                view = DecisionBridgeView(
                    qualification_id=source.qualification_id if source else None,
                    strategy_version_id=strategy.strategy_version_id if strategy else None,
                    blockers=error.blockers,
                    evaluated_at=self._now(),
                )
            except (ValueError, KeyError, TypeError):
                view = DecisionBridgeView(
                    blockers=("DECISION_PREPARATION_INPUT_INVALID",), evaluated_at=self._now()
                )
            view = view.model_copy(
                update={"request_id": command.request_id, "revision": revision + 1}
            )
            session.add(
                AnalysisDecisionBridgeRecord(
                    request_id=command.request_id,
                    run_id=run.id,
                    revision=view.revision,
                    qualification_id=qualification_row.id if qualification_row else None,
                    strategy_version_id=view.strategy_version_id,
                    decision_id=view.decision_id,
                    input_hash=command.expected_input_hash,
                    request_hash=digest,
                    status=view.status,
                    payload_json=view.model_dump(mode="json"),
                    **{**audit(run.id), "created_by": actor},
                )
            )
            await emit(
                session,
                run,
                "decision_prepared",
                {
                    "request_id": str(command.request_id),
                    "decision_id": str(view.decision_id) if view.decision_id else None,
                    "revision": view.revision,
                    "status": view.status,
                    "actor_id": actor,
                    "qualification_id": str(command.qualification_id),
                    "input_hash": command.expected_input_hash,
                },
            )
            await uow.commit()
            return view

    async def _proposals(
        self, session: AsyncSession, run: AnalysisRunRecord
    ) -> tuple[CioProposal, PortfolioIntent]:
        values: dict[str, object] = {}
        for role, kind in (("CIO", "cio-proposal-1.0"), ("PORTFOLIO", "portfolio-intent-1.0")):
            output = await session.scalar(
                select(AnalysisRoleOutputRecord).where(
                    AnalysisRoleOutputRecord.run_id == run.id,
                    AnalysisRoleOutputRecord.role == role,
                    AnalysisRoleOutputRecord.schema_kind == kind,
                    AnalysisRoleOutputRecord.round_number == 0,
                )
            )
            if (
                output is None
                or fingerprint(output.payload_json) != output.content_hash
                or output.payload_json.get("failure")
            ):
                raise CandidateBlocked("DECISION_STRUCTURED_PROPOSAL_UNAVAILABLE")
            agent_run = await session.get(AgentRunRecord, output.agent_run_id)
            if (
                agent_run is None
                or agent_run.status != "SUCCEEDED"
                or agent_run.input_snapshot_hash != run.input_hash
            ):
                raise CandidateBlocked("DECISION_STRUCTURED_PROPOSAL_PROVENANCE_INVALID")
            values[role] = output.payload_json["validated_output"]
        proposal, intent = (
            CioProposal.model_validate(values["CIO"]),
            PortfolioIntent.model_validate(values["PORTFOLIO"]),
        )
        if proposal.unknowns or intent.unknowns:
            raise CandidateBlocked("DECISION_STRUCTURED_PROPOSAL_HAS_UNKNOWNS")
        return proposal, intent

    async def _append_candidate(
        self,
        uow: SqlAlchemyUnitOfWork,
        run: AnalysisRunRecord,
        frozen: AnalysisFrozenInput,
        numeric: RiskSizingView,
        view: DecisionBridgeView,
        source: DecisionQualification,
        proposal: CioProposal,
        intent: PortfolioIntent,
        command: PrepareAnalysisDecision,
    ) -> InvestmentDecisionRecord:
        session = uow.session
        now = self._now()
        risk = await session.get(RiskAssessmentRecord, numeric.risk_assessment_id)
        sizing = await session.get(PositionSizingRunRecord, numeric.sizing_run_id)
        policy = await session.get(InvestmentPolicyVersionRecord, run.policy_version_id)
        thesis = await session.get(ThesisVersionRecord, frozen.thesis_version_id)
        if any(item is None for item in (risk, sizing, policy, thesis)):
            raise CandidateBlocked("DECISION_STANDARD_LINEAGE_MISSING")
        assert risk is not None and sizing is not None and policy is not None and thesis is not None
        parent = await session.get(InvestmentPolicyRecord, policy.policy_id, with_for_update=True)
        schema = InvestmentPolicySchema.model_validate(policy.config_json)
        if (
            parent is None
            or parent.status != "ACTIVE"
            or parent.current_version_id != policy.id
            or schema.metadata.status.value != "ACTIVE"
            or schema.sizing is None
            or policy.approved_at is None
            or not policy.approved_by
            or policy.approved_at > frozen.as_of
            or policy.effective_from is None
            or policy.effective_from > frozen.as_of
            or policy.content_hash != frozen.queued.valuation.input_snapshot.policy.content_hash
            or fingerprint(policy.config_json) != policy.content_hash
        ):
            raise CandidateBlocked("DECISION_POLICY_NOT_EXPLICITLY_APPROVED_AND_FIXED")
        if sizing.input_json.get("ledger_hash") != await ledger_fingerprint(
            session, run.portfolio_id
        ):
            raise CandidateBlocked("DECISION_PORTFOLIO_CHANGED")
        current_pending, pending_reasons = await pending_capacity(
            session, frozen, as_of=self._now()
        )
        request = TypeAdapter(SizingRequest).validate_python(sizing.input_json["request"])
        if (
            current_pending is None
            or pending_reasons
            or current_pending
            != (
                request.capacity_inputs.pending_instrument_weight.value,
                request.capacity_inputs.pending_sector_weight.value,
                request.capacity_inputs.pending_gross_exposure.value,
            )
        ):
            raise CandidateBlocked("DECISION_PENDING_EXPOSURE_CHANGED")
        action = proposal.proposed_action
        if action not in {Action.BUY, Action.ADD, Action.REDUCE, Action.EXIT}:
            raise CandidateBlocked("DECISION_ACTION_HAS_NO_APPROVAL_QUANTITY")
        if risk.veto and action in {Action.REDUCE, Action.EXIT}:
            if not command.confirm_risk_reduction_exception:
                raise CandidateBlocked("DECISION_RISK_REDUCTION_CONFIRMATION_REQUIRED")
            # Preserve the original numeric artifact. A new canonical sizing copy records
            # the explicitly confirmed reduction exception required by the existing 301 gate.
            sizing = PositionSizingRunRecord(
                id=uuid4(),
                portfolio_id=sizing.portfolio_id,
                instrument_id=sizing.instrument_id,
                policy_version_id=sizing.policy_version_id,
                input_json={**sizing.input_json, "risk_reduction_exception_recorded": True},
                output_json=sizing.output_json,
                input_hash=sizing.input_hash,
                formula_version=sizing.formula_version,
                **{
                    **audit(run.id),
                    "metadata_json": {"source_sizing_run_id": str(numeric.sizing_run_id)},
                },
            )
            session.add(sizing)
            await session.flush()
        pairs = (
            await session.execute(
                select(AgentOpinionRecord, AgentRunRecord)
                .join(AgentRunRecord, AgentRunRecord.id == AgentOpinionRecord.agent_run_id)
                .join(
                    CommitteeMessageRecord,
                    CommitteeMessageRecord.opinion_id == AgentOpinionRecord.id,
                )
                .where(CommitteeMessageRecord.session_id == risk.session_id)
            )
        ).all()
        opinions = [agent_opinion(opinion, agent_run) for opinion, agent_run in pairs]
        if not opinions or any(opinion.unknowns for opinion in opinions):
            raise CandidateBlocked("DECISION_COMMITTEE_INCOMPLETE_OR_UNKNOWN")
        before_core = Decimal(str(numeric.numbers["core_weight"]))
        before_tactical = Decimal(str(numeric.numbers["tactical_weight"]))
        after_core, after_tactical = before_core, before_tactical
        target_weight = Decimal(str(sizing.output_json["target_weight"]["value"]))
        if request.bucket.value == "CORE":
            after_core = target_weight
        else:
            after_tactical = target_weight
        content = thesis_content(thesis)
        assert view.expires_at is not None
        expiry = min(
            [view.expires_at, *[item.expires_at for item in frozen.evidence if item.expires_at]]
        )
        assert expiry is not None
        reasons = tuple(
            DecisionClaim(reason.text, reason.evidence_ids) for reason in proposal.reasons
        )
        reasons += (
            DecisionClaim(
                "固定已批准Strategy的具名规则及资料通过确定性校验(合成)",
                tuple(sorted({fact.evidence_id for fact in source.facts}, key=str)),
            ),
        )
        domain = InvestmentDecision(
            instrument_id=run.instrument_id,
            portfolio_id=run.portfolio_id,
            thesis_version_id=thesis.id,
            policy_version_id=policy.id,
            strategy_version_id=source.strategy_version_id,
            risk_assessment_id=risk.id,
            position_sizing_run_id=sizing.id,
            action=action,
            confidence=Weight(min(opinion.confidence.value for opinion in opinions)),
            risk_intent=intent.risk_intent,
            position_before=DecisionPosition(
                Weight(before_core + before_tactical), Weight(before_core), Weight(before_tactical)
            ),
            position_after_proposed=DecisionPosition(
                Weight(after_core + after_tactical), Weight(after_core), Weight(after_tactical)
            ),
            core_action=BucketAction(action.value)
            if request.bucket.value == "CORE"
            else BucketAction.NONE,
            tactical_action=BucketAction(action.value)
            if request.bucket.value == "TACTICAL"
            else BucketAction.NONE,
            reasons=reasons,
            risks=(),
            watch_conditions=content.monitoring_conditions,
            invalidation_conditions=tuple(
                item.condition for item in content.invalidation_conditions
            ),
            unknowns=(),
            dissent=(),
            next_review_at=UtcTimestamp(expiry),
            input_snapshot_hash=frozen.input_hash,
            prompt_bundle_version=frozen.prompt_bundle_version,
            formula_version=sizing.formula_version,
            committee_session_id=risk.session_id,
            state=DecisionState.PENDING_APPROVAL,
        )
        record = decision_record(
            domain, now, run.id, source.qualification_id, numeric.sizing_run_id
        )
        sizing_request(sizing, record, policy, risk, thesis)
        await uow.decisions.append(record)
        await uow.decisions.link_evidence(record.id, domain.evidence_ids)
        return record


def decision_record(
    value: InvestmentDecision,
    at: datetime,
    run_id: UUID,
    qualification_id: UUID,
    source_sizing_run_id: UUID | None,
) -> InvestmentDecisionRecord:
    def position(item: DecisionPosition) -> dict[str, str]:
        return {
            "total": str(item.total.value),
            "core": str(item.core.value),
            "tactical": str(item.tactical.value),
        }

    def claims(values: tuple[DecisionClaim, ...]) -> list[dict[str, object]]:
        return [
            {
                "text": item.text,
                "evidence_ids": [str(identifier) for identifier in item.evidence_ids],
            }
            for item in values
        ]

    return InvestmentDecisionRecord(
        id=value.id,
        instrument_id=value.instrument_id,
        portfolio_id=value.portfolio_id,
        committee_session_id=value.committee_session_id,
        thesis_version_id=value.thesis_version_id,
        policy_version_id=value.policy_version_id,
        strategy_version_id=value.strategy_version_id,
        risk_assessment_id=value.risk_assessment_id,
        position_sizing_run_id=value.position_sizing_run_id,
        action=value.action.value,
        confidence=value.confidence.value,
        risk_intent=value.risk_intent.value,
        core_action=value.core_action.value,
        tactical_action=value.tactical_action.value,
        state=value.state.value,
        reasons_json=claims(value.reasons),
        risks_json=claims(value.risks),
        watch_conditions_json=list(value.watch_conditions),
        invalidation_conditions_json=list(value.invalidation_conditions),
        next_review_at=value.next_review_at.value,
        input_snapshot_hash=value.input_snapshot_hash,
        position_before_json=position(value.position_before),
        position_after_proposed_json=position(value.position_after_proposed),
        unknowns_json=list(value.unknowns),
        dissent_json=list(value.dissent),
        prompt_bundle_version=value.prompt_bundle_version,
        formula_version=value.formula_version,
        content_hash=value.content_hash,
        version=value.version,
        created_at=at,
        **{
            **audit(run_id),
            "metadata_json": {
                "analysis_run_id": str(run_id),
                "decision_qualification_id": str(qualification_id),
                "source_sizing_run_id": str(source_sizing_run_id),
                "simulation_only": True,
                "confidence_method": "MINIMUM_VALID_COMMITTEE_CONFIDENCE",
                "origin": "EXPLICIT_POST_ANALYSIS_PREPARATION",
            },
        },
    )
