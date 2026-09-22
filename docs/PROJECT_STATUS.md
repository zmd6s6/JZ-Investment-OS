# 项目状态

> 这是唯一的当前状态记录。推进阶段时必须在同一变更中更新它。

## 当前快照

- 项目：Personal AI Investment OS
- 当前模式：`DEVELOPMENT`
- 活跃路线图阶段：`PRODUCT-04 — 已授权数据供应商运行时`
- 阶段状态：`PLANNING`
- 实盘交易：`FORBIDDEN`
- 权威规范：`INVESTMENT_OS_MASTER_SPEC.md`
- 上次状态更新：`2026-09-22`

## 已建立

- 主工程规范、根工作约定、持续工作模式以及 ADR/阶段文档约定均已建立。
- Python 3.12 项目元数据、锁文件、健康检查、Compose、CI、OpenAPI、依赖/许可证检查与密钥扫描已具备。
- ADR-0001 至 ADR-0015 已被接受；其中明确了模块化单体边界、DSA Adapter、多提供方研究运行时、证据与时间语义、双轮委员会、风险否决、确定性仓位、学习治理、调度锁与 Outbox、安全、纯领域内核及显式多市场日历语义。
- 纯领域值对象、投资政策、Instrument/Thesis/Decision/Strategy 状态机，以及 Core/Tactical、风险否决、人类审批和学习权限不变量已实现并以失败关闭方式保护。
- 数据库迁移、乐观版本控制、审计/事件历史、不可变工件守卫、工作单元、事务 Outbox、咨询锁和幂等 TaskRun 已验证。
- PR-01 至 PR-07 已合并到 `main`；各自的合并提交记录仍保留在 Git 历史。
- PR-08 已由 PR #8 合并到 `main`，合并提交为 `9e3dad77142336918b24849b99cdadd1068effb8`。它交付了只支持显式合成日历的运行时调度、持久化 TaskRun、事务 Outbox 与仅模拟的报告；默认 Compose 环境不启用日历。
- PRODUCT-01 已完成首次启动引导状态、服务端能力矩阵、设置向导 UI、独立 PR-08 合成演示路由以及单元/集成/浏览器 E2E 验证。引导 HTTP 接口通过应用层用例访问持久化端口；模型与数据提供方在 PRODUCT-02 前如实标为 `NOT_IMPLEMENTED`。该状态不保存凭据、真实组合或投资政策数值。

## 尚未实现或尚未验证

- 真实数据提供方运行时、组合导入与观察清单写操作。
- 产品工作流中的分析编排、批准/拒绝 UI、手工执行记录、结果复盘、学习工作流与发布加固。
- 除已实现的 PR-07 S10 和 PR-08 调度重放/幂等性切片以外的完整验收场景覆盖。

不得仅因为主规范存在就推断以上项目已经完成。

## 当前授权工作

PRODUCT-01 已由 PR #12 合并到 `main`。PRODUCT-02 已由 PR #13 合并到 `main`，并且 ADR-0013
已由所有者于 2026-09-22 接受。PRODUCT-03 已由 PR #14 合并到 `main`（合并提交
`6753da5`）：它交付 OpenAI-compatible 模型网关、显式连接测试、角色分配、超时/Token 上限、
预算失败关闭和完整 AgentOpinion 验收，不选择或自动启用任何真实提供方，也不执行任何交易。
DeepSeek V4.1 Flash 已获所有者授权进行一次最小真实网络验收。所有者录入的定价、测试预算和凭据均只存在于
本地运行时配置；2026-09-22 已在无真实 Evidence、Portfolio 或交易数据的连接测试中验证认证、HTTPS 调用、预算
预留、可验证用量结算和 JSON 对象输出。同日又以合成 Evidence 完成真实模型的完整
`OpenAICompatibleLLMGateway → AgentRuntime → 严格 AgentOpinion → Evidence 引用校验` 路径：无修复成功，
用量为 425 输入 / 452 输出 Token，脱敏成本为 USD 0.0006699。该验证不构成分析编排、真实投资数据或任何交易行为的授权。
PRODUCT-04 现进入 `PLANNING`：可继续准备既有 `ResearchProviderPort`/`DSAAdapter` 的运行时接线，
但不会选择、连接或摄取任何真实数据源，直至所有者明确授权供应商、许可、端点与数据边界。

## 已记录的范围决定

- 发布的政策为 `TEST_DEFAULT`；选择真实限额仍需人工明确决定。
- A 股范围仅授权 SSE/SZSE 日历语义和合成研究/模拟夹具，不授权数据提供方、真实 A 股组合数据、政策限额、券商执行或实盘交易。
- 业主已授权阶段分支的提交和推送；合并到 `main` 仍是独立的人类动作。

## 路线图

| 阶段 | 状态 | 人工验收 | 说明 |
|---|---|---|---|
| PR-00 | ACCEPTED | 已合并到 `main` | 基础工程工作已交付并接受 |
| PR-01 | ACCEPTED | 已合并到 `main` | 2026-09-17 |
| PR-02 | ACCEPTED | 已合并到 `main` | 2026-09-18 |
| PR-03 | ACCEPTED | 已合并到 `main` | 2026-09-18 |
| PR-04 | ACCEPTED | 已合并到 `main` | 2026-09-19 |
| PR-05 | ACCEPTED | 已合并到 `main` | 2026-09-20 |
| PR-06 | ACCEPTED | 已合并到 `main` | 2026-09-20 |
| PR-07 | ACCEPTED | 已合并到 `main` | 2026-09-20 |
| PR-08 | ACCEPTED | 已合并到 `main` | 调度、报告和只读 UI |
| PRODUCT-01 | ACCEPTED | 已由 PR #12 合并到 `main` | 首次引导与产品状态 |
| PRODUCT-02 | ACCEPTED | PR #13 已合并；ADR-0013 已接受 | 设置、密钥存储与提供方档案 |
| PRODUCT-03 | ACCEPTED | 已由 PR #14 合并；MockTransport、隔离浏览器及已授权 DeepSeek 的合成 Evidence 真实网络验收均通过 | 真实模型运行时 |
| PRODUCT-04 | PLANNING | 待所有者授权数据供应商、许可、端点与数据边界；不发起真实网络请求 | 已授权数据供应商运行时 |
| PR-09 | PLANNED | 待定 | 结果、学习、加固与发布 |

## 状态更新规则

- 未记录验证证据时，禁止将阶段标为 `READY_FOR_REVIEW`。
- 需要人工治理审查的阶段不得由 Codex 单方面标为 `ACCEPTED`。
- 阻塞项必须记录负责人、精确条件、已尝试替代方案和解除事件。
- 详细清单与证据放在对应阶段文档；本文件保持简明。
