# ADR-0044 — 有界候选的逐次显式研究

- 状态：Accepted（既有研究授权内工程选择，不改变投资治理）
- 日期：2026-10-28
- 补充 ADR0040/0041，不改旧漏斗快照或分析协议。

## 决策

机会页仅允许已保存漏斗中的有界候选逐个发起现有 AnalysisRun。应用服务读取不可变 FunnelRun，校验候选成员/上限、原候选 Evidence 必须随命令明确选择、行情来源保持一致。调用方显式选择组合、所有角色模型、可选研究源/查询，并分别同意模型与资料调用；没有批量或自动扇出入口。

复用现有 typed AnalysisStartService 及模型/预算/证据最终失败关闭，不重写分析、Policy、Risk、Sizing 或审批引擎。研究发生在新运行当前时点，不把后到研究作为历史筛选时已知资料；原漏斗/分析输入快照均不变。历史漏斗的 deep_research=NOT_PROVIDED 描述当时运行，当前可调用能力由 capabilities 单独显示。

## 持久化与恢复

在排队前先以 Analysis request_id 记录只追加 candidate research intent、Audit、Event/Outbox 同事务，固定原漏斗/候选与完整显式命令/hash。该 intent/outbox 不是工作队列，没有自动消费者，也不会自行调用模型。之后经原 AnalysisStart 入队，沿其唯一 request_id 实现重复提交不重复入队。

两步没有跨事务伪原子保证：若 intent 已写但入队失败，页面明确“未找到分析运行，需要显式重试”；如果响应丢失，读取按固定 request_id 找真实 AnalysisRun 并核命令 hash，显示真实结果。仅用户明确用原命令重试，不能自动重播未知费用。输入变化须新 request_id，旧 intent/失败与已发出运行永不覆盖。

## 替代方案、边界与回滚

拒绝仅静态跳转或 localStorage 关联、直接全列表模型扇出、伪造已完成研究、把 ShadowDecision 提升成可审批交易。无需新增表/迁移/依赖；新增可选 router 组合参数保持旧调用兼容。回滚新增组件与桥接服务，保留 Event/Audit/Analysis 历史。全市场 universe、周定时筛选和完整 P8 尚未提供；Owner/Checkpoint PENDING，auto_trade=false。

验证包括非候选/超上限/来源与Evidence不匹配零排队、同请求重放与异内容拒绝、intent失败回滚、排队失败/未知响应显式恢复、真实 API/DB/Worker/UI正常与失败路径。真实来源/模型与Owner实例不在本次授权内，只有独立合成验证。
