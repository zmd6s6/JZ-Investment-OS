# Project Status

> This is the single current-status record. Update it in the same change that advances a stage.

## Current snapshot

- Project: Personal AI Investment OS
- Current mode: `DEVELOPMENT`
- Active roadmap stage: `PR-08 — Scheduler, Reports & Personal UI`
- Stage state: `READY_FOR_REVIEW`
- Live trading: `FORBIDDEN`
- Canonical specification: `INVESTMENT_OS_MASTER_SPEC.md`
- Last status update: `2026-09-20`

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
- Remote GitHub CI passes quality, Compose smoke, and independent Gitleaks jobs on the PR-01 branch.
- ADR-0001 through ADR-0010 are accepted as Master-Spec implementation decisions.
- Pure domain values, Investment Policy, and Instrument/Thesis/Decision/Strategy state machines exist.
- Core/Tactical, Risk Veto, human approval, and Learning authority invariants fail closed.
- Decision Risk Gate is explicit (`UNKNOWN|PASS|VETO`); missing assessment cannot be interpreted as PASS.
- ADR-0011 records the pure-domain and strict Policy-boundary implementation decision.
- ADR-0012 records explicit synthetic calendar semantics for U.S., Shanghai, and Shenzhen venues;
  A-share real data/provider and trading authorization remain unapproved.
- Alembic revision `20260917_0001` creates all Master-Spec core tables plus normalized Evidence
  reference tables with UUID, numeric, timestamptz, constraint, and index contracts.
- Policy, Position, Thesis, and Decision persistence uses optimistic version checks.
- Audit/event history and immutable artifacts have database-enforced append-only guards.
- Unit of Work, transactional outbox, advisory locks, and idempotent TaskRun execution are verified
  against PostgreSQL 16.
- Compose applies migrations through a successful one-shot service before API/worker startup.
- Remote GitHub Actions run `35295158962` passes quality, Compose smoke, and independent Gitleaks
  jobs for the current PR-02 review head `cfb707d4f463a37605d6cae503f5a1f42aaceea9`.
- PR-02 is accepted and merged to `main` by PR #2 as `72a64ff797c25ec1c1e5e8d8196f9fe85ad44d5e`.
- PR-03 is accepted and merged to `main` by PR #3 as `5dc99027a460a7f29d9b4021a982af726f2363f2`.
- PR-04 is accepted and merged to `main` by PR #4 as `a0a9acdca6b5c75b2193eede51dd1a6e2310a22f`.
- PR-05 is accepted and merged to `main` by PR #5 as `b141be8ada55f44b2840e692c6b838c3df0913ca`.
- PR-06 is accepted and merged to `main` by PR #6 as `3009b2b52289b6a6552dac5e3676e41f7ce8bb53`.
- PR-07 is accepted and merged to `main` by PR #7 as `2838301f4b4b648f010fa4f0d06cfe03a2e0f64e`.

## Not yet implemented or verified

- business persistence workflows beyond the focused PR-02 repositories and reliability primitives;
- acceptance-scenario coverage beyond the implemented PR-07 S10 and the focused PR-01/PR-05
  domain-gate slices, except for PR-08 S12 scheduler replay and idempotency coverage;
- Learning workflow functionality, outcome review, release hardening, and recovery drills (PR-09).

Nothing above may be inferred complete from the Master Spec alone.

## Next authorized work

PR-08 is `READY_FOR_REVIEW` on `codex/pr-08-scheduler-reports-ui`, created from the GitHub- and
`origin/main`-confirmed PR #7 merge commit `2838301f4b4b648f010fa4f0d06cfe03a2e0f64e`.
It may implement only synthetic scheduler/replay, reporting, and personal read-only UI contracts.
Live brokerage execution, credentials, real Portfolio data, and real investment-policy choices
remain forbidden.

## Recorded scope decisions

- **PR-05 scope reconciliation (approved 2026-09-20):** defer S1/S2 final `WATCH`/`AVOID` Action
  assertions to PR-07, where the CIO/Decision path is in scope. PR-05 retains synthetic research
  and committee fixtures for the scenarios' antecedent inputs, and must not create a CIO Decision.
- The shipped Policy is `TEST_DEFAULT`; choosing real limits remains a future human decision.
- **A-share scope (approved 2026-09-20):** include SSE/SZSE calendar semantics and synthetic
  research/simulation fixtures. This does not approve a data provider, real A-share portfolio data,
  A-share policy limits, brokerage execution, or live trading.
  Stage-branch commits and pushes are authorized by the owner; merging to `main` remains a separate
  human action.

## Roadmap

| Stage | State | Human acceptance | Notes |
|---|---|---|---|
| PR-00 | ACCEPTED | Merged to `main` | Delivered and accepted with the merged foundational work |
| PR-01 | ACCEPTED | Merged to `main` on 2026-09-17 | PR #1 merge commit `45b024109775e233049b8c7df1792b6190c67a58` |
| PR-02 | ACCEPTED | Merged to `main` on 2026-09-18 | PR #2 merge commit `72a64ff797c25ec1c1e5e8d8196f9fe85ad44d5e` |
| PR-03 | ACCEPTED | Merged to `main` on 2026-09-18 | PR #3 merge commit `5dc99027a460a7f29d9b4021a982af726f2363f2` |
| PR-04 | ACCEPTED | Merged to `main` on 2026-09-19 | PR #4 merge commit `a0a9acdca6b5c75b2193eede51dd1a6e2310a22f` |
| PR-05 | ACCEPTED | Merged to `main` on 2026-09-20 | PR #5 merge commit `b141be8ada55f44b2840e692c6b838c3df0913ca` |
| PR-06 | ACCEPTED | Merged to `main` on 2026-09-20 | PR #6 merge commit `3009b2b52289b6a6552dac5e3676e41f7ce8bb53` |
| PR-07 | ACCEPTED | Merged to `main` on 2026-09-20 | PR #7 merge commit `2838301f4b4b648f010fa4f0d06cfe03a2e0f64e` |
| PR-08 | READY_FOR_REVIEW | Pending | Scheduler, reports, UI; full local verification recorded |
| PR-09 | PLANNED | Pending | Outcome, learning, hardening, release |

## Status update rules

- Do not mark a stage `READY_FOR_REVIEW` without recorded verification evidence.
- Do not mark a stage `ACCEPTED` on Codex's authority alone when human governance review is required.
- Add blockers with an owner, precise condition, attempted alternatives, and unblocking event.
- Keep detailed checklists and evidence in the corresponding `docs/stages/PR-XX.md`; keep this file concise.
