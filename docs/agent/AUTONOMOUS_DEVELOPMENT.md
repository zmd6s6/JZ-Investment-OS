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

## 3. 自治循环

```text
READ → CLAIM → INSPECT → PLAN → IMPLEMENT
     → FAST TESTS → FULL REQUIRED TESTS
     → SELF REVIEW → PR → CI/REVIEW FIX LOOP
     → GATE PASS → MERGE → NEXT READY TASK
```

只要还有独立 READY 工作，Agent 不得因为另一项任务等待 owner 决定而整体停止。

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

## 8. Handoff

无法继续时，使用 `HANDOFF_TEMPLATE.md` 写入 PR 描述、PR 评论或工作分支中的 `docs/agent/handoffs/<ID>.md`。聊天记录不是 handoff。

## 9. 状态更新

合并 Work Item 时同步更新 `WORK_QUEUE.yaml` 和必要的 `ACCEPTANCE.md`。禁止因为代码存在而把 Checkpoint 标为 ACCEPTED。

## 10. 主分支

`main` 保持可运行稳定。常规 Work Item 合入 `release/mvp-beta`；Checkpoint 通过用户可见验收后，通过 Release PR 合回 `main`。
