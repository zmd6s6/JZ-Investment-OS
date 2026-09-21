# ADR-0004 — 结构化 Agent Schema 与模型网关

- 状态：Accepted
- 日期：2026-09-17
- 决策者：经人类批准的主规范；由 Codex 实现
- 取代：无
- 被取代者：无
- 相关阶段：PR-05

## 背景

运行时 Agent 需要提供方无关的执行与机器可验证的通信。自由格式报告无法可靠强制 Evidence、置信度、角色权限或下游决策不变量。

## 决策

所有模型调用经 `LLMGatewayPort`。Agent 输出使用带版本的严格 Pydantic/JSON Schema，包括 AgentOpinion。事实 observation 必须有 Evidence ID。校验至多进行两次附带明确错误的 Schema 修复；之后运行以 `INSUFFICIENT_DATA` 失败，原始文本不得提升为 opinion。

记录提供方、模型、参数、Prompt 版本/hash、工具白名单、输入快照 hash、已验证输出、用量、延迟、重试和已清理的原始输出引用。

## 已考虑的替代方案

### 在每个 Agent 内使用提供方 SDK

未选择，因为会将角色耦合到供应商，且无法集中预算、追踪和安全策略。

### 用 Markdown 作为内部协议

未选择，因为散文无法提供稳定校验或兼容性。

## 后果

Schema 需要版本控制和迁移。提供方变化成为适配器工作，而不是领域重写。

## 安全与运维影响

网关工具使用最小权限、有限成本/超时、脱敏追踪和 Prompt Injection 隔离。模型输出在通过 Schema 和领域校验前均不可信。

## 迁移与回滚

PR-05 引入 v1 Schema。破坏性变更创建新 Schema 版本，并为保留的历史输出提供显式读取器。

## 引用

- 主规范第 4、6、15、16.1 节
