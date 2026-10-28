# User-visible Acceptance

> 这是所有者查看“现在到底能用什么”的产品验收台账。仓库状态不能替代浏览器实际行为。

## 状态定义

- `NOT_IMPLEMENTED`：没有可用产品路径；
- `ENGINEERING`：底层实现存在，但尚未形成完整用户路径；
- `INTEGRATED`：真实 UI/API/DB/Worker 已接通；
- `ACCEPTANCE_READY`：可由所有者直接按步骤验收；
- `ACCEPTED`：所有者已完成可见验收；
- `DEGRADED`：可用但存在明确限制/失败。

## 当前 Checkpoint

| Capability | Route | Current truth | Human acceptance |
|---|---|---|---|
| Portfolio / CSV import | `/portfolio` | ACCEPTANCE_READY — MVP-101已由PR #21合入Release；手工 / 分仓 / 现金 / CSV预览及冲突 / 对账 / 刷新已有隔离可见验证 | PENDING |
| Watchlist | `/watchlist` | ACCEPTANCE_READY — MVP-101已由PR #21合入Release；目录搜索 / 幂等添加 / 刷新 / 删除 / 四项缺失状态已有验证 | PENDING |
| Investment Policy review | `/#policy` | ACCEPTANCE_READY — MVP-101已核对实际API版本与无写入审阅；真实参数仍由Owner治理 | PENDING |
| Acceptance Center | `/acceptance` | ACCEPTANCE_READY — MVP-000已由PR #20合入Release；构建交付清单不是实时健康检测 | PENDING |
| 人工行情与币种边界 | `/market-data` | INTEGRATED — MVP-201已由PR #22合入Release；人工未核实、CNY限定，非完整分析 | PENDING |
| 参考估值与Sizing缺口 | `/valuation` | ACCEPTANCE_READY — MVP-202已验证CNY分仓/NAV/权重/暴露与来源追溯；人工报价非交易级，缺完整Sizing输入明确阻断；集成记录仅随PR #24合入Release生效 | PENDING |
| 团队影子分析 | `/analysis` | INTEGRATED — PR26已合入9c8b8cb，root对最终463独立64/4合入后审查通过。Risk UNKNOWN、Sizing BLOCKED，仅只读降级 | PENDING |
| 分析依据与资料追溯 | `/analysis` | INTEGRATED — MVP-204已随PR27合入36aed8d，当次冻结来源/论点/角色/分仓/政策/闸门只读下钻，不补完整Risk/Sizing | PENDING |
| Decision Center（MVP-301条件式组件切片） | `/decisions` | 组件INTEGRATED仅随PR #28通过最终独立Gate并实际合入Release生效；真实列表/完整合法Decision链审阅/具名批准拒绝撤销/手工facts已合成验证。整体PARTIAL：现Analysis仍仅Shadow、Risk UNKNOWN/Sizing BLOCKED，不可审批；完整P7/Checkpoint B仍PENDING，MVP-501继续BLOCKED | PENDING |
| Daily Runtime（团队分析 / 周月复核） | product UI | ENGINEERING baseline only；MVP-401仅交付下列日历状态报告，完整团队运行仍未接通 | PENDING |
| 日历状态报告（MVP-401独立切片） | `/calendar`，设置页提供入口 | MVP-401=INTEGRATED / ACCEPTANCE_READY，此记录随PR #23通过最终独立Gate合入Release生效。91801d0已获独立28项SQL / 1项恢复浏览器复验；仅STATUS_ONLY，不含团队分析或完整Daily Runtime | PENDING |
| Opportunities | `/opportunities` | PARTIAL — PR25有限范围/人工年报/确定性漏斗已集成；后续单候选显式研究已真实接线验证，集成记录仅随后续PR独立Gate并合入生效；全市场/周定时未提供 | PENDING |

## Checkpoint A 验收步骤

### 产品进度入口（MVP-000）

从主导航「产品进度与验收」或直接打开 `/acceptance`，分别查看工程交付、集成证据、人工验收和服务装配。
展开操作指引，进入组合 / 观察清单 / 设置 / 政策页面；分析、决策、机会等未交付产品不提供误导链接。
刷新后仍须显示待所有者验收；本页没有写入、验收通过或调用模型按钮。
读取失败显示中文错误，成功卡片清空，点「刷新产品进度」只读重试；服务未装配保留工程证据但隐藏入口。
这只描述当前构建的已记录交付及用例装配，不保证数据库 / 供应商健康，不保证已授权或已配置，也不接受Checkpoint。
工程与集成证据见 `docs/agent/work-items/MVP-000.md`，所有者部署与产品接受仍未执行。

### Portfolio / Watchlist

MVP-101于2026-10-27在独立合成API / DB完成可见路径复验，修复CSV迟到预览、旧冲突选择以及确认结果的跨组合展示；现金竞态复修后前端34/34、Chrome15/15通过；主代理独立复验现金/预览/反馈16/16、本项真实浏览器7/7。PR #21已通过独立Gate并合入Release。
这不是所有者本人接受，不改变PRODUCT-05 IN_PROGRESS或Checkpoint A PENDING。证据、输入与明确限制见 `docs/agent/work-items/MVP-101.md`。
CSV请求处理中切换组合或改动内容后，迟到预览不能恢复确认；内容变化后须重新预览并选择冲突方式。
已发出的确认仍写入原组合；切换后的页面不会把原组合对账当成本组合结果，回到原组合可查导入历史。

1. 打开 Portfolio；
2. 创建/选择 Portfolio；
3. 手工添加持仓；
4. 上传 CSV，查看 Preview/错误；
5. Confirm 后刷新，数据仍存在；
6. 查看导入对账结果；
7. 打开 Watchlist，搜索并添加/移除标的；
8. 查看生命周期/Thesis/数据新鲜度/下一监控条件的真实或显式空状态；
9. 查看当前 Policy version 与 TEST_DEFAULT 警告；
10. 至少验证一个失败路径，错误必须用户可见。

通过后才将 PRODUCT-05 标为 ACCEPTED。

## 规则

### 日历状态报告验收路径（MVP-401）

设置 → 配置市场日历与查看运行记录 → 选择市场 / 填来源与版本 → 上传或粘贴CSV → 确认来源 → 预览UTC时段 → 明确导入。
新版本显示暂停；勾选「仅状态报告」后启用，在到期时段观察真实Worker记录与来源摘要，刷新仍保留，再暂停。
失败路径：重复日期 / 部分错误整批拒绝且保留输入；读取失败禁止保存 / 启停并显示未知，可只读刷新恢复。
无Worker或无到期会话时没有报告不表示健康；本路径不含团队研究、费用授权、投资建议或交易。
详细命令、独立栈与迁移恢复证据见 `docs/agent/work-items/MVP-401.md`。尚未操作所有者实例，所有者验收PENDING。
证据归属：c0ad765旧头独立日历四文件25/25、普通浏览器2/2仅限旧实现；恢复与双交错修复后的91801d0由root独立复跑四文件28/28（8.75秒）及原样真实API / DB / Worker恢复浏览器1/1（15.7秒），源码无新增blocker。
91801d0的Linux六CI全绿，完整454 / 85.50%、集成51；这是该精确提交的工程证据，不代替后续提交的最终合入门禁。MVP-401集成记录随PR #23合入Release生效，Owner=PENDING、完整PRODUCT-08=PLANNED。

任何业务 Work Item PR 都必须更新本文件或产品 `/acceptance` 页面对应能力的真实状态。不得把 API 存在、单测通过或静态 UI 等同于用户可用。

## 人工行情与币种边界（MVP-201，Checkpoint B的输入切片）

MVP-201已完成隔离合成环境UI / API / DB接线验证，并由PR #22合入Release；Owner部署与人工验收PENDING。
进入 `/settings` →「记录人工行情／查看单币种与FX边界」或 `/market-data`；先登记标的，再搜索、填来源 / 出处 / 精确价格及四个业务时间，明确保存后读取。
应看到Evidence、hash、UTC来源时间；刷新后再次读取仍存在。错误应保留输入，过期 / 缺价 / 未来资料不显示价格；切换USD估值应显示缺FX并阻止。
人工资料始终未经独立核实、非交易级；不自动调用模型 / 网页或产生订单。工程 / 浏览器证据与限制见 `docs/agent/work-items/MVP-201.md`。
完整分析、FX、全市场行情、波动率 / 流动性及Sizing不在本切片交付中，不能因此接受整个P6或Checkpoint。


## MVP-202 参考估值验收

依次在资产组合录入现金和分仓、人工行情记录同一来源名称有效CNY报价，再到估值对账选择组合/来源并读取。现金100、Core10/Tactical2、价19.25应得到NAV331和分仓192.5/38.5；刷新明确重读可复验。检查Evidence与UTC时间，以及政策/历史波动/流动性/预占容量等缺口；不能生成建议数量或投资动作。缺价/过期不给完整NAV/权重，非CNY整组缺FX阻断。Owner未接受Checkpoint，完整分析仍属203/204。证据见docs/agent/work-items/MVP-202.md。


## 有限范围机会漏斗（MVP-402，PARTIAL）

后续单候选研究验收：在原筛选结果选择「准备研究候选」，核对候选Evidence/行情来源，明确组合与模型（可选新资料源/查询）。分别勾选本次模型持仓出站和资料调用费用同意后，只发起这一个候选。应看到真实Worker阶段与最终降级影子结论、Risk UNKNOWN / Sizing BLOCKED / 无建议数量；刷新保留原漏斗与研究关联。正常、坏CIO失败、非候选与无同意拒绝的真实Chrome3/3（21.5秒）已实际验证，仅合成API18113/DB15441/真实Worker/loopback模型。原漏斗不重算、不覆盖，没有批量扇出。

排队失败或响应未知时，先只读刷新；存在未入队意图须重新核对原请求并单独重新同意原模型/原研究源，明确原请求重试不重复入队。已经发出的模型请求可能收费，不伪造零费用；缺模型/预算/服务未装配明确失败。完整全市场/周定时与P8仍未提供；后续PR独立CI/Gate、Owner部署与接受仍PENDING，不把下列PR25旧数字当新切片证明。

PR25历史切片只接通本地明确手选范围、人工自然年年报事实、确定性四指标 / 分层查询、有界研究候选和不可变历史；工程清单明确PARTIAL。当时全市场 / 深研 / 周定时尚未提供，后续单候选研究见上段，不表示完整402、P8或Checkpoint接受。
入口 `/opportunities`，也可从导航 / 设置 / 产品进度进入。先登记标的并保存人工报价，选择有限范围；绑定报价Evidence，录入有来源的年度利润 / 营收 / 年报稀释EPS和时间，填本次研究查询条件后筛选。
应看到候选与排除理由、缺项、来源 / UTC业务时间 / Evidence / hash；刷新保持旧结果。跨币种缺FX、过期 / 未来 / 损坏 / 口径不符必须停止，不借旧价、不心算EPS、不调用模型或产生交易。
本项21个合成浏览器场景总回归通过，不代替Owner个人数据或产品接受；细节与限制见 `docs/agent/work-items/MVP-402.md`，记录随PR合入Release生效。


## MVP-203 团队影子分析验收（Owner PENDING）

当前事实补充：PR #26已实际合入9c8b8cb，root于最终463源码独立64项/4真实浏览器通过，审查评论6466069735为合入后审查，非root执行合并；下文旧反馈/旧提交验证仅保留历史，不能理解为当前仍未修复。

模型档案在分析期间停用或配置漂移时，本次调用失败关闭；凭据读取和预算预留后的变化均在实际HTTP前核验。若尚未出站，明确记录无出站并释放预占；已经发出的调用仍可能计费。剩余模型边界反馈6457329770的修复为fixed-awaiting-review，当前实现者新源码582项及原样真实合成浏览器4/4通过；新HEAD CI/独立Gate待核对，不借511旧绿状态。

从主导航或设置进入 `/analysis`，按中文引导登记组合/标的并配置模型价格、预算；显式为全部角色选模型，勾选已有有效证据或明确研究源、查询和数据调用同意。核对证据/持仓/现金将发给模型与可能费用后，单独同意并发起。观察排队、冻结输入、两轮和风险/仓位阶段；展开可读角色观点/事实引用，影子结论须显示实际缺口，不能出现BUY/PASS/建议数量。刷新后从历史重读；失败显示具体理由，不补造WATCH。取消只能停止后续步骤，已发出调用可能计费；重试新建Run、重新同意，原历史不变。

本项实现者在专用PG15442/API18114/真实Worker/loopback合成模型验证4/4；root又对09974bb独立运行unit/PG/API/pipeline 32/32（14.55秒）、原样analysis.spec.ts真实4/4（22.9秒），覆盖两轮/刷新、无效CIO/新Run重试、held调用取消、无证据零模型/移动端，未放宽断言。此前MVP-202独立32/3/4仅归其旧提交，不算本项。本PR #26实际合入后203 INTEGRATED、204/301依赖满足READY才生效；新HEAD CI及独立Gate仍须最终核对。这些32/4仅对应09974bb旧代码，随后三项P1（预算最终预留、无效正文前视、研究档案最终解析）已复现并修复；修后实现者新验证见工作项，新HEAD尚须独立复审。全部是合成证据，不是实际付费模型、Owner数据或本人接受。完整Risk/Sizing与可审批Decision未提供，Risk UNKNOWN、Sizing BLOCKED，P6与Checkpoint B未ACCEPTED。详细命令及失败记录见 `docs/agent/work-items/MVP-203.md`。

## MVP-204 分析依据追溯（Owner PENDING）

从 `/analysis` 选择组合的运行历史，在「阅读本次分析的完整依据」核对模型提案→确定性闸门裁决。点击任何事实/理由旁的证据按钮，页面应展开并定位到该次冻结资料：来源、出处、观察/生效/可得/摄入UTC时间、到期、hash、纯文本正文与当次有效性。资料出处只展示、不自动访问；未来/过期或不在快照内的引用不能当作有效事实。

使用章节链接检查当次现金与Core/Tactical成本/数量、参考行情及Evidence、政策版本、Thesis支柱/催化/风险/证伪/监控、确定性特征和两轮各角色。缺少论点/阶段/模型产物时明确未提供；Risk UNKNOWN和Sizing BLOCKED必须保持，不能显示0股建议或可审批Decision。刷新后选择原Run，后来新增的Thesis版本不能替换旧Run。没有资料/坏CIO/取消/详情读取失败须显示明确失败或部分历史；选择其他运行遇到详情读取失败时，旧运行依据先清空，避免跨运行误读。

本项仅展示实际保存的只读产物，既有摘要未记录的观点字段不编造，不重新调用来源或模型。工程/集成/可见测试与独立Gate分开，INTEGRATED仅随本项PR合入生效；Owner部署、本人Checkpoint验收及完整P6仍PENDING。证据见 `docs/agent/work-items/MVP-204.md`。


## MVP-301 组件切片与完整主链边界

MVP-301的条件式INTEGRATED只指有效完整PR07 Decision输入下的决策中心组件，并且只在PR #28经独立Gate实际合入Release后生效。当前Analysis仍只生成Shadow、Risk UNKNOWN / Sizing BLOCKED，不能生成可批准或可执行的完整Decision；不存在默认Policy/数量/许可填空。隔离合成环境618后端/102集成、89前端、中心3与分析追溯6真实浏览器仅是工程与接线证据，不是Owner部署或接受。完整P7、Checkpoint B及Owner接受仍PENDING；MVP-501继续BLOCKED，不能据组件状态解锁完整Beta E2E。

MVP-301修后候选另已实际合并Release39f5738：完整667/87.63%、集成140、前端95与新源码真实中心3/3通过；时间竞态、完整引用链及跨Decision幂等三项独立Review反馈为fixed-awaiting-review，新HEAD CI/root独立Gate另核。旧源码绿色证据不替代修后验收；这不改变上述P7/Checkpoint B/Owner PENDING及MVP-501 BLOCKED边界。
