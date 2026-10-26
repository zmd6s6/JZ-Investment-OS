# 项目工作模式

## 目的

本文件定义 Personal AI Investment OS 的持续交付方式。主规范、已接受 ADR 和阶段契约仍具有更高权威；本文件只定义如何更快地把它们变成可见产品。

## 角色

### 人类所有者

所有者是 Product Owner / Governance Owner，主要负责：

- 定义当前 Release 的产品目标与优先级；
- 决定真实 Investment Policy、风险偏好、数据授权/许可、成本预算、实盘能力等治理事项；
- 在 Release Checkpoint 上直接通过浏览器做产品验收；
- 接受或拒绝阶段里程碑。

所有者不负责日常任务分解、普通工程选择、逐 PR 催办或重复复审。

### Worker Agent

任何 Codex、Claude Code、Gemini CLI 或其他开发 Agent 都视为 Worker Agent。进入仓库后必须自行读取控制文件、领取 READY 工作项、实现、验证、提交 PR，并根据 CI/Review 反馈继续修复。只要队列中仍存在无阻塞 READY 工作，不应因为一个无关任务等待人类决定而整体停止。

### Gatekeeper Agent

Gatekeeper 独立于实现任务，负责检查：

- CI 与必要测试；
- 主规范、ADR、阶段契约和架构边界；
- Risk Veto、Approval、deterministic sizing、immutable history、`auto_trade=false`；
- 文档真实性和 `NOT VERIFIED`；
- unresolved review threads；
- 是否存在人工治理决定；
- 用户可见验收契约。

全部满足时，Gatekeeper 可将 Work Item PR 合并到当前 Release integration branch；否则留下精确 blocker，Worker Agent 继续修复。

## Release Train 工作循环

```text
Master Spec / ADR / Stage Contracts
            ↓
      Active RELEASE
            ↓
      WORK_QUEUE.yaml
      ↙      ↓       ↘
  Worker A Worker B Worker C
      ↓      ↓       ↓
     PR     PR      PR
       \     |      /
        Review Gate
             ↓
     release/mvp-beta
             ↓
    User-visible Checkpoint
             ↓
       owner acceptance
             ↓
            main
```

同一时间只有一个活动 Release，但一个 Release 内可以有多个并行 Work Item。产品阶段仍按 P5→P9 作为验收里程碑；这不禁止在没有真实依赖时提前实现后续阶段的独立纵切。

## Work Item 状态

`docs/agent/WORK_QUEUE.yaml` 使用：

- `READY`：依赖满足，可领取；
- `CLAIMED`：Agent 已创建 `agent/<id>` 分支；
- `IN_PROGRESS`：实现中；
- `REVIEW`：PR 已提交，等待 CI/Gatekeeper；
- `INTEGRATED`：已合并到 Release branch，但尚未通过所属 Checkpoint 的人类可见验收；
- `BLOCKED`：仅限真实依赖、外部能力或人工治理决定；
- `DONE`：已被所属 Checkpoint 验收，或该项明确为无需人工 UI 验收的内部能力且其上层可见链路已通过。

队列是调度真相源；阶段文件是验收契约，二者不得互相伪造完成状态。

## Claim 与并发

1. Agent 读取 `RELEASE.md` 和 `WORK_QUEUE.yaml`；
2. 选择最高优先级、依赖均已满足的 `READY` 项；
3. 从当前 Release integration branch 创建远程分支 `agent/<work-item-id>`；
4. 分支创建成功即 Claim 成功；同名创建失败代表被其他 Agent 抢占，必须重新选任务；
5. 不得在其他 Agent 分支上继续开发，除非按 Handoff 协议接管。

这样不需要中央人工调度，也避免多个 Agent 同时修改同一任务。

## 开发与验证

每个 Work Item 都必须形成最小完整纵切，并在 PR 内提供：

- 关联 Work Item ID；
- 实现范围与不变量；
- 实际运行的测试和 CI；
- 未验证项；
- 用户可见验收入口；
- `入口页面 → 操作 → 预期结果 → 失败路径`；
- Owner Decision 是否为 `NONE`。

没有真实 UI/API/DB 接线的业务功能不能宣称 Product Done。

## 人工治理升级

只有以下情况允许暂停受影响任务并请求所有者：

- 修改主规范或已接受投资治理；
- 选择/更改真实 Investment Policy 限额；
- 削弱 Evidence、Risk Veto、Approval、immutable history、deterministic sizing；
- 使用授权/许可/隐私未解决的数据源；
- 引入实际支出但预算未获批准；
- 启用券商或实盘执行；
- StrategyProposal 激活；
- 无可靠恢复路径的不可逆真实数据迁移。

普通 API 命名、数据库表设计、React 组件拆分、测试组织、内部重构等工程问题由 Agent 自主决定。

## Review Gate

Gatekeeper 只有在以下条件全部满足时才合并到 Release branch：

1. PR mergeable；
2. required CI 全绿；
3. 无 unresolved review thread；
4. 无待定 Owner Decision；
5. 主规范/ADR/阶段契约未被削弱；
6. Risk/Approval/Deterministic Domain 不变量保持；
7. 文档与实际验证一致；
8. 正常/失败/边界测试与必要 E2E 有证据；
9. 用户可见验收路径已填写；
10. 没有把尚未实现能力宣称为 DONE。

实现 Agent 不需要等待所有者逐 PR 复核。失败时 Gatekeeper 留评论，Worker 继续修复。

## Release Checkpoint

所有者只需要验收少量 Checkpoint，而不是每个 PR：

- Checkpoint A：Portfolio / Watchlist；
- Checkpoint B：Analysis / Decision；
- Checkpoint C：Daily Runtime / Opportunities；
- Checkpoint D：完整 Beta。

Checkpoint 必须在 `docs/agent/ACCEPTANCE.md` 和产品 Acceptance Center 中列出可点击入口、测试数据要求和预期结果。通过后再更新相应阶段为 `ACCEPTED`。

## Handoff

Agent 无法继续时，不得只在聊天中留下上下文。按 `docs/agent/HANDOFF_TEMPLATE.md` 在工作分支或 PR 中记录：

- 当前 head；
- 已完成；
- 剩余工作；
- 实际测试结果；
- blocker；
- 下一条最短执行路径。

新 Agent 读取后可从同一分支继续。

## 发布模式

运行时发布模式仍保持：`DEVELOPMENT → BACKTEST → SHADOW → PAPER → MANUAL_LIVE_RECORDING`。V1 禁止自动进入 `BROKER_LIVE`，任何开发流程加速均不得改变这一点。

## 通知原则

日常 Worker/Review 循环不要求所有者参与。只在以下情况通知所有者：

- Work Item/Checkpoint 被合并或状态发生实质变化；
- 出现真正的人工治理决定；
- 产品 Checkpoint 已可进行浏览器验收；
- Release 目标或风险边界需要变更。
