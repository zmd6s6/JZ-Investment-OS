# ADR-0011 — 纯领域内核与严格 Policy 边界

- 状态：Accepted
- 日期：2026-09-17
- 决策者：主规范约束；由 Codex 实现
- 取代：无
- 被取代者：无
- 相关阶段：PR-01

## 背景

PR-01 需要精确金融数值、受治理的状态转换和严格的 Investment Policy 协议。领域层必须独立于 Pydantic 等框架，同时 JSON 输入仍需要带版本 Schema 和失败关闭校验。

## 决策

在 `investment_os.domain` 内使用冻结、带 slots 的标准库 dataclass、`StrEnum`、`Decimal` 和时区感知值对象。即使绕过输入 adapter，领域构造器也强制不变量。状态机使用封闭转换表和显式 guard context；成功转换返回带机器可读原因代码及 UTC 时间的不可变记录。

严格的 Pydantic v2 `InvestmentPolicySchema` 位于 application 层。它拒绝未知字段、不安全 V1 执行设置和不一致跨字段限额，再将百分比转换为领域 `Weight`。生成的 JSON Schema 提交至 `docs/schemas/investment-policy-v1.json` 并在 CI 检查漂移。

随系统发布的 Policy 为 `TEST_DEFAULT`，仅用于测试配置；没有完整、明确归属的人类批准记录不得变为 `ACTIVE`。

## 已考虑的替代方案

### Pydantic 领域实体

未选择，因为校验框架类型会泄漏到无框架领域，使核心依赖传输层关注点。

### 无结构字典与条件状态更新

未选择，因为未知字段、隐式转换和字符串化 guard 会削弱可审计性及失败关闭行为。

### 二进制浮点百分比

未选择，因为金融规则和 Core 加 Tactical 不变量要求精确相等与可复现。

## 后果

领域规则不依赖基础设施即可测试，对相同输入具确定性。边界模型重复少量结构，但显式转换防止框架和 wire-format 关注点控制业务不变量。Schema 变化需要版本与生成工件更新。

## 安全与运维影响

未知 Policy 字段和不安全执行标志校验失败。Learning Engine 权力由策略转换 guard 表达，不能批准或激活提案。未引入实盘交易、外部数据、数据库或模型能力。

## 迁移与回滚

PR-01 不增加数据库迁移，也不保存生产状态。一起回滚领域模块、Policy Schema/配置、测试和生成 Schema。未来 wire 不兼容必须使用新 Schema 版本和 ADR，不能静默更改版本 `1.0`。

## 引用

- 主规范第 2.4、2.5、7、8、10、15、18 节及 PR-01
- `src/investment_os/domain/`
- `src/investment_os/application/policy_schema.py`
- `tests/unit/test_state_machines.py`
- `tests/property/test_domain_properties.py`
