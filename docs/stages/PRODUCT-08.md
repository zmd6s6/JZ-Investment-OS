# PRODUCT-08 — 每日 AI 团队运行时

- 状态：`PLANNED`
- 前置条件：`PRODUCT-07` 已由所有者接受；Portfolio、Watchlist、分析、Decision 与人类关卡均已可追溯
- 治理规范：`INVESTMENT_OS_MASTER_SPEC.md` §5、§9、§12、§14、§16 至 §19
- 相关 ADR：`ADR-0003`、`ADR-0005`、`ADR-0008`、`ADR-0010`、`ADR-0012`、`ADR-0015`、`ADR-0016`
- 安全基线：`auto_trade=false`；调度只产生研究、分析和报告工件，不产生订单

## 目标

在已有显式市场日历、TaskRun、咨询锁、幂等键和 Outbox 基础上，交付用户可见、可诊断的日常 AI 团队运行：数据同步、
Portfolio/Watchlist Evidence diff、自动分析触发、每日报告、每周机会筛选和每月 Portfolio 复核。每次运行都必须保留
输入、as-of、实际 provider/model、状态、失败/降级原因和可重放关联。

## 范围

1. 明确、持久化、可暂停的日/周/月任务定义和 UI 运行历史；同一业务键不能重入。
2. 已授权 Portfolio/Watchlist 的数据新鲜度检查、Evidence diff 与通过 P6 既有编排器产生的分析触发。
3. **每周机会筛选硬契约**（确定性漏斗，禁止全市场强模型扇出）：
   ```text
   market universe
   → deterministic filter / features
   → bounded candidate set
   → deep research / LLM 仅用于候选
   → Opportunities UI
   ```
   必须记录每个候选的入选原因与缺失数据；必须有测试证明不会对全市场直接 fan-out 强模型（对齐
   `BETA_ACCEPTANCE` §13 与主规范 §17.3 成本/性能边界）。
4. 面向所有者的报告和机会候选；它们必须标明来源、as-of、未知、缺失、降级、模拟状态和是否需要人工操作。
5. **每日主界面/报告必显信息归属**：action required、hold/watch、新机会、Risk Veto、待处理 approvals、
   data/job degraded；缺失时显式“未提供”，不得静默省略。
6. 失败、部分成功、锁冲突、超时、预算耗尽、市场关闭、无授权 profile 或无数据的显式状态和恢复说明。
7. dry-run 与 as-of 重放只能使用隔离输入，不能影响真实个人历史或执行状态。

## 不变量与范围外事项

- 任务写入与 Event/Outbox 在同一事务；锁、幂等、重试和失败记录遵守已接受调度 ADR。
- 仅使用所有者已授权且已启用的 provider/profile；不得因故障或空数据静默切换来源、扩大市场范围或增加查询成本。
- 自动分析只能生成 P6/P7 约束下的影子 Decision；Risk Veto、批准与 `auto_trade=false` 始终有效。
- 本阶段不自动批准、不记录执行、不激活 Strategy/Policy/Prompt 变更，也不接入任何实盘经纪商。

## 人工边界

在启用任何真实定时研究前，所有者必须明确确认市场/标的范围、调度频率、可调用 provider、预算/成本边界、保留期和
暂停方式。未确认时，工程验证只能使用合成日历、夹具或 dry-run；不得把默认定时器当作真实研究授权。

## 验收标准

1. 已授权市场会话到期后，Worker 无需手工 CLI 即能产生可追溯的预期分析/报告或明确失败记录。
2. 日/周/月任务的锁、幂等、重试、重放、失败和部分成功均可通过 UI/API 与持久化历史审计。
3. 每次自动运行明确记录实际数据/模型来源、as-of、Evidence 新鲜度、预算和降级情况；没有静默回退。
4. 每周机会筛选严格执行 `universe → deterministic funnel → bounded candidates → 候选才 deep research`；
   有自动化证据表明未对全市场强模型 fan-out，且候选原因/缺失数据可见。
5. 每日主界面/报告展示 action required、hold/watch、新机会、Risk Veto、待处理 approvals、data/job degraded。
6. 机会筛选和报告不是投资建议或交易命令，所有批准与执行仍由 P7 的人类关卡控制。
7. 调度、重入、故障恢复、授权边界、报告内容和浏览器流程具有具名单元、集成、迁移、E2E 与合成运行证据。

## 完成前验证

运行受影响的格式、lint、类型、单元/属性/契约/集成/迁移、API/OpenAPI、Worker/Compose、前端构建与浏览器 E2E。
真实定时运行只在所有者已确认的边界内做最小验证；证据必须脱敏并记录仍未验证项。
