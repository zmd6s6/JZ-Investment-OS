# Personal AI Investment OS — Beta 验收门槛

> 目的：定义项目可被描述为所有者可正常使用前所需的最低证据。
>
> 约束权威仍为 `INVESTMENT_OS_MASTER_SPEC.md`。

---

## 1. Beta 定义

Beta 表示所有者无需接触源代码、SQL、原始 JSON、curl 或仅供内部开发者使用的工具，即可完成正常的投资助手工作流。

Beta 不表示：

- 实盘经纪商自动化
- 保证投资表现
- Strategy 自主激活
- 移除人工批准

V1/Beta 保持 `auto_trade=false`。

---

## 2. 新安装验收

在干净的受支持机器上：

```text
git clone
docker compose up -d
```

用户必须能够打开 Web UI 并进入 Setup Wizard。

通过条件：

- 数据库迁移成功
- API 健康
- worker 健康
- Web UI 可访问
- 不需要手动初始化数据库
- 普通引导不需要隐藏的一次性开发者脚本

---

## 3. 模型供应商验收

仅通过 UI，用户可以：

- 创建 OpenAI-compatible 供应商配置文件
- 输入 base URL、模型和密钥
- 测试连接
- 查看经清洗的成功/失败结果
- 分配默认模型
- 运行一次模式有效的 Agent 调用

安全检查：

- 密钥绝不以明文返回
- 密钥不出现在日志中
- AgentRun 记录实际供应商/模型
- 超时失败闭合
- 无效结构化输出遵循有限修复策略
- 模型失败不能默认变成 BUY/ADD

---

## 4. 数据供应商验收

仅通过 UI，用户可以：

- 配置一个已授权研究/数据供应商
- 测试连接
- 查看供应商健康/新鲜度
- 同步至少一个真实且已授权标的

可追溯性检查：

```text
Provider payload
→ ResearchArtifact
→ Evidence
```

通过条件：

- 保留 source/locator/timestamps
- schema validation 处于启用状态
- 不与 DSA 私有 DB/internal 实现耦合
- stale/malformed/unavailable 数据是明确状态
- 类提示词外部内容保持不可信数据

---

## 5. Portfolio 验收

仅通过 UI，用户可以创建 Portfolio，并通过以下方式填充：

- 手工录入
- CSV 导入预览 + 确认

支持的必填字段：

- market
- symbol
- name
- asset type
- currency
- quantity
- average cost
- Core/Tactical bucket

通过条件：

- 导入预览不产生修改
- 无效行得到清晰报告
- symbol normalization 可见
- 用户在提交前明确确认
- 已提交的 positions 可对账
- Portfolio 页面反映导入 positions
- 真实个人持仓绝不出现在测试夹具/仓库工件中

---

## 6. Watchlist 验收

仅通过 UI，用户可以：

- 搜索/添加一个 instrument
- 移除一个 instrument
- 查看 lifecycle state
- 查看 Thesis state
- 查看 data freshness
- 查看下一 monitoring condition

---

## 7. Initial-analysis 验收

用户点击：

```text
Run Initial Analysis
```

对于至少一个已授权真实/影子 instrument，系统必须持久化并展示完整链路：

```text
Evidence
→ FeatureSnapshot
→ Thesis
→ specialist Agent opinions
→ conflict record if applicable
→ Devil's Advocate when required
→ Portfolio Manager risk_intent
→ RiskAssessment
→ PositionSizingRun
→ CIO
→ InvestmentDecision
```

通过条件：

- AnalysisRun progress 可见
- failure 明确且有界
- correlation/provenance 可重建
- 缺失 Risk assessment 不得解释为 PASS
- 不接受 LLM 生成的任意最终百分比
- Decision 引用准确 versions/snapshots

---

## 8. Decision Center 验收

Decision 详情页必须展示：

- Action
- confidence
- Thesis state
- Core action
- Tactical action
- current position
- proposed target/delta
- Risk gate and flags
- Evidence freshness
- reasons
- unknowns
- dissent
- invalidation/watch conditions
- next review
- relevant historical versions

用户必须能够下钻到支撑 Evidence 和 Agent opinions。

---

## 9. 人工批准验收

对于合资格 Decision，UI 支持：

- APPROVE
- REJECT
- 在状态机中法律有效时的 REVOKE

通过条件：

- 仅追加的人工动作
- 记录 actor/time
- TTL 得到强制执行
- 过期批准不能执行
- 撤销批准不能执行
- Risk Veto 不能被覆盖
- 批准不等于执行

---

## 10. 手工执行验收

在外部完成交易后，用户可以记录一笔 MANUAL execution。

必填输入：

- quantity
- price
- 适用时的 fees
- execution timestamp
- 经清洗的 external reference/note

通过条件：

- 适用时要求有效 approval linkage
- fill state 一致
- 应用不提交经纪商订单
- 记录不可变且可审计

---

## 11. 运行时调度器验收

正在运行的 worker（而非 test harness）必须评估到期工作。

对于至少一个明确的合成/已授权市场会话：

```text
worker
→ calendar
→ due job
→ dispatcher
→ advisory lock
→ TaskRun
→ handler
→ Event/Outbox
→ Report/Analysis effect
```

通过条件：

- 不得将 direct dispatcher call 作为唯一 E2E 证明
- retry 具幂等性
- 重复并发调用只有一次业务效果
- failures 可持久化且可见
- as-of replay 可用
- 不得使用 server local timezone 作为业务时间

---

## 12. 日常使用验收

引导后的下一个到期会话，无需手工 CLI 调用，系统必须：

- 同步已授权数据
- 评估 Portfolio/Watchlist 变化
- 创建/更新相关 analysis
- 在适当时产生 Decisions
- 生成 Daily Report
- 展示 operational/data/risk exceptions

Dashboard 必须清晰回答：

- 什么需要动作
- 什么可以继续持有
- 什么仅在观察
- 出现了哪些新机会
- 存在哪些 Risk Veto
- 哪些 approvals 待处理
- data/jobs 是否降级

---

## 13. 每周机会验收

每周运行必须演示：

```text
market universe
→ deterministic funnel
→ bounded candidate set
→ deep research only for candidates
→ Opportunities UI
```

通过条件：

- 不得对整个 market universe 无差别扇出 strong-model
- candidate reason 可见
- 缺失 Evidence 可见
- lifecycle state 可见
- 没有 candidate 被自动交易

---

## 14. 失败模式验收

Beta 至少必须明确验证：

- model provider unavailable
- invalid model schema output
- data provider unavailable
- stale Evidence
- conflicting Evidence
- Portfolio import invalid row
- RiskAssessment UNKNOWN
- Risk VETO
- scheduler retry
- duplicate job invocation
- expired approval
- revoked approval
- report unavailable
- partial AnalysisRun failure

对于每一种情况，系统必须安全且可见地降级。

---

## 15. 安全/隐私验收

验证：

- 仓库中没有真实 API key
- browser/API read response 中没有 secret
- 日志中没有 secret
- 没有提交真实 portfolio fixture
- 审计 payload 中没有 provider raw credential
- 没有不受限制的 live execution adapter
- 没有将 external content 当作 instructions
- dependency/security scans 保持通过

---

## 16. 可用性验收

熟悉投资但不了解仓库内部实现的人员必须能够完成：

```text
configure provider
→ import Portfolio
→ add Watchlist
→ run analysis
→ read Decision
→ Approve/Reject
→ record manual execution
```

且仅靠 UI guidance 完成。

开发者文档可以存在，但普通使用不得依赖它。

---

## 17. 所需发布证据

在宣布 Beta 就绪前，附加或记录：

- 准确 commit SHA
- CI run
- E2E run evidence
- fresh-install evidence
- 已脱敏 secrets 的 provider test evidence
- 使用去标识化/合成 sample 的 Portfolio import test
- complete analysis trace
- scheduler runtime trace
- approval/manual-execution trace
- known limitations
- unresolved human-governance decisions

---

## 18. Beta 结论

只有当上述每个 mandatory section 均为 PASS，或由 human-approved scope decision 明确标记为 NOT APPLICABLE 时，Beta 才通过。

仅有绿色 unit-test suite 不足够。

仅有由 synthetic hard-coded cards 支撑的可运行 UI 不足够。

没有 user-operable UI 的可运行 backend 不足够。

没有 runtime orchestration 的完整 domain model 不足够。
