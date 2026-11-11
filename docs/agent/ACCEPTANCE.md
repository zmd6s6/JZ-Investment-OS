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
| 每日完整历史与公平扫描（MVP406候选） | `/calendar` | ENGINEERING候选 — 真实分页/旧授权暂停撤销/过期审计及有界扫描接线已有合成PG/真实Worker/Edge证据，最终CI/独立Gate和实际合入待核；具体步骤见MVP406工作项 | PENDING |
| 运营待办（MVP405候选） | `/` | ENGINEERING候选 — 原PR47恢复实现只读待审批/运行异常/日报降级、精确详情与刷新；正常和故障合成验证见工作项，最终CI/独立Gate及实际合入待核 | PENDING |
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
| Opportunities（本地声明范围） | `/opportunities` | INTEGRATED / ACCEPTANCE_READY — PR41–44已独立Gate后实际合入，完整声明范围筛选、逐候选显式研究、本地周筛选及只读生命周期可按下述步骤验收。仅Release构建；Owner部署未执行，真实全集NOT_PROVIDED、整体402/P8仍PARTIAL | PENDING |

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


## MVP-402 当前本地声明范围（INTEGRATED / ACCEPTANCE_READY）

截至实际Release `a3a0d04`：Engineering、Integrated及User Visible工程层均有独立合成证据，当前受限范围已集成；这不是Owner部署/产品接受或完整全市场承诺。来源始终SOURCE_DECLARED/UNVERIFIED，真实market universe与真实财务/Timing提供方仍NOT_PROVIDED，真实调用仍需具体有效许可与成本/隐私授权。Queue整个MVP-402依协议§11保持REVIEW/PARTIAL，不标DONE；该REVIEW不表示开放功能PR或应重复上述已集成切片。完整P8/Checkpoint PENDING；MVP-501依PRODUCT-09的P5–P8 Owner接受前提继续BLOCKED。

| 已合入能力 | 可执行入口与预期可见结果 | 失败与安全边界 | 独立Gate |
|---|---|---|---|
| 完整来源筛选（PR41） | `/opportunities`来源集合导入/确认后填写本地报价、事实来源及条件，点“完整筛选所选快照（v2）”；显示全部成员、逐层原因/缺项、一次全局最多20候选及来源hash，刷新读取原历史 | 最多1000，早于来源/入库时点失败；不截断，不把声明当真实全集，零模型扇出 | [Gate6738456782](https://github.com/zmd6s6/JZ-Investment-OS/pull/41#issuecomment-6738456782) |
| 显式候选研究（PR42） | 原有界候选点“明确研究此完整筛选候选”，核对组合、模型、资料及费用并逐次同意；显示真实Worker进度/终态，刷新保持原运行关联 | 非候选/错版本/缺Evidence或同意拒绝；失败/未知先只读核对，再明确同内容重试，不自动付费重播 | [Gate6743489395](https://github.com/zmd6s6/JZ-Investment-OS/pull/42#issuecomment-6743489395) |
| 本地周筛选（PR43） | 同页周面板从完整结果选模板，确认完整自然周/日历/仅本地零费用后保存暂停；核对版本后明确启用，到期由Worker写真实周产物；暂停/刷新后历史可读 | 不完整周、未授权写入、前视/换日历/暂停竞态失败关闭；零外网/模型/费用，不自动研究或交易 | [Gate6751583318](https://github.com/zmd6s6/JZ-Investment-OS/pull/43#issuecomment-6751583318) |
| 生命周期来源（PR44） | 新查询展开每行，显示可核初始状态、来源ID/version/UTC时间/hash或具名UNKNOWN；重读旧运行保持原快照 | 未来/修订后无法恢复历史/无效引用不推断状态；旧运行不回填，候选和BUYABLE展示均不是当前买入或批准资格 | [Gate6757832502](https://github.com/zmd6s6/JZ-Investment-OS/pull/44#issuecomment-6757832502) |

独立真实API/PG/Worker及浏览器证据的精确HEAD、命令与适用边界见上述Gate和 `work-items/MVP-402.md` 当前收口表。已停止的合成栈不是Owner可访问部署；所有者验收需在其明确指定环境进行。以下候选/待核措辞保留当次工程历史，当前集成事实以上述表为准。

## 有限范围机会漏斗（历史工程记录，完整产品仍PARTIAL）

生命周期只读快照候选（仅本功能PR实际合入后生效）：`/opportunities`新建有限范围或完整来源查询，展开每行。已存在且可核对初始记录应显示实际状态、instrument_state行ID/版本、生效与记录UTC时间、筛选时点和来源摘要；Thesis/Decision引用仅当同标的且当时存在才保留。无状态、未来状态、来源引用损坏或当前行已修订但无完整可恢复历史分别明确UNKNOWN及原因。候选身份和状态展示分开，显示BUYABLE也不代表当前可买、Risk/Policy或批准通过。刷新/读取历史仍显示原冻结状态，不以当前状态回填；旧运行明确“历史运行未冻结生命周期”。本地周产物按原as-of冻结相同内容，点击原完整结果可读。

新候选后续条件说明需核对资料时效/模型/预算并逐次明确同意；旧历史保留其当时“深研未提供”语义。没有新增状态写入、外部调用或交易。工程合成API/PG/Edge已实际验证正常/修订未知/未来未知/刷新/390宽；Owner部署与接受仍PENDING，完整402/P8不提前完成。精确命令与限制见本项工作记录及ADR0055。

来源快照续接（当前切片，独立Gate/Release集成待核）：打开 `/opportunities` 来源集合面板，明确来源名/版本/locator/市场/覆盖定义、三源业务时间、声明数量与完整性，上传UTF8 `market,symbol` CSV并预览；分别确认合法使用与来源声明边界后保存。应看到服务器入库时间、全部冻结成员、文件/成员/快照hash、Evidence和SOURCE_DECLARED/UNVERIFIED。填原漏斗区报价/事实来源及条件后选择快照完整筛选，应出现真实有界结果与直接来源关联，刷新仍可读。未知/重复/数量不符/未来日期整批失败；201可存且展示全部成员，但筛选明确失败、不截断。历史业务周早于该快照导入/可用时间须可见失败且无周产物。零外网/模型/费用、无自动研究或任务启用；完整402/P8 PARTIAL、501BLOCKED与OwnerPENDING不变。工程合成E2E与Owner接受分开，最新证据见本项工作记录。

后续单候选研究验收：在原筛选结果选择「准备研究候选」，核对候选Evidence/行情来源，明确组合与模型（可选新资料源/查询）。分别勾选本次模型持仓出站和资料调用费用同意后，只发起这一个候选。应看到真实Worker阶段与最终降级影子结论、Risk UNKNOWN / Sizing BLOCKED / 无建议数量；刷新保留原漏斗与研究关联。正常、坏CIO失败、非候选与无同意拒绝的真实Chrome3/3（21.5秒）已实际验证，仅合成API18113/DB15441/真实Worker/loopback模型。原漏斗不重算、不覆盖，没有批量扇出。

排队失败或响应未知时，先只读刷新；存在未入队意图须重新核对原请求并单独重新同意原模型/原研究源，明确原请求重试不重复入队。已经发出的模型请求可能收费，不伪造零费用；缺模型/预算/服务未装配明确失败。完整全市场与P8仍未提供；周筛选续接见下段；后续PR独立CI/Gate、Owner部署与接受仍PENDING，不把下列PR25旧数字当新切片证明。

本地周筛选续接验收：同页第6区选择当前历史漏斗模板，明确市场与完整自然周范围、核对有来源日历的完整性，分别确认完整覆盖与仅本地读取后保存；应看到新版本暂停。再确认保存版本后单独启用，完整周结束后应由Worker写入真实TaskRun/产物/Event/Outbox，运行历史可打开对应候选详情；暂停保留历史且确认后无晚到副作用。缺资料应显示降级/缺项，明确闭市周跳过且无产物，换日历后旧配置阻止排入并需新版本。固定零外网/模型/费用，不消费逐候选深研意图；真实Owner激活和产品接受PENDING。独立合成时钟工程证据以MVP-402工作项最新记录为准，本PR独立Gate与Release集成仍待，不代表完整402/P8接受。

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

MVP-301修后候选另已实际合并Release39f5738：完整674/87.56%、集成147、前端95与新源码真实中心3/3通过；时间竞态、完整引用链及跨Decision幂等三项独立Review反馈为fixed-awaiting-review，新HEAD CI/root独立Gate另核。旧源码绿色证据不替代修后验收；这不改变上述P7/Checkpoint B/Owner PENDING及MVP-501 BLOCKED边界。


## MVP-205 确定性影子数值链（已集成，Owner PENDING）

入口 `/analysis`。选择组合、标的、显式数值快照及 Core/Tactical 分仓，再选择模型并明确同意调用后新建分析。完整合法合成输入应在同一运行显示 NAV、价格、权重、风险原因/Evidence、固定 Policy 版本、仓位公式/容量/舍入/目标数量与不可变产物 ID；刷新读取原保存结果。真实来源资格端口尚未接入，页面没有将人工数值升级成可执行资格的按钮；未提供合成fixture的Owner实例保持缺项。

失败入口：不选快照/分仓、REFERENCE_ONLY、TEST_DEFAULT、未批准 Policy、缺公式/波动率/流动性/风险预算/相关性/价格、FX缺失、证据关系损坏或到期，必须显示具名UNKNOWN/BLOCKED而非默认0或PASS；Veto不生成增仓数量，允许确定性减仓测算。所有结果保留simulation_only=true、execution_allowed=false、auto_trade=false，没有可审批Decision或自动订单。


角色失败或有效结构化INSUFFICIENT_DATA也必须显示具名UNKNOWN/BLOCKED，没有建议数量和标准Risk/Sizing记录；有效末次修复不被误判失败。新8项真实PG正常/失败/边界已通过，最终全量与真实API/DB/Worker/Chrome证据见工作项。[PR #36](https://github.com/zmd6s6/JZ-Investment-OS/pull/36)的a67b61c已实际合入Release01f439f，精确HEAD CI全绿；root独立复核按实际先后另记，不追认root合入前Gate或合并。MVP-206已由PR39经独立Gate实际合入Release4b3995f，显式后置桥接见下节；Owner实例部署/产品接受PENDING，不宣称Product Done、完整P6或Owner接受。

## MVP-206 显式分析到人工审阅（已集成，Owner PENDING）

入口`/analysis`：完整合成资格资料和具体Strategy必须在原Run冻结时已经存在。选择组合、标的、模型、合格数值快照/分仓及含资格facts的Evidence，明确同意研究后发起，等待真实Worker终态。新的“准备人工审阅决策”区单独选择固定资格、填写操作者并勾选仅准备记录，点击确认；不接受UI任意数量或投资阈值，也不追加模型调用。

成功应展示标准Decision编号和“前往决策中心审阅”，精确打开原编号。审阅完整Evidence/Thesis/委员会/风险/Policy/Strategy/Sizing后填写人工归属与理由、勾选本人动作，再明确批准或拒绝。批准后可撤销未成交批准，刷新仍显示不可变历史。准备不等于批准、批准不等于成交，零订单/auto_trade=false。当前真实合格配置不存在，正常链只在独立完整SYNTHETIC_FIXTURE环境证明，不向Owner实例种数据/激活策略。

失败：未冻结资格Evidence、未批准Strategy/Policy、角色失败/高严重风险、Hash/Prompt不符、过期、Risk Veto增仓、pending容量改变或实际scheduled_shadow origin都具名阻断；保存BLOCKED尝试而不保留候选标准Decision。超时显示结果未知、保留输入与请求UUID，用户明确刷新核对，不自动重试。TTL精确到期不可批准。合成API/PG/Worker/Chrome精确当前Decision3/3（22.9s）已演示approve→revoke、reject和缺原Evidence阻断；15项真实PG/前端证据见工作项。完整Python813项/87.89%、最终前端109项、迁移与Domain门槛已通过；[PR #39](https://github.com/zmd6s6/JZ-Investment-OS/pull/39)已于2026-11-05经root独立Gate6647991606实际合入Release4b3995fad5844082e2973daa25a8cdb2d2718d7e（源ff9d5eb），不宣称Product Done、Owner接受或部署。

## MVP-403 每日状态与明确授权Shadow（Owner PENDING）

本节仅随PR #37真正合入Release后的功能生效，不代表实现者自签Gate、Owner部署或Checkpoint C接受。入口/calendar「每日检查与影子研究」：选择组合全部持仓及明确观察项、已导入日历/完整覆盖、资料与报价来源、每日频率/期限/暂停方式；Shadow逐角色选择模型并明确费用/Token边界。预览真实成员、端点/价格与预算后另行确认保存为暂停，再核保存快照独立启用。

到期后刷新「真实每日任务记录」和六节日报；TaskRun SUCCEEDED仅代表本地事务，不等于模型成功。无合格数值快照时Shadow UNKNOWN/BLOCKED与DEGRADED须诚实显示；新机会/审批/可执行Action缺失显示NOT_PROVIDED。报告保留业务收盘、实际知识时点与记录时间；当前账本不是历史收盘快照。暂停/永久撤销经版本确认，已出站可能收费，确认后后续调用阻断；未知队列/费用不自动重试，旧业务日只本地报告。

失败入口：越界日历覆盖、来源/范围/模型价格/预算变化、缺授权或到期均出现具名阻断并保留输入；不新增授权/Analysis，不静默扩范围、换源或填0。data_profile_ids固定为空的当前外部资料成本限制在页面可见。隔离合成API18120/PG15446/生产Worker/Chrome及真实PG双会话证明只算工程/接线/可见路径，不是个人投资数据、真实模型许可或本人产品接受。最新实际验证和NOT VERIFIED见本项工作记录；完整P8、404/501与Owner状态不提前完成。



## MVP-404 独立授权的月度组合复核候选（Owner PENDING）

入口 `/calendar` 的「月度组合复核」：选择组合及已导入市场日历，填写完整自然月、授权起止、保留天数及明确本地报价与资料来源；核对独立月度范围与零外部费用，预览后单独确认保存为暂停，再核对保存快照并显式启用。月度许可不从每日许可推断。实际Worker在完整自然月结束后读取现有本地记录，展示持仓Core/Tactical、变化、证据日期、Thesis/Risk/Decision引用及未知缺口；账本读取时刻和月末业务时刻分别标示。刷新后打开同一冻结快照，授权可暂停或永久撤销。

失败入口：不完整月份、日历覆盖/范围漂移、授权过期或撤销、报告引用损坏均具名阻断，不静默扩权或生成新分析/订单。隔离合成PG/API/真实Worker/Chrome已实际演示成功、刷新与撤销，以及部分月拒绝并保留输入；这不是Owner部署或本人验收。缺失宏观、相关性、资本效率及重新进入判断明确未知；不声称已经完成完整PRODUCT-08或Checkpoint C。更多证据及限制见 `docs/agent/work-items/MVP-404.md`。

MVP-404独立Review发现并修复超过50项配置导致后续任务饥饿：0025持久扫描位置跨Worker/重启前进，配置、任务和报告历史可分页；复核状态fixed-awaiting-review，尚非最终Gate。具体测试和已知offset并发刷新限制见 `docs/agent/work-items/MVP-404.md`。

## MVP-402 全成员来源声明筛选 v2（本 PR 候选，Owner PENDING）

仅在本 PR 实际经独立 Gate 合入后生效：在 `/opportunities` 保存或读取声明来源快照，填写本地报价/年报来源与本次研究条件，点击「完整筛选所选快照（v2）」。所有冻结成员均经确定性规则检查并一次全局排序，最多20个候选；页面列出全部成员的通过/排除/缺项、Evidence、来源四时间与 hash。刷新历史再读取原运行，不重新计算。未知响应保留相同请求，先刷新历史再明确重试；时点早于来源入库、身份漂移或数据异常失败关闭。旧v1仍拒绝201项；v2不改变旧运行。

来源仍 SOURCE_DECLARED/UNVERIFIED，真实 market universe 及真实财务/Timing 来源未提供；不是全市场已验证或投资建议。筛选零网络/模型/费用、不启用交易；v2候选原版本不能直接深研；下述逐候选接线须本次PR实际合入后生效。合成 API/DB/UI 工程验证不代表 Owner 部署或验收，402与完整P8仍 PARTIAL、501 BLOCKED、Owner PENDING。完整证据以本项工作记录及最终PR/CI为准。

### MVP-404 实际合并事实澄清

此前fixed-awaiting-review仅描述历史修复状态；PR #40 最终 [独立 Gate](https://github.com/zmd6s6/JZ-Investment-OS/pull/40#issuecomment-6665931499) 后已实际合入 Release 1cd5801bdfeca69a9e7c3f540e6b0ef74ad41c7c。Owner部署与产品接受仍 PENDING。

## MVP-402 完整来源候选显式研究（候选）

本次PR独立Gate并实际合入后，/opportunities完整v2结果中每个有界候选可点击“明确研究此完整筛选候选”，页面定位到单候选研究面板。明确选择组合与模型、核原Evidence及费用/资料出站说明后单独同意再发起；未同意时按钮禁用，不会因筛选或展开面板调用模型。研究以新当前时点经原Analysis证据、模型、预算与Risk/Sizing闸门，完整来源声明不是金融资格证据。正常显示真实Worker进度及Shadow/缺项；无效角色失败仍保留原关联，刷新不重试。未知回执先只读刷新，原请求需要重新同意后明确重试。schema_version2.0固定原v2 run及候选，v1保持原读取。真实来源/费用未授权，Owner部署/接受PENDING、402/P8 PARTIAL、501BLOCKED；工程证据见工作项。


## MVP-402 完整来源本地周筛选 v2（本PR候选）

入口 `/opportunities`：先在完整来源v2结果或冻结历史中核对全部成员/条件，进入“完整来源 · 每周本地确定性筛选 v2”，明确周配置名称、市场、完整周一至周日范围及已导入日历。分别声明全部会话完整与仅本地零外网/模型/费用后保存；应显示schema2.0新版本暂停。另行确认保存范围后启用，周结束由真实Worker以最后明确收盘时点完整扫描最多1000项、一次全局最多20候选；刷新可读TaskRun/缺项、原来源与本周不可变完整产物。原v1保持200边界，两个协议不互换模板或启停。

失败：不完整周/未勾确认不保存；来源晚于业务时点、日历改变/暂停/版本冲突失败关闭，无部分产物；资料缺失显示DEGRADED与全部逐层缺项，明确闭市周SKIPPED_CLOSED。未知写回先刷新，以同内容同request_id明确核对；不自动外联或研究候选。历史链接可读取原v2完整运行，390宽可操作。新旧真实PG29通过、独立合成18134/API/PG/生产Worker/Edge1通过32.9秒（含实际未授权401）均属工程/接线证据；最终CI与独立Gate待核，实际合入后生效，Owner部署和本人验收PENDING，402/P8 PARTIAL及501BLOCKED不变。
