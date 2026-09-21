# ADR-0002 — DSA 适配器边界

- 状态：Accepted
- 日期：2026-09-17
- 决策者：经人类批准的主规范；由 Codex 实现
- 取代：无
- 被取代者：无
- 相关阶段：PR-03

## 背景

DSA 是研究/数据基础，而 Investment OS 拥有投资含义和持久决策状态。直接导入或数据库耦合会阻碍独立演进，并会意外让上游数据成为权威。

## 决策

所有 DSA 访问都必须在 `infrastructure/dsa` 后实现 application port。只有带版本的内部 DTO 能跨越边界。适配器记录提供方引用、源 Schema、可用时间、原始内容 hash 和规范化输出。DSA 故障或 Schema 漂移必须失败关闭，且不得创建合成 Evidence。

DSA 永远不得拥有或修改 Portfolio、Thesis、Risk Veto、Decision、Approval、Execution、Outcome 或 Review 状态。

## 已考虑的替代方案

### 共享 DSA 数据库

未选择，因为私有 Schema 没有兼容性契约，并会抹去系统所有权边界。

### 导入 DSA 内部 Python 模块

未选择，因为发布变化会成为无边界的源级破坏性变更。

## 后果

适配器需要映射和契约夹具，但 DSA 可被替换，且不可用时历史决策仍可审计。

## 安全与运维影响

将所有 DSA 内容视为不可信。应用超时、有限重试、限流、Schema 校验、溯源和 Prompt Injection 隔离。

## 迁移与回滚

PR-03 引入 port 和 adapter。提供方变化新增 adapter 与映射版本；旧规范化记录保持可读。

## 引用

- 主规范第 2.1、16.1、16.2 节和 S14
