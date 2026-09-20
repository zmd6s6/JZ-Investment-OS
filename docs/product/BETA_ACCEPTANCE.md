# Personal AI Investment OS — Beta Acceptance Gate

> Purpose: define the minimum evidence required before the project may be described as normally usable by the owner.  
> Governing authority remains `INVESTMENT_OS_MASTER_SPEC.md`.

---

## 1. Beta definition

Beta means the owner can complete the normal investment-assistant workflow without touching source code, SQL, raw JSON, curl, or internal developer-only tools.

Beta does **not** mean:

- live brokerage automation
- guaranteed investment performance
- autonomous Strategy activation
- removal of human approval

V1/Beta keeps `auto_trade=false`.

---

## 2. Fresh-install acceptance

From a clean supported machine:

```text
git clone
docker compose up -d
```

The user must be able to open the Web UI and reach the Setup Wizard.

Pass conditions:

- database migration succeeds
- API is healthy
- worker is healthy
- Web UI is reachable
- no manual database bootstrap is required
- no hidden one-off developer script is required for ordinary onboarding

---

## 3. Model-provider acceptance

Through UI only, user can:

- create an OpenAI-compatible provider profile
- enter base URL, model and secret
- test connection
- see a sanitized success/failure result
- assign a default model
- run one schema-valid Agent call

Security checks:

- secret is never returned in plaintext
- secret does not appear in logs
- AgentRun records actual provider/model
- timeout fails closed
- invalid structured output follows bounded repair policy
- model failure cannot default into BUY/ADD

---

## 4. Data-provider acceptance

Through UI only, user can:

- configure one authorized research/data provider
- test connection
- see provider health/freshness
- sync at least one real authorized instrument

Traceability checks:

```text
Provider payload
→ ResearchArtifact
→ Evidence
```

Pass conditions:

- source/locator/timestamps retained
- schema validation active
- no DSA private DB/internal coupling
- stale/malformed/unavailable data is explicit
- prompt-like external content remains untrusted data

---

## 5. Portfolio acceptance

Through UI only, user can create a Portfolio and populate it using:

- manual entry
- CSV import preview + confirm

Required fields supported:

- market
- symbol
- name
- asset type
- currency
- quantity
- average cost
- Core/Tactical bucket

Pass conditions:

- import preview makes no mutation
- invalid rows are clearly reported
- symbol normalization is visible
- user explicitly confirms before commit
- committed positions reconcile
- Portfolio page reflects imported positions
- real personal holdings never appear in test fixtures/repository artifacts

---

## 6. Watchlist acceptance

Through UI only, user can:

- search/add an instrument
- remove an instrument
- view lifecycle state
- view Thesis state
- view data freshness
- view next monitoring condition

---

## 7. Initial-analysis acceptance

The user clicks:

```text
Run Initial Analysis
```

For at least one authorized real/shadow instrument, the system must persist and display a complete chain:

```text
Evidence
→ FeatureSnapshot
→ Thesis
→ specialist Agent opinions
→ conflict record if applicable
→ Devil's Advocate when required
→ Portfolio Manager risk_intent
→ RiskAssessment
→ PositionSizingRun
→ CIO
→ InvestmentDecision
```

Pass conditions:

- AnalysisRun progress is visible
- failure is explicit and bounded
- correlation/provenance is reconstructable
- no missing Risk assessment is interpreted as PASS
- no LLM-generated arbitrary final percentage is accepted
- Decision references exact versions/snapshots

---

## 8. Decision Center acceptance

The Decision detail page must display:

- Action
- confidence
- Thesis state
- Core action
- Tactical action
- current position
- proposed target/delta
- Risk gate and flags
- Evidence freshness
- reasons
- unknowns
- dissent
- invalidation/watch conditions
- next review
- relevant historical versions

The user must be able to drill down to supporting Evidence and Agent opinions.

---

## 9. Human-approval acceptance

For an eligible Decision, the UI supports:

- APPROVE
- REJECT
- REVOKE where legally valid in the state machine

Pass conditions:

- append-only human action
- actor/time recorded
- TTL enforced
- expired approval cannot execute
- revoked approval cannot execute
- Risk Veto cannot be overridden
- approval does not equal execution

---

## 10. Manual-execution acceptance

After externally placing a trade, user can record a MANUAL execution.

Required inputs:

- quantity
- price
- fees where relevant
- execution timestamp
- sanitized external reference/note

Pass conditions:

- valid approval linkage required where applicable
- fill state is coherent
- no broker order is submitted by the application
- record is immutable/auditable

---

## 11. Runtime scheduler acceptance

The running worker, not a test harness, must evaluate due work.

For at least one explicit synthetic/authorized market session:

```text
worker
→ calendar
→ due job
→ dispatcher
→ advisory lock
→ TaskRun
→ handler
→ Event/Outbox
→ Report/Analysis effect
```

Pass conditions:

- no direct dispatcher call is used as the only E2E proof
- retry is idempotent
- duplicate concurrent invocation has one business effect
- failures are durable and visible
- as-of replay works
- server local timezone is not used as business time

---

## 12. Daily-use acceptance

On the next due session after onboarding, without manual CLI invocation, the system must:

- synchronize authorized data
- evaluate Portfolio/Watchlist changes
- create/update relevant analysis
- produce Decisions where warranted
- produce a Daily Report
- surface operational/data/risk exceptions

Dashboard must clearly answer:

- what needs action
- what can continue to hold
- what is only being watched
- what new opportunities appeared
- what Risk Vetoes exist
- what approvals are pending
- whether data/jobs are degraded

---

## 13. Weekly opportunity acceptance

A weekly run must demonstrate:

```text
market universe
→ deterministic funnel
→ bounded candidate set
→ deep research only for candidates
→ Opportunities UI
```

Pass conditions:

- no indiscriminate whole-market strong-model fan-out
- candidate reason is visible
- missing Evidence is visible
- lifecycle state is visible
- no candidate is automatically traded

---

## 14. Failure-mode acceptance

Beta must explicitly verify at least:

- model provider unavailable
- invalid model schema output
- data provider unavailable
- stale Evidence
- conflicting Evidence
- Portfolio import invalid row
- RiskAssessment UNKNOWN
- Risk VETO
- scheduler retry
- duplicate job invocation
- expired approval
- revoked approval
- report unavailable
- partial AnalysisRun failure

For every case, the system must degrade safely and visibly.

---

## 15. Security/privacy acceptance

Verify:

- no real API key in repository
- no secret in browser/API read response
- no secret in logs
- no real portfolio fixture committed
- no provider raw credential in audit payload
- no unrestricted live execution adapter
- no external content treated as instructions
- dependency/security scans remain green

---

## 16. Usability acceptance

A person familiar with investing but not the repository internals must be able to complete:

```text
configure provider
→ import Portfolio
→ add Watchlist
→ run analysis
→ read Decision
→ Approve/Reject
→ record manual execution
```

using UI guidance alone.

Developer documentation may exist, but ordinary use must not depend on it.

---

## 17. Release evidence required

Before declaring Beta ready, attach or record:

- exact commit SHA
- CI run
- E2E run evidence
- fresh-install evidence
- provider test evidence with secrets redacted
- Portfolio import test using de-identified/synthetic sample
- complete analysis trace
- scheduler runtime trace
- approval/manual-execution trace
- known limitations
- unresolved human-governance decisions

---

## 18. Beta verdict

Beta passes only when every mandatory section above is PASS or explicitly marked NOT APPLICABLE by a human-approved scope decision.

A green unit-test suite alone is insufficient.

A working UI backed only by synthetic hard-coded cards is insufficient.

A working backend without user-operable UI is insufficient.

A complete domain model without runtime orchestration is insufficient.
