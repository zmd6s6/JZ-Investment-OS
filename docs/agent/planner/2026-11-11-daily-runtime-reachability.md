# MVP-BETA 每日运行可达性补货

## 当前事实与执行权

基线为实际Release `0f2a3d17df28ae2508c504881a21269bab72f076`。PR47已经实际合入，合入后独立复验由root另行记录，不能补写成合入前Gate。本轮读取权威队列15项，没有READY。开放PR只有旧PR18到main，没有开放Planner PR。MVP402本地链已经集成，整个项仍REVIEW/PARTIAL；MVP501仍受PRODUCT09的Owner接受前提阻断。405的旧候选队列状态不是要求重建相同功能，实际合入与Handoff已核对。

已核远端agent/MVP000至405 Claim、工作树清单及402/405 Handoff，原Claim和文件保留。402和405的执行权已交回root，无开放功能PR；root协调当前状态收口。本Planner只操作独立分支 `planner/mvp-beta-replenish-after405-20261111`，不更改既有15项状态、Claim或治理文档，不建立agent/MVP-406。

## 契约与实际缺口

PRODUCT08范围2、7及验收2要求可暂停的日任务、可审计运行和失败历史。主规范§14/17.2要求持久可靠调度与幂等恢复，ADR0048要求独立暂停/永久撤销、只追加日报和正文到期后保留审计。Daily当前有三个实际边界问题。

- `infrastructure/daily_runtime_runner.py` 的 `dispatch_due` 按配置UUID固定读取最多50个enabled记录，没有游标。存在51个长期启用配置时，后续配置永久不被计划，即使前50个早已执行完当天任务。
- 同文件 `refresh_reports` 只取最新50个execution。仍等待分析终态的较早执行可被后续新执行挤出，长期保留PENDING，不能继续收口。
- `infrastructure/daily_runtime_store.py` 的 `configurations` 固定最新50、`runs`/`reports`最多100。`api/daily_routes.py` 没有分页参数或单记录详情，`web/src/DailyRuntimePanel.tsx` 没有加载更多。较早配置的暂停/撤销控件以及较早运行/报告因此不可达。过期报告直接跳过，缺少可见审计摘要。

Monthly已通过ADR0052解决其配置公平扫描和历史分页，Daily仍是独立实现。此次只修Daily生产链，复用已验证模式和原授权语义。当前405是首页有界运营总览，不承担完整Daily历史；不重复它，也不把扩大首页扫描视为完整历史。

## 最小纵切与安全边界

提出唯一MVP406。保留原轮询资源上界，以持久可恢复进度覆盖全部可检查Daily配置及待收口执行；多Worker、重启和故障下仍使用既有锁、TaskRun幂等键、授权最终核验和只追加报告。明确有限集合与持续轮询条件下的最终公平性，不承诺无限新增记录下的无条件时限。

类型化分页/单ID读取接入实际API和/calendar，保留旧列表调用的兼容默认值。配置、运行及审计摘要采用稳定排序，UI显示页范围、加载更多及并发插入后的刷新提示。原记录定位不依赖它恰好在首页。较早授权的暂停/撤销继续要求当前version及显式确认；读取失败不能让旧控件继续声称当前权限有效。

报告正文到期仍拒绝展示/复用，审计只暴露已允许的ID、时点、状态、hash和关联，不泄漏过期正文或密钥。读取不排队、不重试、不授予研究权限。游标仅运行进度，新增ADR及迁移须记录重建/回滚或前向修复，不能改旧accepted ADR。无真实数据、付费调用、Policy选择、Strategy激活、订单或Owner部署。

## 验证与验收

开发时先写修前可失败的真实PG回归，构造超过50个配置和待收口执行，验证尾项、回绕、并发、重启、幂等与暂停交错。超过100条历史验证稳定分页及单ID可达，过期/坏hash/不存在/非法参数失败关闭，旧API默认行为兼容，读SQL零业务写入。

独立合成生产API/PG/真实Worker/浏览器从/calendar加载尾项，观察真实报告，定位历史，明确暂停或永久撤销并刷新确认。演示网络失败恢复、正文到期审计可读与390宽。完整必要基线、迁移、OpenAPI、前端及相应E2E必须实际执行，最终新HEAD独立Gate后才能合入。

## 本轮机器记录

```text
work_item: PLANNER / proposed MVP-406
base: 0f2a3d17df28ae2508c504881a21269bab72f076
code_changed: NONE
business_code_sha: NONE
checks: actual Release/PR/remote Claim/worktree/Handoff inventory and source inspection; Python/PyYAML PASS 16 unique legal DAG items, original 15 identical, dependency integrated, 402 REVIEW/501 BLOCKED, no remote 406 Claim; git diff --check PASS
pr_state: Planner PR pending creation; no functional PR
user_visible: NOT VERIFIED — proposed /calendar daily history and controls
owner_decision: NONE
blocking_condition: unique Planner PR must actually merge before create-only Claim and implementation; subsequent exact-HEAD CI and independent Review Gate
```

本轮没有业务代码交付，没有运行功能测试。实际数据源/Owner部署/阶段接受仍受原边界约束，MVP501不解锁。Planner合入后才能领取406开发，不能以本规划或静态代码定位宣称产品缺口已修复。

规划校验首次使用系统Python缺少PyYAML，改用仓库既有venv后遇到Windows默认GBK读取Git中文失败；显式UTF-8后上述断言全部通过。这两次环境失败不计通过，不新增依赖。
