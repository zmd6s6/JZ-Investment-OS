# MVP-BETA 决策历史可达性补货

## 实际控制状态

基线Release为`e7b8ac5a5a14b4ee8570d8712c3b87a456141029`。已安全fetch，实际PR49为MERGED，root合入后独立核验[6802776134](https://github.com/zmd6s6/JZ-Investment-OS/pull/49#issuecomment-6802776134)没有可执行的新阻塞意见。原46e六CI、独立47项PG/两项真实Worker与Edge/迁移保留52日报hash均为既有406交付证据，本轮未重复运行或追认为root合入前Gate。

权威队列16项没有READY。405/406已实际集成但队列仍保留REVIEW、执行权在root；不存在开放功能修复PR，不能据旧候选状态重建已交付功能。402本地链已集成，整个项保持REVIEW/PARTIAL；501仍受PRODUCT09的Owner接受前提。当前开放仅旧PR18到main，没有开放Planner。已核远端Claim、工作树清单和301/402/406 Handoff，原分支与未跟踪证据均保留，301原实现者已经停止写入并释放窗口。没有新agent/MVP-407 Claim。

本轮独立Planner树和分支为`planner/mvp-beta-replenish-after406-20261112`。主规范、根AGENTS、自治/DEVELOPMENT_LOOP、阶段与ADR相对已读取46e版本没有变更，已复核P7及ADR0043/0049、当前Release/Queue/DECISIONS和相关Handoff。没有治理待决项。

## 真实产品缺口

PRODUCT07范围1、验收1要求所有者仅靠UI找到并完整审阅Decision和Journal；BETA_ACCEPTANCE §8–10/16要求审阅、人工处理与手工记录的产品路径。当前正常路径会在历史超过100条后失联。

- `infrastructure/decision_center.py` 的 `SqlDecisionCenter.list` 按created_at/id排序并固定`.limit(100)`，没有分页参数。typed `DecisionCenterPort.list`及API列表只支持portfolio_id，不能从产品继续读取第101条。
- `web/src/DecisionCenterPage.tsx` 的 `refreshList` 仅在URL的decision_id存在于这一页数组中时调用open，否则显示链接不在当前列表。该判断使一个实际存在、可精确读取的旧记录被UI拒绝。
- 同一SQL adapter的 `get(decision_id)`和既有详情API已经能直接加载原记录，完整资格、当前状态与人工动作最后闸门也已存在。缺口在列表/精确导航接线，没有证据需要更改投资资格或重新实现批准语义。

因此新增MVP407只恢复完整历史中的产品可达性。它属于P7独立纵切，依赖301/206已实际INTEGRATED，允许在Owner阶段接受前完成工程。405首页运营总览继续保留自身有界窗口；406的Daily扫描/历史不重复实现；402已有Claim和范围不被本项接管。

## 最小范围与边界

扩展既有typed read port和真实SQL列表为有界稳定分页，保留默认响应形状与旧调用。UI可加载更早记录，显示页或已加载范围及筛选口径，不能把本页结果或过滤当作全局总量。实时分页的并发变动限制应明确，刷新可重查。

精确decision_id独立经已有GET读取并验证身份，不以列表页成员资格冒充存在或授权检查。查询不存在、协议损坏、读取失败、迟到响应或切换选择时清空旧详情/确认，不能显示另一记录的可用动作。旧记录的Journal/Evidence/历史仍来自原不可变源，不能补造缺失字段、改hash或回填状态。

所有人工动作继续要求真实当前allowed_actions、具名理由、独立确认、版本CAS、TTL、Risk Veto、Policy/Strategy资格、确定性数量和事务审计。可达性不延长任何期限、不覆盖Veto、不使legacy/TEST_DEFAULT可批准、不扩大任何模型或资料授权。没有新调度、模型调用、Strategy激活、券商或订单；auto_trade=false。优先复用已有读取与动作实现，不引入新生产依赖或无关Schema/状态投影。

## 开发时验证

具名PG/API验证100与101以上真实持久Decision、页边界/稳定排序、跨页刷新、精确ID不在第一页仍正确读取、GET零业务写入、缺失/损坏ID与legacy兼容。通过既有完整合成资格端口生成合法旧Decision，其他记录不能使用伪造真实Policy。对旧合法记录执行明确人类动作并证明原Decision/hash不变、人工历史只追加；过期/撤销/Veto/缺链及并发版本仍拒绝。

独立合成生产API/PG/浏览器从列表加载旧记录及精确URL打开，审阅固定链，明确处理并刷新，演示网络失败/恢复、错页/迟到身份与390宽。上游需要Worker产物时沿真实Analysis→Decision桥接已有路径验证，不能用静态卡片或模型连接测试代替。运行全部必要基线和OpenAPI兼容检查，取得精确HEAD独立Gate后才合入，Owner部署和产品接受另行记录。

## 本轮机器记录

```text
work_item: PLANNER / proposed MVP-407
base: e7b8ac5a5a14b4ee8570d8712c3b87a456141029
code_changed: NONE
business_code_sha: NONE
checks: actual Release/PR/Claim/worktree/Handoff and source inspection; PyYAML PASS 17 unique legal acyclic items, original 16 fully preserved, 407 dependencies integrated, 402 REVIEW/501 BLOCKED, no remote 407 Claim; git diff --check PASS
pr_state: unique Planner PR pending creation; no new functional PR
user_visible: NOT VERIFIED — proposed /decisions complete historical navigation
owner_decision: NONE
blocking_condition: Planner PR must actually merge before create-only Claim; implementation and independent final-HEAD Gate follow
```

本轮没有业务代码交付，没有运行功能测试。只提出可证明的产品缺口，保留既有16项对象及所有Claim，不以队列状态改写完成事实，不因Owner接受待完成而伪造新的治理阻塞。
