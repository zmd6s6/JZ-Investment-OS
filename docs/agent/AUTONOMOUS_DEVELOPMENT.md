# Autonomous Development Protocol

> 适用于当前 `MVP-BETA` Release Train。它不修改主规范、ADR 或投资治理，只定义开发 Agent 如何自治协作。

## 1. Agent 启动顺序

任何 Agent 进入仓库后必须依次读取：

1. `INVESTMENT_OS_MASTER_SPEC.md`
2. `docs/PROJECT_STATUS.md`
3. `docs/agent/RELEASE.md`
4. `docs/agent/WORK_QUEUE.yaml`
5. 当前 Work Item 对应的 `docs/stages/` 契约
6. 相关 accepted ADR
7. `AGENTS.md`

不得依赖聊天历史作为唯一上下文。

## 2. 领取任务

选择最高优先级、所有 `depends_on` 已满足的 `READY` Work Item。

Claim 使用远程分支作为原子锁：

```text
base = release/mvp-beta
branch = agent/<WORK_ITEM_ID>
```

创建成功即 Claim 成功。若同名分支已经存在或 push 被拒绝，重新读取队列并选择其他任务；禁止 force-push 抢占。

- 以 Release 分支上实际已合并的状态为准；工作分支中的条件式 `INTEGRATED` 不作为依赖已满足的证明。
- 每次运行先查同一 Work Item 的开放 PR、远程 Claim 分支和现有 Handoff；存在时续接原任务，不另起重复 PR。
- 若没有可领取的 `READY`：不能把 `REVIEW`、`BLOCKED` 偷改成 `DONE`。先查当前正在审查/正在开发的任务；对现有范围可继续修复并完成 PR。确有未分解的阶段契约缺口时，由单个 Planner 提交**一个**仅含合法新工作项、依赖、验收与安全边界的队列补货 PR；该 PR 合入之前不从拟议队列 Claim。
- 队列状态不应因人类 Checkpoint 未签收而阻挡没有真实依赖的工程开发；Checkpoint 本身仍不得伪造为 `ACCEPTED`。

## 3. 自治循环

```text
READ → CLAIM → INSPECT → PLAN → IMPLEMENT
     → FAST TESTS → FULL REQUIRED TESTS
     → SELF REVIEW → PR → CI/REVIEW FIX LOOP
     → GATE PASS → MERGE → NEXT READY TASK
```

只要还有独立 READY 工作，Agent 不得因为另一项任务等待 owner 决定而整体停止。

- **WIP 上限**：默认同时推进不超过 2 个互不冲突的功能 Work Item（优先 1 个 Checkpoint B 风险/决策主链、1 个 Checkpoint C Runtime）；同任务多个 Agent 可分别实现与测试，但共用一个有归属的 Claim/PR，不覆盖他人分支。
- **两条泳道**：Developer 只对业务代码/测试/可见验收负责；Gatekeeper 独立负责 review、CI、审查线程与合并。等待 Gate 时，Developer 可领取另一独立 READY 任务，或修复已领取任务的审查反馈；不可用“等审查”作总体停工理由。
- **功能优先**：每个工作迭代优先形成真实 UI/API/DB/Worker 的最小纵切和有失败路径的测试，不以文档行数、评论数、PR 数或合成成功截图衡量产品进度。

## 4. 允许自行决定

普通、可逆工程选择由 Agent 自主决定，包括内部 API 命名、表/DTO 组织、组件拆分、测试结构、局部重构、错误处理实现方式等，但不得违反主规范、ADR、阶段契约和既有公共兼容性要求。

## 5. 必须升级给 Owner

仅限：

- 主规范/投资治理改变；
- 真实 Policy 限额；
- Risk Veto / Approval / deterministic sizing / immutable history 弱化；
- 新数据源授权、许可、隐私或真实成本未决；
- Strategy 激活；
- 券商/实盘能力；
- 不可逆真实数据迁移且无已验证恢复方案。

遇到 Owner blocker 时，把该 Work Item 标为 `BLOCKED`，在 `DECISIONS.md` 记录问题，并继续其他 READY Work Item。

## 6. Product Done

业务功能必须同时满足：

- Engineering Done；
- Integrated Done；
- User Visible Done。

User Visible Done 必须给出：

```text
入口页面
→ 操作
→ 输入
→ 预期可见结果
→ 失败时用户看到什么
```

没有真实产品入口的 API/类不能独立宣称业务完成。底层能力可通过上层 E2E/运行状态间接证明。

- 每个功能 PR 写明精确 HEAD、与 Release 对比的实际功能 diff、执行过的正常/失败/边界测试、具体路由和操作步骤、显式未验证项及 Owner PENDING；不使用旧 HEAD 的 CI/浏览器证据冒充新 HEAD 结果。
- `TEST_DEFAULT`、人工报价、合成模型或合成日历只代表工程验证；未授权真实投资配置不得被包装为真实可审批 Decision。

## 7. Review Gate

Gatekeeper 对每个 PR 检查：

- mergeable；
- required CI green；
- unresolved threads = 0；
- Owner Decision = NONE；
- no governance regression；
- fail-closed Risk/Approval；
- deterministic domain rules；
- architecture boundaries；
- docs truthful；
- tests cover normal/failure/boundary；
- UI/E2E evidence appropriate；
- no secrets/personal production data；
- no live broker/order path。

全部通过后可 merge 到 `release/mvp-beta`。实现 Agent 不要求 owner 逐 PR 审批。

- 同一未变化 HEAD 的同一阻塞只留一条可执行审查意见，后续仅在修复或新证据带来实质变化时复审；不因审查评论数量重复触发开发回合。
- 真实性是硬要求。功能 PR 同步必要的 Queue、ACCEPTANCE、PROJECT_STATUS 和契约证据，状态以**实际合并后才生效**表述；不能借未合并 PR 或合成环境宣称 Owner 已接受。
- 文档单独 PR 仅限足以误导用户的重大状态错误、治理/安全错误或阻止后续工作领取的队列错误；普通历史时态修正并入下一功能 PR 的小变更。任何独立文档 PR 也必须满足 Review Gate，不得为了吞吐量降低真实性要求。

## 8. Handoff

无法继续时，使用 `HANDOFF_TEMPLATE.md` 写入 PR 描述、PR 评论或工作分支中的 `docs/agent/handoffs/<ID>.md`。聊天记录不是 handoff。

## 9. 状态更新

合并 Work Item 时同步更新 `WORK_QUEUE.yaml` 和必要的 `ACCEPTANCE.md`。禁止因为代码存在而把 Checkpoint 标为 ACCEPTED。

## 10. 主分支

`main` 保持可运行稳定。常规 Work Item 合入 `release/mvp-beta`；Checkpoint 通过用户可见验收后，通过 Release PR 合回 `main`。

## 11. 开发与审查的独立运行约定

开发执行入口见 [DEVELOPMENT_LOOP.md](DEVELOPMENT_LOOP.md)。按 `PREPARE → CLAIM → IMPLEMENT → TEST → PR → REVIEW FIX → MERGE → NEXT` 运行；审查 Agent 不能凭审查角色暗中自造或自签 PR。

工作项优先级：先解决完整 `Analysis → deterministic Risk/Sizing → valid Decision → human Approval` 主链，再补 Daily/Monthly Runtime；与主链无依赖的 Runtime 可并行。MVP-402 处于 `REVIEW/PARTIAL`，需在原拥有者的 Handoff/PR 上收口，不因多次局部合并自动标为 `DONE`。MVP-501 在其真实依赖与 Owner Checkpoint 均未满足时继续 `BLOCKED`。

每次迭代结束写明机器可核对的三项结果：`code_changed`（业务文件及测试）、`gate_state`（PR/CI/threads/Owner block）、`user_visible`（实际可操作路由和限制）。未运行的验证写 `NOT VERIFIED`；没有实质变化则保持安静。Owner 仅在 Checkpoint 浏览器验收或治理问题时参与。
