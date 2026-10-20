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

## P6 预览与输入快照（20261015_0016）

从 `20261010_0015_analysis_run` 前向新增 `research_preview` / `research_confirmation`，两表仅追加；
增加 AnalysisRun 已有 `input_snapshot` 不得修改 / 删除的数据库守卫。不重写已有 Evidence、组合或旧报告。

部署前暂停 API / Worker 写入并保存 PostgreSQL 自定义格式备份，使用 `pg_restore --list` 检查归档可读；
通过同一部署的 `investment-migrate` 升级后再启动 API。必须保留提供方凭据卷、加密主密钥和本机会话库。

应用回滚：使用上一镜像、保留 0016 数据库与新增表 / 触发器。旧 API 可继续读写不带快照的运行，
新快照仍受保护；不能为了回滚界面删除审计历史。
仅当预览与快照均为空时允许 Schema 降级；非空降级会明确拒绝，采用前向修复。
升级异常时 PostgreSQL DDL 事务回滚；如需数据恢复，应将备份恢复到新的、明确指定的数据库后核对，禁止覆盖原库。

自动回归覆盖：空库往返、0015 合成旧报告升级后不变、旧代码写入兼容、空预览降级保留旧报告、
非空预览禁止降级、快照 UPDATE / DELETE 拒绝。仅在专用可丢弃库运行，测试夹具会清空表。

## P6 持久化后台任务（20261016_0017）

从 0016 新增 `analysis_job` 和只追加 `analysis_progress`；旧报告不追补阶段事件。
API 先固定输入并返回 202；Worker 消费显式队列，Compose 为 Worker 只读挂载既有凭据卷并传入同一加密主密钥。
不更换主密钥、不复制秘密到数据库，不配置任何新供应商。未配置 / 停用 / 预算不足仍由既有网关失败关闭。

升级须先备份并校验归档，然后迁移，再同步更新 API / Worker，避免只部署新页面而旧 Worker 永不消费队列。
正常服务重启：排队任务继续；已 RUNNING 且咨询锁已释放的任务标 `ANALYSIS_INTERRUPTED`，不会自动重复模型费用。
取消请求在阶段边界生效；不能保证已经发出的上游调用停止或不计费。

回滚应用须保留任务 / 进度历史和快照守卫；先检查待处理任务，旧 Worker 无法消费新版队列。
仅空任务表允许 Schema 降级，非空拒绝破坏性删除并采用前向修复。恢复备份只使用明确的新数据库，不覆盖原库。

## P6 单次模型快照（2026-10-20，无数据库迁移）

本次新增请求中的 model_plan，继续使用 0017 队列和 input_snapshot 守卫。必须同步更新 API / Worker；
新 Worker 遇到没有模型快照的旧排队任务会明确失败，不从当前设置补全或自动发起费用。
历史报告保持可读；显式重新发起是带新配置与新费用确认的新运行。

回滚先停止入队，核对并处理 / 取消新版待执行任务，再同步回滚 API / Worker；禁止让旧 Worker 消费新版请求，
以免忽略模型固定字段。保留队列、快照、阶段和审计，不删除历史、不回退数据库。详见 ADR-0020。

## P6 单次行情计划（2026-10-20，无数据库迁移）

新增可选 market_plan 与结果内的行情尝试记录，仍用 0017 队列和快照守卫；新增 ADR-0021。
新客户端默认不读取行情；旧请求没有该字段也按空计划执行，不按当前启用档案自动加源。
旧报告不追补；重试保留原来源 ID / 顺序，但重新验证、固定当时配置，失效不换源。

API / Worker 必须同步更新。回滚先停止入队、检查并处理 / 取消新版待执行任务，再同步回滚；
禁止旧 Worker 忽略新计划而按旧链自动取价。保留全部快照 / 阶段 / 尝试审计，不删除历史或降级数据库。
无新增依赖、实际数据源授权或投资规则变化。部署到所有者实例仍需明确授权，不因无迁移而跳过备份 / 恢复核验。

## P6 行情尝试事件（2026-10-20，无数据库迁移）

ADR-0022 复用既有只追加 event_log，事件类型为 ANALYSIS_MARKET_ATTEMPT；按 analysis_run / 运行 ID 读取。
每个来源批次进入适配器前提交 STARTED，返回后追加结果，与审计 / Outbox 同事务。
只存在开始事件时保留未知，不根据当前档案补写、不自动重放，也不能据此判断上游已收到请求或费用为零。
取消可阻止下一来源，但已发出的请求仍可能返回并计费；其结果允许在取消请求后追加、在运行终态前保存。

同步更新 API / Worker / 页面，沿用 0017 Schema。回滚先停止入队并处理活动任务，保留所有事件和快照；
旧页面不显示新账本不等于没有调用。不得为兼容回滚删除事件，所有者部署仍须明确授权。
事件记录失败时停止后续行情调用，先检查数据库健康和已保存记录，再对照供应商账单，由用户决定是否新建运行。

## 验证查询（核心约束与当前版本）

确认迁移 head 和可靠任务约束：

```sql
SELECT version_num FROM alembic_version;
SELECT indexname FROM pg_indexes WHERE tablename = 'task_run';
SELECT tgname FROM pg_trigger
WHERE tgname IN ('trg_audit_log_append_only', 'trg_event_log_append_only');
```
