# ADR-0016 — 数据提供方保留期限与同步可观测性

- 状态：Accepted
- 日期：2026-09-23
- 决策者：仓库所有者；已确认博查个人研究用途及 365 天保留边界
- 相关阶段：PRODUCT-04

## 背景

Evidence 必须不可变，但外部数据源又可能要求有限的本地使用期限。连接成功也不等于实际同步成功，设置页需要分别展示两种状态。

## 决策

每个 `DataProviderProfile` 保存明确的 `retention_days`。适配器以请求时的 UTC `as_of` 加该期限写入新 Evidence 的
`expires_at`；到期 Evidence 保持审计历史，但不得再被作为新分析输入。默认值为 365 天，仅作为经所有者确认的
当前数据保留边界，不构成投资规则。同步状态以无凭据的追加事件记录，成功状态只在全部请求结果完成 Evidence
摄取后写入。Compose 为 API 的加密 SecretStore 使用独立命名卷。

## 后果与回滚

旧 Evidence 不会被原地修改；迁移前已写入且无 `expires_at` 的记录保持原样。迁移回滚仅移除档案配置列，
不会删除 Evidence 或 SecretStore 卷；应优先前向修复。

## 安全影响

事件、UI 和 API 仅暴露状态、时间、数量和延迟，绝不包含凭据或外部正文。外部搜索内容仍是不可信数据。

## 引用

- `INVESTMENT_OS_MASTER_SPEC.md` §2.2、§2.3、§16、§17
- ADR-0003、ADR-0010、ADR-0013、ADR-0015
