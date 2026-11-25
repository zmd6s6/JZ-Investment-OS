# ADR-0061 — 人工 Thesis 内容命令与原子请求回执

- 状态：Proposed（MVP-412实现候选，独立Review Gate待核）
- 日期：2026-11-25
- 依据：Master §2.2/2.3/5.3/6.3/8.2/16–19，ADR0003/0008/0010/0011/0041；不取代已接受ADR。

## 背景与决定

既有内部writer不是面向人工的完整授权、时效、CAS与请求幂等边界。新增严格版本1.0 application command/read port与`/thesis`工作台，旧GET保持原响应。初次仅UNKNOWN，修订必须与当前状态完全相同，包括BROKEN不能恢复。人工支柱判断与Thesis整体状态分开，任何判断不核实来源、不授予投资资格。

命令必须显式携带expected_version_id/hash（仅不存在允许同时null）、request UUID、具名人工记录人与结构化draft，不接收回溯as_of、trusted source标记或full-review捷径。认证仍是已有本机单用户Bearer写令牌；actor_name是认证本机使用者填写的审计归属，不冒充独立身份认证。读取沿用原Thesis读取权限，不扩大外部暴露。

请求规范hash含标的、基线、actor和规范领域内容。事务先按request再按instrument获取带命名空间的PostgreSQL事务advisory lock，覆盖不存在的首次创建；内部writer同时使用同一instrument锁，已有乐观当前指针更新继续保留。相同request先返回原已提交回执，不重核后来过期的证据；不同内容/标的/actor/基线冲突。没有实质语义变化不创建版本，仍保存一次可重放的no-op回执和具名审计事件。

预览零写，按服务器UTC验证全部持久化证据归属（已有Analysis允许instrument-neutral）、四时间不晚于now、expiry严格大于now、quality在(0,1]、摄入状态FRESH。保存独立重查基线和证据，在await读取后核验，所有写flush后、最终commit前再次取服务器UTC核验；过期失败整事务回滚。没有caller可信时间、资料正文出站或模型调用。

版本、规范Evidence关联、CAS当前指针、HUMAN Audit、`thesis.human_revision.saved/noop` Event/Outbox和请求回执同一UoW。复用领域content/hash/diff与内部writer的版本构造原语，不调用会自行提交的旧write作为子事务。既有版本和hash不回填。新回执表正规化request/instrument/version FK与命令hash，JSON只保存版本化返回快照，数据库trigger禁止更新/删除。

页面必须先预览，再明确保存。编辑失效旧预览；确定4xx拒绝保留草稿，基线冲突需明确重读与重新预览。网络/5xx/坏响应保持未确认及原请求，禁止自动重试，只提供明确同内容恢复。标的切换使用epoch拒绝迟到响应。返回Analysis不自动选证据或恢复同意；已有Worker仍仅将本Run eligible显式选择集合中的Thesis引用冻结，缺项保持UNKNOWN与THESIS_EVIDENCE_NOT_IN_FROZEN_INPUT。

## 替代方案与影响

拒绝先调用内部writer提交再写receipt（非原子）、以当前版本存在推断初建意图（覆盖并发）、客户端时间或preview永久许可（过期竞态）、状态提升复核flag、自动勾选证据或调用同意、从PR18整体移植。复用PostgreSQL和现有依赖，无新生产服务。工作台读取使用只读REPEATABLE READ单一快照，避免并发读取混合当前指针/版本/来源。Picker仅最近100并补充历史版本原引用，历史列表显示实际不可变版本；不宣称完整来源全集或数据资格。

## 迁移与恢复

0029接0028，仅新增只追加thesis_command_receipt及保护trigger，并为既有thesis_version_evidence追加UPDATE/DELETE保护（不回写数据）；不修改旧版本。空表可降级再升级；有回执时拒绝破坏性降级，回退应用保留表或前向修复。仅专属合成云PG/API/Worker验证，不操作Owner数据库或Docker引擎。迁移、故障回滚、并发、精确到期及回执后到期重放须具名实测。Owner部署/Checkpoint接受PENDING，402PARTIAL/501BLOCKED不变。
