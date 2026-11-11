# MVP-BETA Planner补货 — 2026-11-11

## 实际定位

基线Release为`2e3fe9fa217d9aee4fce88519946612d68da919d`。当前队列14项中12项INTEGRATED、MVP402 REVIEW/PARTIAL、MVP501 BLOCKED，没有READY。开放PR只有旧P6到main的PR18，没有开放Planner PR。MVP402的本地切片已经合入并收口，原Claim保留；不重复实现、不抢占长期分支。此次Planner使用独立工作树和分支，未建立MVP405 Claim。

停滞发生在DEVELOPMENT_LOOP §3已经规定的队列补货入口未被执行。队列耗尽后，重复巡检没有产生下一功能。补货提交必须先经独立Gate真正合入，随后Developer才能原子创建`agent/MVP-405`。

## 真实产品缺口

`BETA_ACCEPTANCE.md` §12及PRODUCT08范围6要求每日主界面展示六类信息。`web/src/App.tsx`的HomePage当前只读取onboarding和product-capabilities，显示向导与能力卡。`application/daily_runtime.py`已经有DailyReport六节和持久化TaskRun来源，`application/acceptance.py`仍声明新机会/审批总览NOT_PROVIDED。没有真实运行收件箱把本地待审批和运行异常接到主界面。

MVP405限定为只读运行收件箱。它读取现有本地产物，为实际待审批、失败/降级运行提供来源与详情入口。需要投资解释而来源不支持的栏目明确未知，不能从持仓、候选或运行成功推断投资Action。无新数据源、模型费用、Policy参数、状态转换或交易授权。依赖206/403/404均已实际INTEGRATED，工程开发不依赖Owner Checkpoint签收。完整P8/Owner接受与501前提保持既有边界。

## 最小交付与验证

生产代码预期涉及typed application read port、SQL适配器、只读API和首页面板；复用现有详情路由，避免新增生产服务/依赖。只读聚合使用有界查询、稳定排序和来源观察时间。不存在字段时显示NOT_PROVIDED，读取失败显示栏目错误，空成功查询显示无记录。客户端刷新不得写TaskRun、Decision、Approval、Audit或Outbox。

开发时验证正常、空库、过期/撤销/完成批准、坏引用、单源故障、分页上界及刷新并发。真实合成PG/API与浏览器演示刷新后最新持久状态、跳转原详情、中文失败/恢复提示及390宽可读。需要Worker来源的用例通过真实Worker产物证明，未运行项记录NOT VERIFIED。最终保留独立Review Gate和精确HEAD CI。

## 本轮机器可核对记录

```text
work_item: PLANNER / proposed MVP-405
base: 2e3fe9fa217d9aee4fce88519946612d68da919d
code_changed: NONE
business_code_sha: NONE
checks: queue YAML and dependency validation, original-state preservation and diff scope (results in PR)
pr_state: Planner PR pending creation, no functional PR
user_visible: NOT VERIFIED — proposed route /
owner_decision: NONE
blocking_condition: Planner PR must actually merge before Claim and implementation
```

本轮只交付规划，未交付业务代码。Planner合入后立即按READY优先级执行MVP405，功能PR必须记录业务SHA、实际测试结果、入口与当前阻塞/解除条件。只有当前真实产品缺口才补货，不以文档数量或重复检查作为功能交付。
