# 项目状态

> 这是唯一的当前状态记录。推进阶段时必须在同一变更中更新它。

## 当前快照

- 项目：Personal AI Investment OS
- 当前模式：`DEVELOPMENT`
- 活跃路线图阶段：`PR-08 — 调度器、报告与个人 UI`
- 阶段状态：`READY_FOR_REVIEW`
- 实盘交易：`FORBIDDEN`
- 权威规范：`INVESTMENT_OS_MASTER_SPEC.md`
- 上次状态更新：`2026-09-21`

## 已建立

- 已有 Master Engineering Specification，作为项目 SSOT。
- `AGENTS.md` 中已有根 Codex 工作约定。
- `docs/WORKING_MODE.md` 中已有持久工作模式。
- 已有 PR/ADR/阶段文档约定。
- 已有 Python 3.12 项目元数据和 `uv.lock`。
- 已有 API 和 worker 引导健康路径及自动化测试。
- PostgreSQL/API/worker Compose 配置可成功解析。
- PostgreSQL、API 和 worker 镜像均可构建并达到健康状态；端口 8100 的端到端冒烟测试通过。
- 已配置 CI、OpenAPI 契约生成、依赖/许可证检查和密钥扫描。
- 远程 GitHub CI 在 PR-01 分支上通过质量、Compose 冒烟和独立 Gitleaks 任务。
- ADR-0001 至 ADR-0010 是已接受的 Master-Spec 实施决定。
- 已有纯领域值、Investment Policy 和 Instrument/Thesis/Decision/Strategy 状态机。
- Core/Tactical、Risk Veto、人工批准和 Learning 权限不变量均失败闭合。
- Decision Risk Gate 是明确的（`UNKNOWN|PASS|VETO`）；缺失评估不能解释为 PASS。
- ADR-0011 记录纯领域和严格 Policy 边界实施决定。
- ADR-0012 记录美国、上海和深圳场所的显式合成日历语义；A 股真实数据/供应商和交易授权仍未获批准。
- Alembic 修订 `20260917_0001` 创建全部 Master-Spec 核心表和规范化 Evidence 引用表，含 UUID、numeric、
  timestamptz、约束和索引契约。
- Policy、Position、Thesis 和 Decision 持久化使用乐观版本检查。
- 审计/事件历史和不可变工件具有数据库强制的仅追加保护。
- 已针对 PostgreSQL 16 验证 Unit of Work、事务性 outbox、咨询锁和幂等 TaskRun 执行。
- Compose 在 API/worker 启动前通过成功的一次性服务应用迁移。
- 远程 GitHub Actions 运行 `35295158962` 在当前 PR-02 审查头
  `cfb707d4f463a37605d6cae503f5a1f42aaceea9` 上通过质量、Compose 冒烟和独立 Gitleaks 任务。
- PR-02 已接受并由 PR #2 合并至 `main`，提交为 `72a64ff797c25ec1c1e5e8d8196f9fe85ad44d5e`。
- PR-03 已接受并由 PR #3 合并至 `main`，提交为 `5dc99027a460a7f29d9b4021a982af726f2363f2`。
- PR-04 已接受并由 PR #4 合并至 `main`，提交为 `a0a9acdca6b5c75b2193eede51dd1a6e2310a22f`。
- PR-05 已接受并由 PR #5 合并至 `main`，提交为 `b141be8ada55f44b2840e692c6b838c3df0913ca`。
- PR-06 已接受并由 PR #6 合并至 `main`，提交为 `3009b2b52289b6a6552dac5e3676e41f7ce8bb53`。
- PR-07 已接受并由 PR #7 合并至 `main`，提交为 `2838301827fd386f38dba5f58ab49a88db26d912`。
- PR-08 审查 blocker 已修复：worker 运行时只能分派带有限重放、持久 TaskRuns、事务性 outbox 和仅模拟
  报告的显式配置合成日历；默认 Compose 环境不设置日历。

## 尚未实现或验证

- 超出聚焦 PR-02 仓库和可靠性原语的业务持久化工作流；
- 除已实施 PR-07 S10、聚焦 PR-01/PR-05 领域关卡切片和 PR-08 S12 调度器重放/幂等覆盖外的验收场景覆盖；
- Learning 工作流功能、结果复核、发布加固和恢复演练（PR-09）。

不得仅因 Master Spec 存在就推断上述任何事项已完成。

## 下一项授权工作

PR-08 在 `codex/pr-08-scheduler-reports-ui` 上为 `READY_FOR_REVIEW`，它创建自 GitHub 与
`origin/main` 确认的 PR #7 合并提交 `2838301827fd386f38dba5f58ab49a88db26d912`。它只能实施合成的
调度器/重放、报告和个人只读 UI 契约。实盘经纪商执行、凭证、真实 Portfolio 数据和真实投资 policy
选择仍被禁止。

## 已记录范围决定

- **PR-05 范围协调（2026-09-20 批准）：** 将 S1/S2 最终 `WATCH`/`AVOID` Action 断言延后至 PR-07，
  因为 CIO/Decision 路径在该阶段范围内。PR-05 为场景前置输入保留合成研究与委员会夹具，且不得创建
  CIO Decision。
- 已交付 Policy 为 `TEST_DEFAULT`；选择真实限制仍是未来人工决定。
- **A 股范围（2026-09-20 批准）：** 纳入 SSE/SZSE 日历语义和合成研究/模拟夹具。这不批准数据供应商、
  真实 A 股 Portfolio 数据、A 股 policy 限制、经纪商执行或实盘交易。所有者已授权阶段分支提交和推送；
  合并到 `main` 仍为独立人工动作。

## 路线图

| 阶段 | 状态 | 人工验收 | 备注 |
|---|---|---|---|
| PR-00 | ACCEPTED | 已合并到 `main` | 与已合并的基础工作一并交付并接受 |
| PR-01 | ACCEPTED | 2026-09-17 已合并到 `main` | PR #1 合并提交 `45b024109775e233049b8c7df1792b6190c67a58` |
| PR-02 | ACCEPTED | 2026-09-18 已合并到 `main` | PR #2 合并提交 `72a64ff797c25ec1c1e5e8d8196f9fe85ad44d5e` |
| PR-03 | ACCEPTED | 2026-09-18 已合并到 `main` | PR #3 合并提交 `5dc99027a460a7f29d9b4021a982af726f2363f2` |
| PR-04 | ACCEPTED | 2026-09-19 已合并到 `main` | PR #4 合并提交 `a0a9acdca6b5c75b2193eede51dd1a6e2310a22f` |
| PR-05 | ACCEPTED | 2026-09-20 已合并到 `main` | PR #5 合并提交 `b141be8ada55f44b2840e692c6b838c3df0913ca` |
| PR-06 | ACCEPTED | 2026-09-20 已合并到 `main` | PR #6 合并提交 `3009b2b52289b6a6552dac5e3676e41f7ce8bb53` |
| PR-07 | ACCEPTED | 2026-09-20 已合并到 `main` | PR #7 合并提交 `2838301827fd386f38dba5f58ab49a88db26d912` |
| PR-08 | READY_FOR_REVIEW | 待定 | 调度器、报告、UI；已记录完整本地验证 |
| PR-09 | PLANNED | 待定 | Outcome、学习、加固、发布 |

## 状态更新规则

- 没有已记录验证证据时，不得将阶段标记为 `READY_FOR_REVIEW`。
- 当需要人工治理审查时，不得仅凭 Codex 权限将阶段标记为 `ACCEPTED`。
- 添加 blocker 时需包含所有者、精确条件、尝试过的替代方案和解除事件。
- 详细检查清单和证据应保留在对应 `docs/stages/PR-XX.md`；本文件应保持简洁。
