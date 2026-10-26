# MVP-BETA Release

- Release ID: `MVP-BETA`
- Integration branch: `release/mvp-beta`
- Owner: Product / Governance Owner
- Execution: multi-Agent autonomous Release Train
- Runtime mode: `DEVELOPMENT / SHADOW`
- Live trading: `FORBIDDEN`
- `auto_trade=false`

## Release Goal

交付一个所有者可以从浏览器实际使用和验收的 Personal AI Investment OS Beta：

```text
配置模型/数据源
→ 导入 Portfolio
→ 管理 Watchlist
→ 运行 Analysis
→ 查看 Evidence / Thesis / Agents / Risk / Sizing
→ 查看 Decision
→ Approve / Reject
→ 可选记录 MANUAL Execution
→ 查看 Daily Runtime / Opportunities
```

整个主路径不得要求所有者使用 SQL、curl、Python、原始 JSON 或内部数据库工具。

## Checkpoints

### A — Portfolio / Watchlist

可见验收：Portfolio 创建与导入、持仓、Watchlist、Policy 审阅。

### B — Analysis / Decision

可见验收：Run Analysis、AnalysisRun 进度、Evidence→Decision 下钻、Risk/Sizing、Decision Center、Approve/Reject。

### C — Runtime / Opportunities

可见验收：日常/每周任务、运行状态、Daily Report、机会漏斗、失败/降级状态。

### D — Beta

从 fresh install 到完整产品主链 E2E，满足 `docs/product/BETA_ACCEPTANCE.md` 的适用项。

## Release Rules

- 阶段 ACCEPTED 顺序仍保持 P5→P9；
- 无真实依赖 Work Item 可跨里程碑并行；
- 所有业务任务要求 User Visible Done；
- Release branch 可以持续集成半成品，但不得虚假展示为可用功能；
- main 只通过 Checkpoint PR 更新；
- PR-09 仍保持 BLOCKED，直到 P9 ACCEPTED 且所有者明确恢复。
