# ADR-0058 — Read-only weekly opportunity task audit pagination

- Status Proposed. Effective only after final independent Gate and MVP-409 integration.
- Date 2026-11-18. Supplements accepted ADR0045 and the integrated ADR0054 scope.

## Decision

Add authenticated GET tasks and tasks/{task_run_id} under the existing separate weekly and complete-weekly resources. Keep their overview response and save/mode semantics compatible. A shared typed application history contract carries an explicit protocol discriminator and is implemented by one SQL read adapter. New reads require the existing local Bearer token. Other existing reads and OPTIONS retain their middleware behavior. No mutation, dispatch/retry, Event/Outbox, provider/model or fee operation is available through this port.

Each page returns at most50 records and an opaque cursor carrying protocol, original created_at and task UUID. Sort descending by created_at then UUID. TaskRun retries can change started_at/status/attempt, so started_at cannot provide the stable page boundary. Existing rows keep their original created_at. Cursor input is validated and cannot cross protocols. Newly inserted rows above the cursor are discovered on refresh. Pages are live reads of current recorded statuses rather than a transaction-wide snapshot or complete per-attempt timeline. GET never backfills missing records.

Exact task reads are independent of loaded pages. Resolve schedule/revision/week from the recorded task namespace and idempotency key, then verify the original frozen revision hash, protocol, schedule, normalized members and TaskRun input_hash. Never follow the mutable configuration's current revision. Resolve calendar/source/template identifiers from that original revision and immutable calendar record. Expose missing/legacy/unverified references as explicit unknowns. Validate result revision/week/protocol before using it. Link an artifact only through its original result/event association and existing exact v1/v2 Funnel read validation. Reuse those existing Funnel detail pages without recomputation.

Original source declarations remain SOURCE_DECLARED/UNVERIFIED. A record of attempt3 does not establish three independently retained attempt events. Current task status, timestamps and errors are recorded facts, and unsupported history remains NOT_PROVIDED. Existing immutable artifacts/hashes, original capacity50, authorization windows, paused defaults, Risk Veto, human Approval, deterministic sizing and auto_trade=false are unchanged.

## Verification and recovery

Named real PostgreSQL/API tests cover50/51-plus, more than100 mixed protocol records, tied creation ordering, retry started_at changes, exact out-of-page reads, original revisions, FAILED/SKIPPED without artifacts, malformed/missing/legacy/mismatched references, GET authentication and unchanged full business table hashes. UI covers Chinese errors, retained rows on page failure, cleared stale detail/link on failure, ignored late responses, protocol changes, direct URL/refresh, existing artifact navigation and390px. A dedicated synthetic API/DB/production Worker produces real current records while seeded older audit rows are labelled separately.

No production dependency, schema or migration is added. Roll back application/UI while preserving all records. No Owner instance action or new source/cost authorization is granted. Owner deployment and PRODUCT08/Checkpoint acceptance remain pending; MVP402 stays REVIEW/PARTIAL and501BLOCKED.
