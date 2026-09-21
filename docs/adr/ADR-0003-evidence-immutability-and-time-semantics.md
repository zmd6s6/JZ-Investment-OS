# ADR-0003 — Evidence 不可变性与时间语义

- 状态：Accepted
- 日期：2026-09-17
- 决策者：经人类批准的主规范；由 Codex 实现
- 取代：无
- 被取代者：无
- 相关阶段：PR-02 / PR-03

## 背景

投资决策必须能从当时实际可用的信息重建。覆盖已修正数据或混淆事件时间与摄入时间，会造成前视偏差并破坏可审计性。

## 决策

Evidence 只追加且按内容寻址。修正创建带 `supersedes_id` 的新记录，绝不改变历史 payload。持久化 UTC `observed_at`、`effective_at`、`available_at` 与 `ingested_at`。回测和 as-of 读取仅可在 `available_at <= simulation_time` 时使用记录。

核心不可变工件保存 `content_hash`、Schema 版本、correlation/causation ID 和溯源。数据库数值使用 `numeric`/`Decimal` 和 `timestamptz`。

## 已考虑的替代方案

### 原地更新最新行

未选择，因为过去的决策会被静默改变含义。

### 只保存发布日期/生效日期

未选择，因为延迟可用和摄入会让未来信息进入历史评估。

## 后果

存储会增长，调用方需要 as-of 查询，但决策、重放和回测保持可复现。

## 安全与运维影响

不可变原始 payload 可能包含敏感文字。保留、访问、加密和脱敏在摄入时实施；密钥绝不得作为 Evidence 持久化。

## 迁移与回滚

PR-02 创建只追加表，PR-03 填充它们。Schema 变化添加版本和前向迁移；不得重写旧 hash。

## 引用

- 主规范第 2.2、2.3、5.1、5.2 节和 S13
