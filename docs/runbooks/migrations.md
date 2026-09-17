# Database migration and recovery runbook

## Scope and safety

PR-02 introduces revision `20260917_0001`. It creates the core schema, evidence-reference join
tables, append-only guards, optimistic-lock columns, and reliability tables. It does not activate a
Policy, import personal portfolio data, or enable execution.

Use only synthetic data in development. Never run a downgrade against a populated or production-like
database. The downgrade is an empty-database verification and local reset mechanism, not a data
preservation strategy.

## Upgrade

```text
docker compose up --detach --wait postgres
uv run alembic upgrade head
uv run alembic current
```

Compose normally performs the upgrade through the one-shot `investment-migrate` service before API
and worker startup.

## Empty-database round trip

```text
uv run alembic downgrade base
uv run alembic upgrade head
uv run pytest -m integration --no-cov
```

This destroys all rows in the PR-02 schema. It is permitted only for a disposable database.

## Populated-database recovery

1. Stop API and worker writers.
2. Record `alembic current` and the application commit.
3. Take and verify a PostgreSQL backup before migration.
4. Apply `alembic upgrade head` once through the migration service.
5. Run migration and application smoke checks.
6. If an upgrade fails, retain the database and logs, restore the verified backup into a separate
   database, and issue a reviewed forward-fix migration. Do not edit an accepted migration or delete
   audit history.

The initial revision is transactional on PostgreSQL. A failed DDL transaction leaves the prior
schema intact. Application writes and outbox writes likewise share one explicit Unit of Work.

## Verification queries

Confirm the migration head and reliable-job constraints:

```sql
SELECT version_num FROM alembic_version;
SELECT indexname FROM pg_indexes WHERE tablename = 'task_run';
SELECT tgname FROM pg_trigger
WHERE tgname IN ('trg_audit_log_append_only', 'trg_event_log_append_only');
```
