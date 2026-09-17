# Project Status

> This is the single current-status record. Update it in the same change that advances a stage.

## Current snapshot

- Project: Personal AI Investment OS
- Current mode: `DEVELOPMENT`
- Active roadmap stage: `PR-01 — Domain Kernel, Policy & State Machines`
- Stage state: `READY_FOR_REVIEW`
- Live trading: `FORBIDDEN`
- Canonical specification: `INVESTMENT_OS_MASTER_SPEC.md`
- Last status update: `2026-09-17`

## Established

- Master Engineering Specification exists and is the project SSOT.
- Root Codex working agreement exists in `AGENTS.md`.
- Persistent working mode exists in `docs/WORKING_MODE.md`.
- PR/ADR/stage documentation conventions exist.
- Python 3.12 project metadata and `uv.lock` exist.
- API and worker bootstrap health paths exist and have automated tests.
- PostgreSQL/API/worker Compose configuration parses successfully.
- PostgreSQL, API, and worker images build and reach healthy state; end-to-end smoke passes on host port 8100.
- CI, OpenAPI contract generation, dependency/license checks, and secret scanning are configured.
- ADR-0001 through ADR-0010 are accepted as Master-Spec implementation decisions.
- Pure domain values, Investment Policy, and Instrument/Thesis/Decision/Strategy state machines exist.
- Core/Tactical, Risk Veto, human approval, and Learning authority invariants fail closed.
- ADR-0011 records the pure-domain and strict Policy-boundary implementation decision.

## Not yet implemented or verified

- remote GitHub CI, because the configured remote has not been pushed or run for this worktree;
- React/Node workspace, intentionally deferred to PR-08 by ADR-0001;
- any database, runtime Agent, scheduler, UI, or Learning workflow functionality;
- persistence/audit of the PR-01 transition records, intentionally deferred to PR-02;
- any complete end-to-end acceptance scenario S1–S15; PR-01 verifies only its domain-gate slices.

Nothing above may be inferred complete from the Master Spec alone.

## Next authorized work

Publish PR-01 on a stage branch under the owner's standing authorization, wait for remote CI, and
record its result. The next implementation stage is PR-02 after PR-01 acceptance.

## Human decisions currently required

No investment-governance decision is required. The shipped Policy is `TEST_DEFAULT`; choosing real
limits remains a future human decision. Stage-branch commits and pushes are now authorized by the
owner; merging to `main` remains a separate human action.

## Roadmap

| Stage | State | Human acceptance | Notes |
|---|---|---|---|
| PR-00 | READY_FOR_REVIEW | Pending | Local/container checks pass; remote CI not verified |
| PR-01 | READY_FOR_REVIEW | Pending | Domain kernel, Policy, and state machines complete locally |
| PR-02 | PLANNED | Pending | Persistence, audit, reliable jobs |
| PR-03 | PLANNED | Pending | DSA adapter, evidence, feature pipeline |
| PR-04 | PLANNED | Pending | Thesis and shared memory |
| PR-05 | PLANNED | Pending | Agent runtime and committee |
| PR-06 | PLANNED | Pending | Portfolio, risk, sizing |
| PR-07 | PLANNED | Pending | Decision, approval, journal |
| PR-08 | PLANNED | Pending | Scheduler, reports, UI |
| PR-09 | PLANNED | Pending | Outcome, learning, hardening, release |

## Status update rules

- Do not mark a stage `READY_FOR_REVIEW` without recorded verification evidence.
- Do not mark a stage `ACCEPTED` on Codex's authority alone when human governance review is required.
- Add blockers with an owner, precise condition, attempted alternatives, and unblocking event.
- Keep detailed checklists and evidence in the corresponding `docs/stages/PR-XX.md`; keep this file concise.
