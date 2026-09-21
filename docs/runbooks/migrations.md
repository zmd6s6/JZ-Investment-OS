# 数据库迁移与恢复运行手册

## 范围与安全

PR-02 引入修订版 `20260917_0001`。它创建核心 Schema、Evidence 引用关联表、只追加保护、乐观锁列和可靠性表；不会激活 Policy、导入个人组合数据或启用执行。

开发环境只能使用合成数据。绝不对已填充或类似生产的数据库执行降级。降级仅用于空数据库验证和本地重置，不是数据保全策略。

## 升级

```text
docker compose up --detach --wait postgres
uv run alembic upgrade head
uv run alembic current
```

Compose 通常会在 API 和 Worker 启动前，借由一次性 `investment-migrate` 服务完成升级。

## 空数据库往返验证

```text
uv run alembic downgrade base
uv run alembic upgrade head
uv run pytest -m integration --no-cov
```

这会销毁 PR-02 Schema 中的所有行，仅允许对可丢弃的数据库执行。

## 已填充数据库恢复

1. 停止 API 和 Worker 写入端。
2. 记录 `alembic current` 和应用提交。
3. 迁移前创建并验证 PostgreSQL 备份。
4. 通过迁移服务执行一次 `alembic upgrade head`。
5. 运行迁移和应用 smoke 检查。
6. 升级失败时，保留数据库和日志，将已验证备份恢复到单独数据库，并发布经审查的前向修复迁移。不得编辑已接受迁移或删除审计历史。

初始修订在 PostgreSQL 上是事务性的。失败的 DDL 事务会保留原 Schema。应用写入和 Outbox 写入同样共享一个显式 Unit of Work。

## 验证查询

确认迁移 head 和可靠任务约束：

```sql
SELECT version_num FROM alembic_version;
SELECT indexname FROM pg_indexes WHERE tablename = 'task_run';
SELECT tgname FROM pg_trigger
WHERE tgname IN ('trg_audit_log_append_only', 'trg_event_log_append_only');
```
