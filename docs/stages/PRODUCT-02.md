# PRODUCT-02 — 设置、密钥存储与提供方档案

- 状态：`READY_FOR_REVIEW`
- 前置条件：PRODUCT-01 已合并；所有者已授权开始 PRODUCT-02
- 治理规范：`INVESTMENT_OS_MASTER_SPEC.md`
- 安全 ADR：`ADR-0013-local-encrypted-secret-store.md`（待人工安全审阅）
- 安全基线：`auto_trade=false`；本阶段不得启用模型、数据或券商运行时调用

## 目标

交付用户可管理的系统设置、模型/数据提供方档案、角色模型分配与本地加密的 SecretStore 基础。数据库仅保存
凭据引用，且所有设置操作均可审计。

## 首个纵切面

- [x] SystemSettings 读写边界
- [x] ModelProviderProfile 与 DataProviderProfile CRUD
- [x] RoleModelAssignment 的确定性默认回退
- [x] 加密 SecretStore 与 `credential_ref`
- [x] 无网络的提供方配置/凭据校验结果与审计事件
- [x] 不返回密钥的设置 API
- [x] Settings UI

## 明确范围外

- 真实模型调用、OpenAI-compatible runtime 或自动回退（PRODUCT-03）
- 真实数据提供方请求、授权或同步（PRODUCT-04）
- 真实组合导入、观察清单写操作、分析编排与交易执行
- 在数据库、审计、日志、API 或夹具中保存明文凭据

## 验收标准

1. 创建或更新提供方档案时，响应和持久化配置只包含 `credential_ref` 和掩码状态。
2. 没有可用主密钥或凭据时，配置校验明确失败关闭，不产生网络请求或虚构成功。
3. 设置、档案和分配写入与不含密钥的 Event/Outbox 记录处于同一事务。
4. 角色只能分配给已启用的模型档案；未分配角色时显式回退到已启用默认档案。
5. 浏览器 UI 显示配置状态和测试结果，但不渲染或缓存密钥。
6. Risk Veto、人工审批、确定性仓位计算和 `auto_trade=false` 不发生变化。

## 验证计划

遵循 PRODUCT-01 的全量质量、迁移、契约、集成、密钥扫描与浏览器 E2E 命令；另补充 SecretStore 轮换/缺失
主密钥、API 密钥泄露、原子 Event/Outbox 与无网络测试的失败路径。

## 实现与验证证据

- `SecretStore` 是应用层端口；本地实现仅将 Fernet 认证密文写入被 Git 忽略的运行时文件。数据库只保存
  UUID `credential_ref`，API 响应仅暴露 `credential_configured`。
- 新迁移 `20260921_0006` 增加系统设置、模型/数据提供方和角色模型分配表，并以数据库约束保证
  `auto_trade=false`、正超时/Token 值和角色分配外键。
- 每次设置/档案/分配写入或无网络校验都在同一数据库事务中追加不含密钥的 Event、Outbox 和 Audit 记录。
  模型角色优先使用显式分配，否则使用已启用的 `DEFAULT`；两者不可用时失败关闭。
- 2026-09-21：`ruff format --check .`、`ruff check .`、`mypy src`、`docker compose config --quiet`、
  `scripts/export_openapi.py --check`、`scripts/check_secrets.py` 与 `pip-audit` 均通过（密钥扫描覆盖
  219 个文件；依赖审计无已知漏洞）。
- 2026-09-21：按测试层累积执行 320 项 Python 测试并以隔离 coverage 数据复核，整体覆盖率 90%；
  前端 Vitest 4 项及在全新隔离 Compose 栈中的 Playwright 2 项均通过。

## 待人工审阅

- ADR-0013 仍为 `Proposed`。请审阅本地加密文件、主密钥备份/轮换和运行时文件权限是否符合所有者的
  安全与恢复要求；在接受 ADR 前不得把本阶段标记为 `ACCEPTED`。
