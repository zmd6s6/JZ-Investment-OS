# PRODUCT-09 — Beta 验收

- 状态：`PLANNED`
- 前置条件：`PRODUCT-05` 至 `PRODUCT-08` 均已由所有者接受
- 治理规范：`INVESTMENT_OS_MASTER_SPEC.md` §18、§19、§21 至 §25
- 相关 ADR：全部已接受且与 P5–P8 范围相关的 ADR；尤其是 `ADR-0002`、`ADR-0003`、`ADR-0006`、`ADR-0007`、
  `ADR-0008`、`ADR-0009`、`ADR-0010`、`ADR-0015`、`ADR-0016`
- 安全基线：`auto_trade=false`；Beta 不是实盘交易、策略激活或投资表现承诺

## 目标

以 `docs/product/BETA_ACCEPTANCE.md` 为唯一产品可用性门槛，验证干净安装、设置、已授权模型/数据、Portfolio/Watchlist、
一次完整影子分析、Decision 人工处理、外部手工执行记录和日常调度报告的端到端体验。只有通过此阶段并获所有者接受，
才可把产品描述为“可正常使用的 Beta”。

## 范围

1. 建立并维护 **`BETA_ACCEPTANCE` 功能追溯矩阵**：`BETA_ACCEPTANCE §2–§18 → owning stage（P1–P8）→
   automated/manual evidence`。P9 只负责 fresh-install + 端到端重跑/汇总，不得首次发现无人负责的功能缺口；
   若发现缺口，先补进对应 P5–P8 契约或经所有者记录为明确豁免。
2. 逐条执行并记录 `BETA_ACCEPTANCE.md`；每条给出版本、环境、脱敏输入、实际结果、证据链接及失败/豁免理由。
3. 用合成或明确授权且去标识化数据进行可重复的安装、迁移、API/UI/E2E、安全和调度验证。
4. **恢复相关验收限定为**：干净安装、迁移前向修复（forward-fix）与最小可启动性；不把正式
   backup/restore 演练作为 P9 通过条件。
5. 对已授权真实 provider 的最小验证必须遵守已确认许可、成本、市场、查询、保留与隐私边界；不得扩大测试范围。
6. 汇总 Beta 已知限制、恢复步骤、降级行为、操作说明和需要所有者签字的治理项。

## 不变量与范围外事项

- Beta 验收不能以静态页面、伪造数据、单元测试或局部 PR-09 预研替代端到端产品流。
- 密钥、个人 Portfolio、真实投资数据和敏感响应不得进入版本库、日志、截图、报告或验收附件。
- 未经有效人类批准，不存在从提案/Decision 到任何真实订单的路径；Beta 始终保持 `auto_trade=false`。
- **正式 PostgreSQL 备份/恢复演练、含数据恢复 hardening 归 `PR-09`**，不在 P9 要求；避免与 PR-09 范围形成
  循环依赖。
- 本阶段不宣称发布、生产 SLA、真实投资业绩或 Strategy 激活；这些属于后续 PR-09 和独立的人类治理。
- 完整多用户认证/授权、CSRF、外网 TLS 等安全加固归后续 hardening/PR-09，不是本地单用户功能 Beta 的阻塞项；
  Risk Veto、人工批准、确定性仓位、历史不可变与 `auto_trade=false` 仍是硬门槛。

## 人工边界

所有者决定哪些真实 provider、个人数据和运行环境可用于最终验收，并对 Beta 结果作出 `ACCEPTED` 或退回决定。任何
关于真实 Policy、评价窗口、成本、策略激活、券商连接或实盘交易的决定都不包含在 Beta 验收中。

## 验收标准

1. `BETA_ACCEPTANCE.md` 的所有适用条目均可在追溯矩阵中定位 owning stage 与证据；不适用或未验证项必须明确、
   经所有者接受，不能静默略过。
2. 新安装所有者无需 SQL、原始 JSON、curl 或开发者脚本，即能完成规定的产品工作流。
3. 失败关闭、数据来源、时效、风险、批准、模拟状态、隐私和密钥边界在 UI/API/运行记录中均可审计。
4. 干净安装、迁移前向修复、密钥扫描、Compose、OpenAPI 与关键 UI/Worker E2E 均以实际结果记录；
   正式 backup/restore 演练不在本阶段通过条件内（归 PR-09）。
5. 所有者明确接受 P9 后，`PR-09` 的阻塞条件才解除；P9 接受本身不等于 PR-09 完成或发布。

## 与 PR-09 的衔接

`PR-09` 在本阶段完成且被所有者 `ACCEPTED` 前保持 `BLOCKED`。恢复后必须先重新审计 PR-09 的阶段契约、当前代码
和验证证据是否仍然有效，再推进 Outcome、Review/Learning、正式 backup/restore hardening 和发布工作；不得将旧的
未合并预研直接等同于完成。
