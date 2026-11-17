# ADR-0057 - Separate local weekly portfolio/watchlist review

- Status: Proposed; effective only with independent Review Gate and actual MVP-408 integration.
- Date: 2026-11-17. Supplements accepted 0003, 0008, 0012, 0037, 0050 and 0052; does not rewrite them.

## Decision

Reuse the established typed local portfolio/evidence capture, scoped member locks, reference quote reader and reliable TaskRun unit of work, with an independent weekly authorization and table family. Daily, monthly and opportunity consent never confer weekly permission. No provider/model capability is injected into this reader; profiles and token/currency/cost budgets remain empty/NONE/zero. No Analysis, Decision, Approval, Execution, Policy or Strategy mutation is offered. auto_trade=false.

An authorization freezes the complete selected portfolio and explicitly selected watchlist members, calendar import UUID/source/version/hash, complete Monday-Sunday coverage, local sources, validity, retention and terminal revoke terms. Save is paused; separate UUID-idempotent, version-checked explicit enable recaptures scope and calendar. Preview, save, enable and final Worker commit validate current source and scope. Scope capture locks the portfolio parent, existing positions, selected watchlist rows and instrument identities before the calendar pointer; a confirmed pause/revoke serializes with the final report transaction.

Session-only calendars cannot prove closed-day coverage. Weekly therefore additionally requires an explicit OPEN/CLOSED entry for every date, with no missing, duplicate, extra or inferred weekday/holiday. Server independently rereads the persisted source/session hash, checks every OPEN date against the imported sessions and every CLOSED date against their absence, and persists the complete date manifest as immutable normalized weekly_calendar_day rows tied to the immutable authorization. It verifies those rows against the frozen payload on every configuration read. A boolean acknowledgement alone is insufficient. Closed-day facts remain SOURCE_DECLARED, not independently exchange/provider verified; the UI and report disclose this limit. Untrusted dates never grant data/model permission. A changed import/hash or member scope requires a new paused revision and explicit enable.

Complete weeks close only after Sunday in the explicit SSE/SZSE Asia/Shanghai timezone. Reports distinguish last explicit business close, current knowledge/read time and recorded time. The mutable current ledger is not a historical week-end snapshot. Historical holdings/returns are NOT_PROVIDED; evidence and bucket changes compare only actual available same-revision prior captures. Evidence ownership, allowed source, hash and four-time/as-of gates reuse the persisted local reader. Missing/expired prices never become zero NAV or Risk PASS. Watchlist membership and quote/evidence provenance are frozen in the same local input payload.

## Persistence and recovery

Preserve foundation 0027 and extend it with 0028 (parent0027, parent0026); no old report is rewritten. 0028 adds audit/operational metadata, typed reference FKs, immutable per-date coverage and a reconstructible singleton fair cursor. Reports remain unique per schedule/week across authorization revisions. TaskRun key includes schedule/revision/full Monday date. Successful TaskRun, report, normalized evidence/reference links, Event/Audit/Outbox commit in one transaction. Failed local attempts roll back all business effects, leave bounded failure history and retry at most three times per revision. No uncertain paid work exists or is replayed.

At most50 enabled configurations and four planned periods are checked per poll. The durable locked cursor advances only through examined records, wraps at end, survives Worker restart and isolates invalid configurations. For finite records and continuing polls every configuration is eventually examined; cursors do not grant authorization. UI/API use bounded stable configuration/history/task pages and exact immutable report replay. Offset pages are live reads, not a whole-database snapshot; refresh after concurrent changes. Expired bodies are refused while permitted audit metadata/hash remain.

Both migrations permit empty downgrade and refuse destruction once authorization/report history exists. Application rollback first pauses weekly schedules, retains all tables/history and forward-fixes. Adding audit defaults labels legacy rows as unverified; no legacy authorization is automatically enabled or treated as a complete new prepared snapshot.

## Alternatives and validation

Rejected: Daily/monthly consent reuse, implicit weekdays, caller boolean as provenance, fabricated historical ledger/return, fixed-first50 scans, in-memory cursors, nontransactional reports, overwriting history and paid/automatic investment fan-out. No new production dependency or investment policy choice.

Required actual evidence: normal/failure/boundary named PostgreSQL API/Worker tests; full week/timezone/manifest/source and scope drift; authenticated commands, CAS and UUID receipts; two Workers, pause/revoke locks, bounded retry/rollback/restart, >50 reachability, immutable history and empty/nonempty migration recovery; production API/Worker/Edge UI plus responsive layout, failed reads and explicit UNKNOWN. Final HEAD CI and independent Gate are separate; Owner deployment and Checkpoint C acceptance remain PENDING.
