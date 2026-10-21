# 数据库迁移与恢复运行手册

## P6 研究主表记录（2026-10-21，无新迁移）

ADR-0026 复用既有 committee_session / agent_run / agent_opinion / committee_message / conflict_record /
risk_assessment 及证据关联表。新增 ORM 映射 agent_opinion_evidence 对应的是已有表，不是自动建库。
完成记录与报告、只追加关联回执、审计 / Outbox 同事务；取消 / 旧 Worker 不发布工件。保存失败标 ANALYSIS_RECORDING_FAILED，
不重放付费调用。GET `/api/v1/analysis-runs/{run_id}/research-records` 只读取已保存记录，旧报告不回填。

同步更新 API / Worker / 页面；仍用 0017 Schema。回滚前处理活动任务，保留全部主表、证据链接、事件和历史输入，不做数据库降级或删除。
独立策略未接入，正式 InvestmentDecision 不创建；不能通过伪造外键或现场批准政策来“修复”缺口。
所有者实例未自动升级；部署仍须单独授权、备份与恢复核验。隔离合成内存盘测试不替代真实供应商或断电恢复验收。

## P6 人工投资逻辑工作台（2026-10-21，无新迁移）

ADR-0025 沿用既有 Thesis / Evidence 引用、只追加事件 / 审计 / Outbox 表。
新接口为 `GET /api/v1/theses/{instrument_id}/workspace` 和 `POST /api/v1/theses/{instrument_id}/versions`，
页面入口为 `/thesis`。版本化保存命令必须带 request_id 和可为空的 expected_version_id，不能客户端补写 hash / 时间 / 批准。
请求级咨询锁与标的行锁、最终指针 CAS 保护并发；版本、引用与回执同事务。无实质变化不新增版本。
保存响应未知时应保留原命令核对回执，不修改请求内容或自动重发；旧基准冲突必须人工核对，不批量覆盖。

同步交付 API / 页面与 ADR-0024 的 Worker 版本输入能力，沿用 0017 Schema；本轮不自动部署或迁移所有者实例。
回滚应用前处理活动任务，保留全部版本、引用、事件与审计；可撤回新页面 / 路由，不删除历史或降级已有数据库。
部署仍需另行授权、备份及恢复核验，不能把隔离库 / 合成模型通过当作真实实例已升级。

## P6 投资逻辑输入兼容（2026-10-21，无新迁移）

新分析固定已发布 Thesis 的历史版本与支持资料；无记录按 UNKNOWN，不创建占位。
已有报告不补写；旧排队任务没有 Thesis 快照时新 Worker 明确失败，不自动读取当前记录或重放模型。
API / Worker 同步更新，升级前检查任务；回滚先停止入队、处理或取消新格式请求，旧 Worker 不得忽略快照消费。
保留全部输入、版本、报告与审计，不降级 / 删除历史。另有 certifi 证书库安全补丁，应重建锁定依赖的运行镜像，不能把旧镜像视为已修补。
本轮不更新所有者实例；正式备份 / 重启仍需明确授权。

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

## P6 政策与运行工件快照（2026-10-20，无数据库迁移）

ADR-0023 增加任务 / input_snapshot 内的 governance。旧待执行任务没有该快照时失败关闭，不从当前政策 / 工件补全；旧报告不追补。
同步更新 API / Worker，先停止入队并核对活动任务，避免旧 Worker 忽略新字段。回滚保留全部快照 / 审计，不降级数据库或删除历史。
工件改变后由用户核对费用再明确新建运行，禁止自动重放；政策指针改变不重写已冻结的历史研究。

ACTIVE 政策需要版本元数据 approved_by_actor=HUMAN、具名批准人与时间、有效时点及规范化内容 hash。
旧记录缺信息或摘要不兼容时明确拒绝，不现场补批准、不修改旧版本 hash；必须经治理创建新版本，不把测试公式激活为真实策略。
政策审阅和分析使用同一端口；可按组合查看绑定版本。真正部署到所有者实例仍需单独授权与恢复核验。

## 验证查询（核心约束与当前版本）

确认迁移 head 和可靠任务约束：

```sql
SELECT version_num FROM alembic_version;
SELECT indexname FROM pg_indexes WHERE tablename = 'task_run';
SELECT tgname FROM pg_trigger
WHERE tgname IN ('trg_audit_log_append_only', 'trg_event_log_append_only');
```
