# ADR-0015 — 多提供方研究数据运行时

- 状态：Accepted
- 日期：2026-09-22
- 决策者：仓库所有者；明确要求后续可接入多个数据源
- 取代：无
- 被取代者：无
- 相关阶段：PRODUCT-04 及后续产品化阶段

## 背景

既有 `ResearchProviderPort` 与 `DSAAdapter` 已将 DSA 私有实现隔离在基础设施层。产品不能因此把 DSA
固化为唯一研究来源：不同市场、数据类别、许可证和可用性可能要求多个供应商并行存在。另一方面，直接在
应用或领域代码中写供应商分支，会破坏可审计性，并容易形成不透明的来源回退。

## 决策

研究数据运行时采用“多档案、适配器注册、统一内部 DTO、显式路由”的结构：

```text
DataProviderProfile（多个、显式启用）
        ↓
DataProviderRuntimeRegistry（provider_type → 基础设施 adapter factory）
        ↓
ResearchProviderPort（统一、带版本的内部 DTO）
        ↓
Evidence 摄取 / 去重 / 质量与新鲜度评估
```

- 一个 `DataProviderProfile` 只描述一个已授权端点、凭据引用、超时和启用状态；未来可增加能力声明与健康元数据，
  但不保存凭据明文。
- 每个供应商的 HTTP、SDK、认证、分页和外部 Schema 映射只存在于 infrastructure adapter。`domain` 和
  application 仅使用 `ResearchProviderPort` 与内部版本化 DTO。
- DSA 是一个可替换 adapter，而非特殊的权威路径；禁止导入 DSA 私有模块或查询其私有数据库。
- 一次摄取必须显式指定允许使用的 provider profile；不因为失败、缺数据或成本自动切换到另一个供应商。
  若将来引入回退，必须由调用方显式声明顺序，并在运行/审计记录中保留每次尝试和实际来源。
- 不同来源的工件独立保留 provider、provider_ref、source、schema version、业务时间、内容 hash、质量和
  新鲜度。冲突交由既有 Evidence 质量规则显式表达，禁止用“最后响应者”静默覆盖。
- 各 adapter 必须实现受限连接/健康检查、超时、最小权限认证、Schema 漂移失败关闭和脱敏错误。真实网络调用
  仅在所有者已授权该供应商、许可、端点和数据边界后执行。

## 已考虑的替代方案

### 将 DSA 作为唯一数据源

未选择。它会让产品能力和可用性受单一外部系统限制，也不满足所有者未来接入多个数据源的需求。

### 在业务用例中按供应商名称分支

未选择。它会让供应商协议穿透应用/领域边界，增加不可审计的回退与 Schema 漂移风险。

### 自动聚合并选取“最佳”来源

未选择。来源优先级、许可、冲突消解和成本属于可审计的产品/治理选择，不能隐式决定。

## 后果

PRODUCT-04 可以逐个交付 adapter：首个 adapter 通过合成夹具、配置/健康 UI 和明确授权验证后，后续供应商
复用同一内部协议而不修改领域模型。新增供应商类型、公共 API/Schema 兼容性、时间/保留语义或自动回退规则
发生改变时，必须另行评审 ADR 和迁移方案。

## 安全与运维影响

凭据仅由 `SecretStore` 按 profile 引用读取。供应商响应均是不可信数据，不能作为指令；原始内容、日志、
审计与 UI 不得泄漏凭据或未授权个人数据。一个供应商不可用时，既有 Evidence 仍可读取，新的摄取显式失败。

## 迁移与回滚

当前决定复用既有 profile 与 port，不进行数据迁移。后续增加运行时 registry、能力/健康字段或 adapter 时，
应采用前向兼容迁移；移除 adapter 只禁用其 profile，历史 Evidence 保持可读。

## 引用

- `INVESTMENT_OS_MASTER_SPEC.md` §2.1、§2.2、§3.3、§16、§17
- ADR-0002、ADR-0003、ADR-0010、ADR-0013
- `docs/stages/PRODUCT-04.md`
