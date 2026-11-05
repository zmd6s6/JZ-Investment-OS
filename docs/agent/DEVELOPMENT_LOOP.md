# MVP-BETA — 持续交付执行手册（开发 Agent / Planner / Gatekeeper）

> 生效范围：`release/mvp-beta`。这是操作手册，不修改主规范、已接受 ADR、阶段契约或人工投资治理。实际状态以目标分支和 GitHub CI/PR 为准。

## 1. 目的与职责

- **Owner**：只有重大投资政策、外部数据/模型成本授权、策略激活、真实交易权限、不可逆迁移，以及 Checkpoint 浏览器验收需要人类决定。
- **Planner（单写入者）**：从 P5–P9 契约与 `BETA_ACCEPTANCE.md` 找真实未交付缺口，维护一个可交付的优先级队列。不能宣告代码完成、不能改主规范或投资阈值。
- **Developer（最多两条互不冲突的工作流）**：Claim 一个已在 Release 生效的 READY Work Item，编写生产代码、正常/失败/边界测试与真实产品操作证据；对已有 PR 的审查反馈负责。不得自行批准自己 PR。
- **Gatekeeper**：独立审查最新 HEAD、必要 CI、review threads、架构/治理/证据/产品路径和文档真实性；未全部满足则留一次清晰阻塞意见，满足则按仓库允许方式合并。不能因为 Planner/Developer 自称通过而跳过门禁。

## 2. 每轮 Developer 具体操作

1. 读取 `INVESTMENT_OS_MASTER_SPEC.md`、`AGENTS.md`、`docs/PROJECT_STATUS.md`、Release/Queue、本手册、相关 Stage/ADR；查询最新 Release HEAD 与开放 PR。
2. 优先回到自己已有的 Claim / PR 处理可执行的 P0/P1 审查反馈；无反馈且存在未领取 READY 时，按优先级与真实依赖领取，Claim 分支使用 `agent/<WORK_ITEM_ID>`。严禁拿 PR 内尚未合入的条件状态作为 Release READY。
3. 明确最小完整纵切：入口→操作→数据→结果→失败表现；先识别 `Risk Veto`、确定性规则、`TEST_DEFAULT`、历史、成本授权、`auto_trade=false` 的失败关闭边界。
4. 实现功能和具名回归，先聚焦检查，再完整 required CI；需要时对真实 API/PG/Worker/UI 做隔离合成 E2E。任何无法执行的验证列为 `NOT VERIFIED`。
5. 在**同一个功能 PR** 内更新 Work Queue、ACCEPTANCE 与项目状态的受影响事实；`INTEGRATED` 写成“本 PR 真正合并后生效”，而不是提前宣布；`ACCEPTED` 永远需要 Owner 实际验收。
6. 打开或更新目标为 `release/mvp-beta` 的 PR：提供 SHA、变更清单、可重现命令、证据、失败路径、限制及 handoff。不把合成数据等同于个人投资验证。
7. 发现 P1/P2 问题时在原 Work Item 修复，最小化非相关文档修补；不替代独立 Gate。PR 真正合并以后，重读 Release 决定下一任务。

## 3. 没有 READY 时怎样不中断开发

- 先检查：是否存在开放的原任务 PR、未结束 Claim、已合并但状态未反映的工作项；继续原任务，不新建同名平行 PR。
- 若确实无 READY，Planner 对照 P6/P7/P8/P9 与 Beta 功能验收清单列出未交付的**产品闭环**，优先可独立开发、无需真实数据或策略授权的纵切。
- 只允许**一个**在审的 Queue replenish PR，保持原状态不变，仅添加合法 `READY/BLOCKED` 工作项、精确依赖、阶段归属、UI 验收、失败条件；禁止写入虚假的 INTEGRATED/DONE/ACCEPTED。
- 在该 PR 真正合并前，Developer 只能继续已有合法工作或完成不触及受阻部分的验证；不能从提案中抢先 Claim。
- 队列耗尽只是工程调度问题，不应升级为 Owner 决策；涉及真实 Policy、数据授权、隐私、预算和交易能力则单独按治理协议升级。

## 4. Review Gate 与文档防空转

- 同一问题、同一 HEAD 不重复提交评论；审查重点是**新增行为和准确证据**，不是要求反复改写同义词。
- 绝不虚报“合并前独立审查”“已在用户部署通过”或通过数量。合并后的独立复核必须写明真实先后顺序。
- 重大错误（治理/安全/与实际功能矛盾的能力状态）必须修复后方可合并。一般历史文案整理可以随下一功能 PR 一起处理；现有阻塞的纯文档 PR 仍按正常门禁处理，不得绕过。
- 所有功能 PR 保留正常、失败、边界和用户可见证据；Risk Veto、Approval、Deterministic Sizing、append-only history、`auto_trade=false` 永不降级。

## 5. 看板和停机条件

每轮内部记录：

```text
work_item: MVP-XXX
head: <actual SHA>
code_changed: <named product source paths and tests, or NONE>
checks: <actual commands/status, not assumptions>
pr_state: <URL / blocked reason / merged SHA>
user_visible: <route + exact success/failure steps, or NOT VERIFIED>
owner_decision: NONE | <specific governance question>
```

- 以“实际可用的功能路径/已验证行为”和“阻塞时间”为主要交付指标，不以文档 PR 数、代码行数、CI 绿灯数作唯一 KPI。
- 仅在 PR 合并、审查状态实质变化、Checkpoint 可供 Owner 浏览器验收或确有治理决定时通知 Owner。
- 遇到需要真实投资规则、未授权外部来源、付费调用、生产数据或实盘操作时，保持开发/测试为合成或只读影子边界，不能自行放宽门禁。
