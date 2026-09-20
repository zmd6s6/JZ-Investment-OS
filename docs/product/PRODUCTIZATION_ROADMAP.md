# Personal AI Investment OS — Productization Roadmap

> Status: PROPOSED EXECUTION PLAN  
> Authority: subordinate to `INVESTMENT_OS_MASTER_SPEC.md`, accepted ADRs, and active stage contracts  
> Purpose: convert the existing Investment OS kernel into a product that the owner can use without writing code, SQL, JSON, or curl commands  
> Safety baseline: `auto_trade=false`; no live brokerage order submission in V1

---

## 1. Product goal

The project is not considered **normally usable** merely because domain modules, APIs, tests, or UI placeholders exist.

The product reaches the first usable Beta only when a user can complete this workflow from the Web UI:

```text
First launch
→ configure market scope
→ configure an authorized model provider
→ configure an authorized data/research provider
→ import or manually enter the real personal Portfolio
→ create a Watchlist
→ review/confirm Investment Policy settings
→ run Initial Analysis
→ receive a complete Decision with Evidence / Thesis / Agent opinions / Risk / Sizing
→ Approve or Reject
→ optionally record a MANUAL execution
```

After onboarding, the normal daily workflow is:

```text
Authorized market/research data
→ Evidence
→ deterministic Features
→ Thesis update
→ specialist Agent Round 1
→ conflict detection / bounded Round 2
→ Portfolio Manager
→ Risk Manager
→ deterministic Position Sizing
→ CIO Decision
→ Decision Center / Daily Report
→ Human Approve / Reject
→ optional MANUAL execution record
→ later Outcome / Review
```

No user should need to operate Python, SQL, raw JSON, curl, or internal database tables for ordinary use.

---

## 2. Product completion terminology

Two completion levels are mandatory:

### Engineering Done

A component is implemented, tested, respects architecture boundaries, and passes required CI.

### Product Done

The component is wired into the running product and is accessible through a supported user workflow.

A class, adapter, API, or React screen that is not connected to the runtime is **not Product Done**.

Examples:

- Scheduler classes without a running worker trigger: Engineering Done only.
- Portfolio domain objects without import/onboarding: Engineering Done only.
- Model gateway interfaces without a real configurable provider: Engineering Done only.
- UI cards backed by hard-coded synthetic data: Engineering Done only.
- Approval domain objects without an approval interaction surface: Engineering Done only.

The Beta gate requires Product Done for the end-to-end workflow.

---

## 3. Target product surfaces

The Web application must ultimately expose these user-facing areas:

1. **Setup Wizard**
2. **Dashboard**
3. **Portfolio**
4. **Watchlist**
5. **Opportunities**
6. **Decision Center**
7. **Thesis / Research Detail**
8. **Reports**
9. **Settings / Providers / System Health**

The existing four PR-08 read-only views are a presentation foundation, not the final product contract.

---

## 4. First-run Setup Wizard

A fresh installation must detect that onboarding is incomplete and open the Setup Wizard.

### Step 1 — Market and asset scope

Initial supported scope should be configurable, with V1 expected to support the product structures needed for:

- A-share equities
- Hong Kong equities / ETFs
- manually managed fund positions where a suitable authorized data source exists

The user selects market scope and market timezone/calendar profiles.

### Step 2 — Model provider

The user configures one or more model profiles.

Minimum fields:

```text
name
provider_type
base_url
model_name
credential_ref
timeout_seconds
max_tokens
enabled
```

V1 implementation should provide an **OpenAI-compatible adapter** behind the existing `LLMGatewayPort`.

This must allow compatible providers without coupling domain code to vendor SDKs.

Required UX:

- create/edit/disable profile
- masked secret display
- Test Connection
- structured-output capability check
- latency/error result
- no secret returned to the browser after storage

### Step 3 — Agent/model assignment

Support:

```text
Default Model
Macro
Industry
Fundamental
Market/Quant
Event
Portfolio Manager
Risk Manager
Devil's Advocate
CIO
Review
```

V1 may assign every role to one default model, but the schema must support role-level assignment.

Every AgentRun must retain the actual provider/model used.

### Step 4 — Data / research provider

Configure an authorized provider through application ports.

Preferred first integration:

```text
ResearchProviderPort
        ↑
     DSAAdapter
```

UI must support:

- provider endpoint/config
- credential reference where required
- Test Connection
- capability display
- last successful synchronization
- data freshness/health

Provider authorization/licensing remains a human governance decision. No provider is silently enabled.

### Step 5 — Portfolio onboarding

The user must be able to:

- manually add a position
- import CSV
- import Excel if implementation cost is reasonable for the same stage
- preview and validate before commit

Broker auto-sync is not required for the first Beta.

Required import flow:

```text
Upload
→ Parse
→ Normalize symbol
→ Match/Create Instrument
→ Validate currency / quantity / cost / bucket
→ Preview
→ Human Confirm
→ Commit
→ Audit
```

An upload must never mutate the Portfolio before explicit confirmation.

Suggested import fields:

```text
account
market
symbol
name
asset_type
currency
quantity
avg_cost
bucket
```

No real personal portfolio data may be committed to repository fixtures, logs, screenshots, or tests.

### Step 6 — Watchlist

User can search/add/remove instruments and inspect lifecycle state:

```text
DISCOVER → WATCH → SETUP → BUYABLE → HOLD
```

### Step 7 — Investment Policy review

The user reviews all currently active values.

Until the owner explicitly approves real values, the product must label `TEST_DEFAULT` prominently and must not present them as real investment policy.

Real policy choices remain governed by the Master Spec.

### Step 8 — Initial Analysis

A single supported action starts the first complete shadow analysis.

```text
Run Initial Analysis
```

This does not execute a trade.

---

## 5. Model integration contract

### 5.1 Architecture

```text
AgentRuntime
   ↓
LLMGatewayPort
   ↓
OpenAICompatibleLLMGateway
   ↓
Configured provider
```

Domain code must not import model SDKs.

### 5.2 Mandatory runtime behavior

Preserve existing AgentOpinion and model-governance requirements:

- strict Pydantic/JSON schema
- factual observations require Evidence
- max two schema-repair attempts
- failures become explicit failure / INSUFFICIENT_DATA
- no free-text fallback into a valid opinion
- timeouts are bounded
- provider/model/prompt/schema/input hash/output metadata recorded
- external model output is untrusted

### 5.3 Failover

Optional for first Beta, but data model should support explicit fallback later.

Any fallback must:

- be visible in AgentRun
- never be silent
- preserve schema/invariants
- never convert unavailable analysis into BUY/ADD by default

### 5.4 Cost controls

Expose or enforce:

- per-call token ceiling
- role-level timeout
- daily token/cost budget where provider data permits
- explicit degradation behavior when budget is exceeded

---

## 6. Secret handling

API keys and provider tokens must not be stored or returned as ordinary plaintext settings.

Introduce a `SecretStore` abstraction.

Minimum V1 requirements:

- local encrypted-at-rest secret storage or another reviewed local secret mechanism
- database/config stores only `credential_ref`
- secrets excluded from logs, audit payloads, API responses, screenshots, tests, and exported reports
- UI shows masked value only
- changing a secret creates an auditable configuration event without storing the old plaintext value

A production-grade cloud secret manager is not required for the personal/local V1.

---

## 7. Portfolio product contract

Portfolio must become a user-owned operational object, not only a domain model.

Required capabilities:

- Portfolio summary
- cash
- NAV
- currency
- positions
- Core/Tactical split
- average cost
- current weight
- sector/theme exposure
- risk capacity
- latest Decision
- latest Thesis state
- reconciliation state

For every import/update, preserve auditability and business time.

Do not infer missing cost/quantity silently.

---

## 8. Watchlist and opportunity discovery

### Watchlist

User-owned monitoring list with:

- current lifecycle state
- Thesis state
- data freshness
- next monitoring condition
- latest Decision
- reason for entering/leaving the list

### Opportunities

The system must support the owner’s requirement to periodically discover candidates.

Weekly workflow:

```text
market universe
→ deterministic tradability filter
→ deterministic financial/quality filters
→ industry/growth/valuation filters
→ timing filter
→ bounded candidate set
→ AI deep research only for candidates
```

Never run expensive strong-model analysis indiscriminately over the entire market universe.

Opportunity UI must show:

- why the instrument entered the funnel
- which Evidence is available/missing
- current lifecycle state
- what condition is required to advance
- whether Portfolio capacity exists

---

## 9. Runtime Analysis Orchestrator

Create an application-level orchestration use case such as:

```text
InvestmentAnalysisOrchestrator
```

Input contract should include:

```text
portfolio_id
instrument_id or scope
as_of
trigger
correlation_id
```

The orchestrator is responsible for wiring already-governed components, not replacing them.

Expected flow:

```text
authorized data sync
→ Evidence validation
→ FeatureSnapshot
→ Thesis evaluation/update
→ frozen AnalysisContext
→ specialist Agent Round 1
→ deterministic conflict detection
→ targeted Round 2 + Devil's Advocate
→ Portfolio Manager risk_intent
→ Risk Assessment
→ deterministic Position Sizing
→ CIO
→ InvestmentDecision
→ immutable persistence
→ report/update event
```

All existing fail-closed Risk, Evidence, sizing, approval, and immutability constraints remain authoritative.

---

## 10. AnalysisRun

Long-running analysis requires a durable user-visible run object.

Suggested states:

```text
QUEUED
RUNNING
PARTIAL
SUCCEEDED
FAILED
CANCELLED
```

Required visibility:

- trigger
- as_of
- started/finished
- current stage
- degraded/failed components
- correlation id
- no secret/raw sensitive payload leakage

API/UI must provide a supported **Run Analysis Now** action.

This action runs analysis only. It never creates a live brokerage order.

---

## 11. Decision Center

The Decision Center is the primary daily interaction surface.

For each Decision show:

- instrument
- Action
- confidence
- Core action
- Tactical action
- current weight
- proposed target weight
- proposed delta quantity
- Thesis state
- Risk gate
- major risk flags
- Evidence freshness
- top reasons
- unknowns
- dissent
- watch/invalidation conditions
- next review
- exact Decision/Thesis/Policy/Strategy/Prompt/Formula versions

Agent opinions must be drill-down details, not a substitute for the governed Decision.

---

## 12. Human approval and manual execution

Provide supported user actions:

```text
APPROVE
REJECT
REVOKE
```

Approval must use the existing immutable/fail-closed domain semantics.

V1 remains:

```text
auto_trade=false
```

No broker order endpoint is included in the Beta requirement.

After the user performs a trade externally, the UI may record a `MANUAL` execution:

- quantity
- price
- fees
- executed_at
- sanitized external reference / note

Approval is not execution.

A Risk Veto can never be overridden by the UI.

---

## 13. Scheduler and worker runtime

Scheduler is Product Done only when the running worker actually evaluates due jobs and dispatches them.

Required runtime chain:

```text
investment-worker
→ authorized/explicit Market Calendar
→ due jobs
→ durable dispatcher
→ advisory lock
→ TaskRun
→ business handler
→ Event/Outbox
→ Report/Decision effects
```

Required cadences:

- Daily
- Weekly
- Monthly
- Quarterly

Scheduling must preserve explicit market timezone, business `as_of`, retry/replay, idempotency, bounded failure, and no server-local-time assumptions.

Integration/E2E verification must prove runtime dispatch; tests that directly call a dispatcher are insufficient as the only proof.

---

## 14. Dashboard contract

The Dashboard should answer:

1. What requires action today?
2. What changed in my Portfolio?
3. Are there active Risk Vetoes?
4. Which Decisions await approval?
5. Which Evidence/Data is stale?
6. What new opportunities appeared?
7. Did scheduled jobs succeed?
8. What needs manual attention?

Do not make the Dashboard a generic market-news feed.

---

## 15. Reports

Daily/weekly/monthly reports should be generated from validated internal objects and clearly separate:

- facts
- deterministic calculations
- Agent judgments
- assumptions/unknowns
- human decisions

Daily report should include at minimum:

- action required
- continue holding
- watch
- new discoveries
- risk/data/operational exceptions

---

## 16. API surface expected for Beta

Exact URI naming can change through reviewed API design, but the product must expose equivalent capabilities.

### Providers / Settings

```text
GET/PUT settings
GET/POST model-providers
POST model-providers/{id}/test
GET/POST data-providers
POST data-providers/{id}/test
```

### Portfolio / Watchlist

```text
GET portfolio
POST portfolio/import/preview
POST portfolio/import/commit
POST portfolio/positions
GET/POST watchlist
DELETE watchlist/{id}
```

### Analysis

```text
POST analysis-runs
GET analysis-runs/{id}
```

### Decisions

```text
GET decisions
GET decisions/{id}
POST decisions/{id}/approve
POST decisions/{id}/reject
POST decisions/{id}/revoke
POST decisions/{id}/manual-executions
```

### Reports / Operations

```text
GET reports/daily/latest
GET reports/weekly/latest
GET reports/monthly/latest
GET task-runs
```

Every mutation requires validation, audit, idempotency where applicable, and authorization appropriate to the personal deployment model.

---

## 17. Productization delivery phases

### P0 — Finish current PR-08 correctly

Before starting new productization stages:

- wire scheduler into actual worker/runtime
- prove runtime dispatch through integration/E2E
- correct PR-07 merge SHA documentation
- update stale README current capabilities/limitations
- retain synthetic/read-only constraints of the current PR-08 stage

PR-08 must be reviewed and merged before P1 implementation.

### P1 — Productization Contract & Onboarding Skeleton

Deliver:

- this productization contract accepted into the repository
- Setup Wizard shell
- onboarding state
- Settings navigation
- explicit Beta acceptance reference
- no real secrets/providers yet

Acceptance: fresh install reaches a deterministic onboarding workflow instead of an unexplained synthetic dashboard.

### P2 — Settings, Secret Store & Provider Profiles

Deliver:

- SystemSettings
- ModelProviderProfile
- DataProviderProfile
- RoleModelAssignment
- SecretStore
- provider CRUD/test APIs
- Settings UI

Acceptance: provider secrets can be configured safely and connection tests are visible/auditable.

### P3 — Real Model Runtime

Deliver:

- OpenAI-compatible LLM adapter
- real configurable model path through existing `LLMGatewayPort`
- role assignment
- timeout/budget/error handling
- provider/model metadata in AgentRun

Acceptance: a synthetic Evidence fixture can run the real authorized model through the complete AgentOpinion schema path without weakening fail-closed behavior.

### P4 — Authorized Data Provider Runtime

Deliver:

- operational DSAAdapter or another explicitly authorized provider
- provider health/freshness
- normalized Evidence ingestion
- real/shadow data boundaries

Acceptance: one authorized real instrument can produce traceable Evidence without direct DSA/private DB coupling.

### P5 — Portfolio & Watchlist Product

Deliver:

- Portfolio UI/API
- manual position entry
- CSV import preview/confirm
- reconciliation
- Watchlist CRUD
- Instrument search/normalization

Acceptance: owner can load a personal Portfolio without touching SQL/JSON/code; no real portfolio data enters repository assets.

### P6 — End-to-End Analysis Orchestration

Deliver:

- AnalysisRun
- InvestmentAnalysisOrchestrator
- Run Analysis Now
- progress/failure visibility
- complete Evidence → Decision persistence

Acceptance: one selected instrument can complete a full shadow investment cycle using configured model/data providers.

### P7 — Interactive Decision & Approval

Deliver:

- Decision list/detail backed by real API
- Evidence/Thesis/Agent/Risk/Sizing drill-down
- Approve/Reject/Revoke
- manual execution record

Acceptance: owner can process a Decision entirely through UI; no live broker order is possible.

### P8 — Daily AI Team Runtime

Deliver:

- scheduled data sync
- Portfolio/Watchlist Evidence diff
- automatic analysis triggering
- daily report
- weekly opportunity screening
- monthly portfolio review
- explicit failure/degraded states

Acceptance: a due market session causes the running worker to produce the expected durable analysis/report effects without manual CLI invocation.

### P9 — Beta Acceptance

Run the complete acceptance gate in `docs/product/BETA_ACCEPTANCE.md`.

No P9 pass means no claim that the product is normally usable.

### PR-09 — Outcome, Review/Learning, Hardening & Release

PR-09 follows a usable Beta and then completes:

- Outcome
- Review/Attribution
- Agent performance evaluation
- StrategyProposal
- Backtest
- Shadow validation
- human-governed activation
- backup/restore
- security/performance hardening
- traceability matrix
- release checklist

---

## 18. Required engineering discipline for productization

From P1 onward:

- Do not implement only a class; wire it into runtime.
- Do not implement only an API; connect the supported UI flow.
- Do not implement only a UI; back it with real application APIs except explicit demo states.
- Do not use hard-coded synthetic cards to claim a product workflow is complete.
- Every mutation must have normal/failure/boundary tests.
- Critical workflows require E2E coverage.
- Keep real personal data out of repository fixtures.
- Keep provider secrets out of logs and API responses.
- Preserve fail-closed Risk and approval semantics.
- Preserve `auto_trade=false`.
- Do not weaken the Master Spec to accelerate productization.

---

## 19. Human-governance decisions that remain outside Codex authority

Codex may implement configurable mechanisms but must not choose these real values on its own:

- real Investment Policy limits
- actual provider/license authorization
- retention/privacy/cost boundaries
- real approval actor and TTL
- model-provider budget limits where they affect owner spending
- real data-source precedence
- brokerage integration
- enabling live execution
- StrategyProposal activation

When one of these decisions blocks only a subfeature, Codex should continue all independent safe work.

---

## 20. Productization success statement

The first Beta is successful when the owner can truthfully say:

> I can start the stack, open the browser, configure my authorized model and data provider, import my Portfolio, manage a Watchlist, run or receive scheduled analysis, inspect Evidence/Thesis/Agent/Risk/Sizing, receive a CIO Decision, Approve or Reject it, and record a manual execution — without touching source code, SQL, raw JSON, or internal tooling.

Until this statement is demonstrably true, the project remains in productization even if individual engineering stages are green.
