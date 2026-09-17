# Project Working Mode

## Purpose

This file defines how the human owner and Codex develop Personal AI Investment OS. It converts the Master Spec into a durable operating rhythm. It does not replace or modify the Master Spec.

## Roles

### Human owner

The human owner has final authority over:

- investment philosophy and real Investment Policy parameters;
- risk appetite and Veto semantics;
- data/provider authorization and cost boundaries;
- Strategy activation;
- live-trading capability and every live-trade approval;
- acceptance of roadmap stages and governance changes.

The owner reviews outcomes and corrects direction. The owner does not need to prescribe routine implementation details already covered by the specification.

### Codex

Codex acts as the senior implementation engineer and is responsible for:

- repository analysis and gap detection;
- architecture within approved boundaries;
- code, migrations, schemas, API, UI, tests, CI, documentation, and runbooks;
- independent verification and honest reporting;
- preserving traceability from requirements to implementation and evidence;
- surfacing only decisions that genuinely require human authority.

Codex may make routine, reversible engineering choices. It may not change investment governance, claim unrun tests passed, or expand to live trading without authorization.

### Runtime investment agents

CIO, Macro, Industry, Fundamental, Market/Quant, Event, Portfolio Manager, Risk Manager, Devil's Advocate, and Review/Learning are product components. They are not substitutes for Codex development work and do not inherit repository write or deployment authority.

## Operating loop

```text
Master Spec
    ↓
One active PR stage
    ↓
Codex implementation + tests
    ↓
Codex self-review and verification evidence
    ↓
Human review of governance/investment decisions
    ↓
Accept, correct, or return to implementation
    ↓
Update project status and begin the next stage
```

Only one roadmap stage is active at a time. Small defects discovered in completed stages may be fixed immediately when needed by the active stage, but must be identified in the delivery report.

## Stage states

Each `docs/stages/PR-XX.md` uses one state:

- `PLANNED`: requirements captured; no implementation claim.
- `IN_PROGRESS`: implementation is active.
- `BLOCKED`: an explicit external or human authority decision prevents safe progress.
- `READY_FOR_REVIEW`: implementation and required verification are complete.
- `ACCEPTED`: human owner accepted the stage.
- `SUPERSEDED`: replaced by an approved new stage contract.

Codex may move `PLANNED → IN_PROGRESS → READY_FOR_REVIEW`. Only the human owner moves a stage to `ACCEPTED` when investment/governance review is required.

## Starting a stage

Before implementation, Codex must:

1. inventory the repository and uncommitted changes;
2. verify the previous stage rather than trusting status labels;
3. identify Master Spec clauses and acceptance scenarios in scope;
4. list deliverables, out-of-scope items, risks, and human decisions;
5. set the stage state to `IN_PROGRESS`;
6. choose a minimal complete vertical slice and verification plan.

If the repository already contains work for a stage, Codex performs a gap analysis. Existing files are evidence only after their behavior is verified.

## Finishing a stage

A stage can become `READY_FOR_REVIEW` only when:

- every stage deliverable is implemented or explicitly marked out of scope by an approved change;
- every stage acceptance criterion has evidence;
- the Master Spec Definition of Done is satisfied;
- required commands have run successfully, with exact results recorded;
- migrations, OpenAPI, schemas, docs, and ADRs are current;
- no material `NOT VERIFIED` remains without a clearly identified external blocker;
- `docs/PROJECT_STATUS.md` and the stage file are updated.

The stage report uses this structure:

```text
Scope completed
Master Spec clauses implemented
Files / migrations / APIs changed
Verification run and results
Acceptance scenarios demonstrated
Risks and known limitations
Human decisions required
Rollback / recovery
Recommended next stage
```

## Human-decision protocol

When a human decision is required, Codex presents:

1. the exact decision;
2. why the Master Spec does not already resolve it;
3. two or three viable options;
4. the recommended option and trade-offs;
5. which work is blocked and which work continues.

The decision and rationale are recorded in an ADR, Policy approval, Strategy approval, or stage decision log as appropriate. Chat history alone is not the authoritative record.

## Stage publication and remote CI

The owner gives standing authorization for Codex to publish each completed roadmap stage for CI:

1. after local Definition of Done checks pass and the stage reaches `READY_FOR_REVIEW`, use a
   stage-specific branch named `codex/pr-XX-short-description`;
2. commit only the reviewed stage scope and push the branch to `origin`;
3. the push must trigger the repository's remote CI on every branch;
4. wait for remote CI and record its actual result in the stage evidence;
5. fix failures on the same branch and push follow-up commits until CI passes or a genuine blocker
   is recorded.

This standing authorization does not allow Codex to push directly to `main`, force-push, merge,
delete remote branches, publish releases, or bypass human stage acceptance. A GitHub pull request may
be opened separately when requested or when repository automation explicitly requires it.

## Defect and change handling

- A defect that violates a Master Spec MUST is fixed before advancing the dependent stage.
- A new feature outside PR-00–PR-09 is placed in a future backlog and does not silently expand the active stage.
- A change to investment behavior requires a human decision and versioned Policy/Strategy artifacts.
- A Master Spec ambiguity is interpreted conservatively, recorded, and escalated only if it changes behavior materially.
- Failed experiments remain documented; do not delete evidence to make the project appear successful.

## Release modes

The project progresses through explicit modes:

1. `DEVELOPMENT`: synthetic fixtures; no portfolio authority.
2. `BACKTEST`: historical as-of execution with `available_at` enforcement.
3. `SHADOW`: current data, recommendations only, no execution.
4. `PAPER`: simulated executions behind the approval workflow.
5. `MANUAL_LIVE_RECORDING`: human executes externally; system records the result after approval.
6. `BROKER_LIVE`: not part of V1 and forbidden until a separate ADR, security review, and explicit human authorization.

Moving to a later mode is never automatic.

## Communication cadence

During active implementation Codex provides concise updates when a meaningful milestone, risk, or blocker appears. Final reports are self-contained and distinguish:

- completed and verified;
- completed but not verified;
- planned but not implemented;
- blocked by human authority or external dependency.

No status report may imply investment performance or safety that has not been demonstrated.
