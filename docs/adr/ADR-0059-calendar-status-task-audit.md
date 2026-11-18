# ADR-0059 — Read-only original Calendar STATUS_ONLY task audit

- Status: Proposed; effective only after independent Gate and actual MVP-410 integration.
- Date: 2026-11-18. Supplements accepted ADR-0003/0008/0010/0012/0037 without rewriting them.

## Decision

Add GET /api/v1/calendar/tasks and /tasks/{task_run_id} through the existing typed Calendar application port. Preserve the existing overview response and its deliberately bounded recent30 summary. Fixed50 pages use descending original created_at and UUID keysets, with a namespace-bound validated opaque cursor. Retrying a task changes started_at, not the page boundary. Pages are live reads of recorded status, not a transaction-wide snapshot; refresh discovers newly inserted rows above the cursor.

Both new GET and HEAD paths require the same configured local Bearer token as the already integrated weekly audit endpoints. HEAD remains unsupported by the router after authentication; OPTIONS and existing safe reads retain their middleware/CORS behavior. No write, scheduling, dispatch/retry, import, enable/pause, external provider/model request or fee capability is exposed through this read port.

Resolve the literal calendar_status_ namespace with escaped SQL underscores. Validate the original calendar-status:venue:business_date:import_uuid key against task_name, original immutable import and session, source calendar content hash, scheduled_for and the original input fingerprint. Do not follow active_import_id. Legacy keys without an import UUID or missing/mismatched references show explicit UNKNOWN and never use a current source as historical truth.

A report must be the unique calendar.status.report Event for that task, have aggregate_type calendar_product/schema1.0, match the original source, date and input business time, and pass the original strict report schema. Its persisted Audit after_hash must equal the hash of the actual original Event JSON, with matching task entity, operation and Event correlation_id. Return that original JSON and persisted hash; never hash a DTO with inserted defaults or confuse calendar_hash with report hash. If any association is unverified, show no report or hash and a named unknown. Event correlation_id need not equal TaskRun correlation_id, which changes on retries. FAILED without an Event remains a failure. No SKIPPED state or complete per-attempt timeline is invented.

## Alternatives and consequences

Offset/started_at pagination was rejected because retries move rows. Reading the current configuration was rejected because sourceA failures and sourceB successes must survive later pointer changes. No production dependency, database migration, scheduler or time storage semantics changes are required. Queries remain bounded, except the existing at-most1000-session original calendar hash verification on exact detail.

## Verification and rollback

Named PG/API and UI tests cover30/31,50/51,102 calendar tasks plus105 other-namespace tasks, ties, retry timestamps, exact out-of-page reads, source correction, malformed/legacy/mismatched references, sanitized failure, auth/CORS/HEAD/OPTIONS and zero mutations/full-table hashes. Independent API/PG/CLI Worker/browser evidence separately labels seeded old FAILED rows and a new real Worker report. Final commands/results belong to MVP-410 work item; independent Gate and Owner deployment/acceptance remain separate.

Rollback application/UI together while preserving all task, import/session, Event, Audit and Outbox records. No database rollback or deletion is needed. No investment governance, source/cost permission, Policy/Strategy, Approval, live order or auto_trade=false change is authorized.
