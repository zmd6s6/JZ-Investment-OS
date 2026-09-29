# PRODUCT-07 — 交互式决策与批准

- 状态：`PLANNED`
- 前置条件：`PRODUCT-06` 已由所有者接受；端到端影子 Decision 链路已可追溯
- 治理规范：`INVESTMENT_OS_MASTER_SPEC.md` §8、§10 至 §13、§16 至 §19
- 相关 ADR：`ADR-0003`、`ADR-0006`、`ADR-0007`、`ADR-0010`
- 安全基线：`auto_trade=false`；人类批准不等于经纪商订单提交

## 目标

提供真实 API 支撑的 Decision 列表与详情，使所有者可审阅 Evidence、Thesis、Agent opinions、反方意见、Risk
Veto、确定性仓位规模计算、Core/Tactical 快照和审计时间线，并可在受约束的状态机内 Approve、Reject 或 Revoke。
系统可记录所有者在外部完成的手工执行事实，但不连接、调用或模拟提交任何经纪商订单。

## 范围

1. Decision 列表、筛选、详情与不可变 Journal 下钻；所有卡片均来自真实应用 API。
2. 状态合法性、版本/并发冲突、原因、审批人、时间、Evidence 引用和审计事件的可见、可验证的 Approve/Reject/Revoke。
3. 仅限外部手工动作的执行记录，字段必须覆盖 `BETA_ACCEPTANCE` §10 与主规范 trade_record 语义：
   - `quantity`、`price`、适用时 `fees`、`execution timestamp`；
   - 经清洗的 `external reference` / `note`；
   - 有效 `approval linkage`（需要时）、fill-state 一致性、不可变审计。
   它只记录事实，绝不触发外部系统。
4. 若持久化模型缺少 `fees` 等字段，在本阶段作为迁移/API/UI 工作补齐，不得推迟到 P9 才发现。
5. 显著显示 `SIMULATION / NO AUTO TRADE`、as-of、陈旧/缺失 Evidence、Risk Veto、未知项与失败状态。

## 不变量与范围外事项

- 任何批准必须是明确、有效、未过期的人类动作；Risk Veto 对 BUY/ADD/增暴露仍不可覆盖。
- Portfolio Manager 仍只输出 `risk_intent`；最终数量、上限、舍入均必须来自确定性代码。
- Decision、Approval、Execution、Audit 和相关历史只追加或版本化；禁止由 UI 覆盖或删除既有事实。
- 本阶段不实现经纪商 adapter、订单 API、自动执行、自动批准、策略激活或投资 Policy 选择。
- 手工执行记录不得被解释为真实券商集成或真实投资建议；测试仅使用合成/去标识化数据。

## 人工边界

所有者独自决定是否批准或拒绝每个 Decision，以及是否在系统外采取任何动作。实现不得为所有者选择 Policy 限额、
解除 Veto、批准真实交易或写入虚假的手工执行。若需要连接任何券商或交易通道，必须另行取得明确治理决定和 ADR。

## 验收标准

1. 所有者可仅通过 UI 找到并完整审阅 P6 产生的 Decision 与其 Evidence 至仓位规模计算的追溯链。
2. Approve、Reject、Revoke 仅在合法状态、有效版本和有效人类授权下成功；非法、过期、Veto 和并发路径失败关闭。
3. 外部手工执行可录入并回读完整字段（quantity、price、适用时 fees、execution timestamp、sanitized external
   reference/note、approval linkage）；fill-state 一致，历史不可变，且系统没有任何订单提交、经纪商网络调用或自动执行路径。
4. UI/API 对权限、失败、未知、陈旧、Veto 与模拟状态均清晰显示，不伪造成功、仓位或执行。
5. 具名单元、状态机/属性、API 契约、集成、迁移、审计与浏览器 E2E 测试覆盖正常、失败和边界行为。
6. 完整认证/授权、CSRF 与外网加固不是本功能阶段的阻塞项（归后续 hardening/PR-09）；投资批准语义本身仍不可绕过。

## 完成前验证

运行受影响的格式、lint、类型、单元/属性/契约/集成/迁移、OpenAPI、前端构建、浏览器 E2E、密钥扫描和 Compose
检查；所有证据、限制和回滚/前向修复说明记录到阶段文档和项目状态后，方可 `READY_FOR_REVIEW`。
