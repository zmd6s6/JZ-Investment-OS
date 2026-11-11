import { useEffect, useRef, useState } from "react";
import { Panel } from "./ProductChrome";
import { apiFetch, readApiError } from "./writeApi";
import "./daily-runtime.css";
type Position = {
    instrument_id: string;
    symbol: string;
    name: string;
};
type Book = {
    portfolio_id: string;
    name: string;
    positions: Position[];
};
type Calendar = {
    venue: string;
    import_id: string;
    source_name: string;
    source_version: string;
};
type Prepared = {
    command: Record<string, unknown>;
    content_hash: string;
    calendar_source: string;
    calendar_version: string;
    calendar_hash: string;
    members: Position[];
};
type Config = {
    schedule_id: string;
    revision_id: string;
    version: number;
    enabled: boolean;
    revoked: boolean;
    blocker: string | null;
    prepared: Prepared;
};
type History = {
    report_id: string;
    schedule_id: string;
    period_start: string;
    period_end: string;
    recorded_at: string;
    usable_until: string;
    usable: boolean;
    content_hash: string;
};
type Task = {
    task_run_id: string;
    schedule_id: string;
    status: string;
    attempt: number;
    error_code: string | null;
};
type Reference = {
    kind: string;
    record_id: string;
    status: string;
    recorded_at: string;
    content_hash: string;
    evidence_ids: string[];
    unknowns: string[];
};
type Report = History & {
    phase: string;
    business_as_of: string | null;
    knowledge_as_of: string;
    baseline_status: string;
    baseline_report_id: string | null;
    unknowns: string[];
    recovery: string[];
    holdings: {
        instrument_id: string;
        symbol: string;
        core_quantity: string;
        tactical_quantity: string;
        core_change: string | null;
        tactical_change: string | null;
        quote_status: string;
        reentry_assessment: string;
        references: Reference[];
        unknowns: string[];
    }[];
    valuation: {
        status: string;
        nav: string | null;
        cash: string;
        cash_weight: string | null;
        gross_exposure: string | null;
    } | null;
    quotes: {
        instrument_id: string;
        source_name: string;
        as_of: string;
        status: string;
        quote: {
            price: string;
        } | null;
        provenance: {
            evidence_id: string;
            expires_at: string;
        } | null;
    }[];
    local_inputs: {
        portfolio: {
            positions: {
                instrument_id: string;
                core_average_cost: string;
                tactical_average_cost: string;
                core_reason: string;
                tactical_reason: string;
            }[];
            cash_balance: string;
            read_at: string;
            time_semantics: string;
        };
        evidence: {
            evidence_id: string;
            source_name: string;
            observed_at: string;
            effective_at: string;
            available_at: string;
            ingested_at: string;
            expires_at: string | null;
            content_hash: string;
        }[];
    } | null;
    evidence_diff: {
        added_ids: string[];
        removed_ids: string[];
        excluded: Record<string, string>;
    } | null;
};
async function read<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await apiFetch(path, init);
    if (!response.ok)
        throw new Error(await readApiError(response));
    return response.json() as Promise<T>;
}
const post = (value: unknown) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) });
const missing = (value: string | null | undefined) => value == null ? "未提供" : /^-?\d+\.\d+$/.test(value) ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
const labels: Record<string, string> = {
    DEGRADED: "有缺口的本地复核", CLOSED_MONTH_SKIPPED: "声明完整但无会话, 已跳过",
    FIRST_RUN_NO_BASELINE: "首次运行, 无可比基线", COMPARABLE_BASELINE: "同授权既往捕获快照",
    REFERENCE_ONLY: "仅供参考, 非交易级", AVAILABLE: "参考报价可用",
    MACRO_AND_INDUSTRY_PANORAMA_NOT_PROVIDED: "宏观与行业全景未提供",
    CORRELATION_AND_CAPITAL_EFFICIENCY_NOT_PROVIDED: "相关性与资本效率未提供",
    NO_NEW_INVESTMENT_JUDGMENT_OR_APPROVAL: "没有产生新的投资判断或批准",
    CURRENT_BOOK_NOT_HISTORICAL_MONTH_END_SNAPSHOT: "当前账本不等于历史月末快照",
    REENTRY_WILLINGNESS_NOT_ASSESSED: "今天是否愿意重新进入尚未评估",
    ANCHORING_AND_SUNK_COST_NOT_ASSESSED: "锚定与沉没成本偏差尚未评估",
    STYLE_DRIFT_AND_BUCKET_BALANCE_REQUIRE_EXPLICIT_POLICY_REVIEW: "风格漂移与分仓平衡需要明确政策复核",
    NO_COMPARABLE_POSITION_BASELINE: "没有可比持仓基线, 不填零变化",
    THESIS_NOT_PROVIDED: "未提供论点", RISK_NOT_PROVIDED: "未提供风险评估", DECISION_NOT_PROVIDED: "未提供决策",
    HISTORICAL_REFERENCE_NOT_REVALIDATED_OR_CURRENT_APPROVAL: "历史引用未重新评估, 不代表当前批准",
    REFERENCE_EVIDENCE_MISSING_EXPIRED_OR_OUTSIDE_EXPLICIT_SOURCE: "引用资料缺失/过期或不在本次明确来源中",
    HISTORICAL_RISK_EXPIRED: "历史风险评估已过期", HISTORICAL_NO_CURRENT_RISK_CLEARANCE: "历史风险记录不代表当前通过",
    VETO_RECORDED: "记录有风险否决", STATUS_OBSERVED_AT_KNOWLEDGE_TIME_NOT_HISTORICAL_MONTH_END: "知识时点观察的状态, 非历史月末状态",
    EXPLICIT_COMPLETE_CLOSED_MONTH_NO_RESEARCH: "声明完整的该月没有提供会话, 不推断交易日也不发起研究",
};
const explain = (code: string) => labels[code] ?? code;
export function MonthlyReviewPanel() {
    const [books, setBooks] = useState<Book[]>([]), [calendars, setCalendars] = useState<Calendar[]>([]);
    const [configs, setConfigs] = useState<Config[]>([]), [history, setHistory] = useState<History[]>([]), [tasks, setTasks] = useState<Task[]>([]);
    const [configOffset, setConfigOffset] = useState(0), [historyOffset, setHistoryOffset] = useState(0), [taskOffset, setTaskOffset] = useState(0);
    const [moreConfigs, setMoreConfigs] = useState(false), [moreHistory, setMoreHistory] = useState(false), [moreTasks, setMoreTasks] = useState(false);
    const [healthy, setHealthy] = useState(false), [working, setWorking] = useState(false), [error, setError] = useState<string | null>(null), [message, setMessage] = useState<string | null>(null);
    const [book, setBook] = useState(""), [calendar, setCalendar] = useState(""), [name, setName] = useState("");
    const [start, setStart] = useState(""), [end, setEnd] = useState(""), [validFrom, setValidFrom] = useState(""), [validUntil, setValidUntil] = useState("");
    const [source, setSource] = useState(""), [sources, setSources] = useState(""), [retention, setRetention] = useState("");
    const [ack, setAck] = useState(false), [confirmed, setConfirmed] = useState(false), [preview, setPreview] = useState<Prepared | null>(null), [modeConfirm, setModeConfirm] = useState<string[]>([]);
    const [report, setReport] = useState<Report | null>(null);
    const busy = useRef(false), reads = useRef(0), modeRequests = useRef(new Map<string, string>()), reportRead = useRef(0);
    const currentBook = books.find(value => value.portfolio_id === book), currentCalendar = calendars.find(value => value.import_id === calendar);
    async function load(signal?: AbortSignal) {
        const id = ++reads.current;
        setHealthy(false);
        setModeConfirm([]);
        setConfigs([]);
        setHistory([]);
        setTasks([]);
        setMoreConfigs(false); setMoreHistory(false); setMoreTasks(false);
        setReport(null);
        ++reportRead.current;
        const [b, c, conf, h, t] = await Promise.all([
            read<Book[]>("/api/v1/portfolios", { signal }), read<{
                configurations: Calendar[];
            }>("/api/v1/calendar", { signal }),
            read<Config[]>("/api/v1/runtime/monthly", { signal }), read<History[]>("/api/v1/runtime/monthly/history", { signal }), read<Task[]>("/api/v1/runtime/monthly/runs", { signal }),
        ]);
        if (id !== reads.current || signal?.aborted)
            return;
        if (![b, c.configurations, conf, h, t].every(Array.isArray))
            throw new Error("月度响应格式不符, 当前状态未确认。");
        setBooks(b);
        setCalendars(c.configurations.filter(value => ["SSE", "SZSE"].includes(value.venue)));
        setConfigs(conf);
        setHistory(h);
        setTasks(t);
        setConfigOffset(conf.length); setHistoryOffset(h.length); setTaskOffset(t.length);
        setMoreConfigs(conf.length === 50); setMoreHistory(h.length === 60); setMoreTasks(t.length === 60);
        setHealthy(true);
    }
    useEffect(() => {
        const controller = new AbortController();
        void load(controller.signal).catch(e => {
            if (!controller.signal.aborted)
                setError(String(e));
        });
        return () => { controller.abort(); ++reads.current; ++reportRead.current; };
    }, []);
    async function act(operation: () => Promise<void>, readOnly = false) {
        if (busy.current)
            return;
        busy.current = true;
        setWorking(true);
        setError(null);
        setMessage(null);
        try {
            await operation();
        }
        catch (e) {
            setError(readOnly ? `${String(e)} 加载下一页失败，已有内容保留；可重试或刷新。` : `${String(e)} 写入结果未知时请先只读刷新核对, 保留原输入与请求身份后再明确重试; 不自动重新提交。`);
        }
        finally {
            busy.current = false;
            setWorking(false);
        }
    }
    async function loadMore(kind: "configs" | "history" | "tasks") {
        await act(async () => {
            if (kind === "configs") {
                const page = await read<Config[]>(`/api/v1/runtime/monthly?offset=${configOffset}`);
                setConfigs(old => [...old, ...page.filter(item => !old.some(value => value.schedule_id === item.schedule_id))]);
                setConfigOffset(configOffset + page.length); setMoreConfigs(page.length === 50);
            } else if (kind === "history") {
                const page = await read<History[]>(`/api/v1/runtime/monthly/history?offset=${historyOffset}`);
                setHistory(old => [...old, ...page.filter(item => !old.some(value => value.report_id === item.report_id))]);
                setHistoryOffset(historyOffset + page.length); setMoreHistory(page.length === 60);
            } else {
                const page = await read<Task[]>(`/api/v1/runtime/monthly/runs?offset=${taskOffset}`);
                setTasks(old => [...old, ...page.filter(item => !old.some(value => value.task_run_id === item.task_run_id))]);
                setTaskOffset(taskOffset + page.length); setMoreTasks(page.length === 60);
            }
            setMessage("已加载下一页；若记录同时变化，请刷新后重新浏览。");
        }, true);
    }
    async function prepare() {
        setPreview(null);
        setConfirmed(false);
        await act(async () => {
            if (!currentBook || !currentCalendar || !ack || !currentBook.positions.length)
                throw new Error("请选择非空组合及日历, 明确完整自然月和独立月频许可。");
            const firstDate = new Date(`${start}T00:00:00Z`), lastDate = new Date(`${end}T00:00:00Z`);
            const lastDay = new Date(Date.UTC(lastDate.getUTCFullYear(), lastDate.getUTCMonth() + 1, 0)).getUTCDate();
            if (firstDate.getUTCDate() !== 1 || lastDate.getUTCDate() !== lastDay || lastDate < firstDate || (lastDate.getTime() - firstDate.getTime()) / 86400000 > 365)
                throw new Error("必须明确完整自然月: 首月1日至末月最后一天, 覆盖最多366日。");
            if (!name.trim() || !source.trim() || !validFrom || !validUntil || new Date(validUntil) <= new Date(validFrom) || !Number.isInteger(Number(retention)) || Number(retention) < 1 || Number(retention) > 3650)
                throw new Error("请填写任务/来源、有效起止和1至3650天报告使用期, 截止须晚于开始。");
            const command = { request_id: crypto.randomUUID(), schedule_id: crypto.randomUUID(), expected_version: 0, name, mode: "LOCAL_MONTHLY_REVIEW", frequency: "MONTHLY_AFTER_COMPLETE_CALENDAR_MONTH", market: currentCalendar.venue, portfolio_id: book, portfolio_instrument_ids: currentBook.positions.map(value => value.instrument_id), calendar_import_id: calendar, coverage_start: start, coverage_end: end, quote_source_name: source, evidence_source_names: sources.split("\n").map(value => value.trim()).filter(Boolean), valid_from: new Date(validFrom).toISOString(), valid_until: new Date(validUntil).toISOString(), retention_days: Number(retention), pause_method: "MONTHLY_UI_PAUSE_OR_REVOKE", missed_run_policy: "LOCAL_CURRENT_KNOWLEDGE_EXPLICIT_PERIOD", complete_calendar_acknowledgement: true, monthly_frequency_acknowledgement: true, scope_acknowledgement: true, local_only_acknowledgement: true, model_profile_ids: [], data_profile_ids: [], limits: { currency: "NONE", task_tokens: 0, day_tokens: 0, task_cost: "0", day_cost: "0" } };
            setPreview(await read<Prepared>("/api/v1/runtime/monthly/preview", post(command)));
        });
    }
    async function save() {
        if (!preview || !confirmed)
            return;
        await act(async () => { await read<Config>("/api/v1/runtime/monthly", post({ command: preview.command, preview_hash: preview.content_hash })); setPreview(null); setConfirmed(false); await load(); setMessage("月度授权已保存, 默认暂停。核对保存范围后另行启用。"); });
    }
    async function mode(config: Config, action: string) {
        const key = `${config.schedule_id}:${config.version}:${action}`;
        if (!modeRequests.current.has(key))
            modeRequests.current.set(key, crypto.randomUUID());
        await act(async () => { await read<Config>(`/api/v1/runtime/monthly/${config.schedule_id}/mode`, post({ request_id: modeRequests.current.get(key), expected_version: config.version, action, confirmed: true })); await load(); setMessage("月度命令已确认并刷新当前状态。暂停确认后旧任务不能再提交; 永久撤销不可恢复。"); });
    }
    async function replay(id: string) {
        const request = ++reportRead.current;
        setReport(null);
        await act(async () => {
            const value = await read<Report>(`/api/v1/runtime/monthly/reports/${id}/replay`);
            if (request === reportRead.current) {
                setReport(value);
                setMessage("已核对原报告并只读重放冻结快照, 未重新取数或发起研究。");
            }
        });
    }
    return <section aria-label="月度组合复核"><Panel title="月度组合复核" description="独立月频许可, 默认暂停。当前仅本地已存资料, 零网络/模型/费用; 不生成投资动作或批准。"><div className="daily-runtime">
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    <button disabled={working} onClick={() => void act(() => load())}>刷新月度状态与报告</button>
    {!healthy && <p>月度状态未确认, 写操作不可用。读取失败不会显示旧配置为当前成功。</p>}
    <form onSubmit={e => { e.preventDefault(); void prepare(); }} onChange={e => {
            setPreview(null);
            setConfirmed(false);
            if (!(e.target instanceof HTMLInputElement && e.target.type === "checkbox"))
                setAck(false);
        }}><fieldset disabled={working || !healthy}><legend>建立新的独立月度授权</legend>
      <label>月度任务名称<input value={name} onChange={e => setName(e.target.value)} required/></label>
      <label>月度组合<select aria-label="月度组合" value={book} onChange={e => setBook(e.target.value)} required><option value="">请选择组合</option>{books.map(value => <option key={value.portfolio_id} value={value.portfolio_id}>{value.name}</option>)}</select></label>
      <p>冻结组合全部持仓: {currentBook?.positions.map(value => `${value.name} ${value.symbol}`).join("、") || "尚未选择非空组合"}。新成员或身份变化须重新授权, 不自动扩大范围。</p>
      <label>月度显式日历<select aria-label="月度显式日历" value={calendar} onChange={e => setCalendar(e.target.value)} required><option value="">请选择已导入日历</option>{calendars.map(value => <option key={value.import_id} value={value.import_id}>{value.venue} · {value.source_name} {value.source_version}</option>)}</select></label>
      <label>首月起日（必须1日）<input type="date" value={start} onChange={e => setStart(e.target.value)} required/></label>
      <label>末月末日（必须月末）<input type="date" value={end} onChange={e => setEnd(e.target.value)} required/></label>
      <label>月度授权开始（浏览器本地时区）<input type="datetime-local" value={validFrom} onChange={e => setValidFrom(e.target.value)} required/></label>
      <label>月度授权截止<input type="datetime-local" value={validUntil} onChange={e => setValidUntil(e.target.value)} required/></label>
      <label>月报使用期限（天）<input type="number" min="1" max="3650" value={retention} onChange={e => setRetention(e.target.value)} required/></label>
      <label>月度本地报价来源<input value={source} onChange={e => setSource(e.target.value)} required/></label>
      <label>月度允许本地资料来源（每行一个）<textarea value={sources} onChange={e => setSources(e.target.value)}/></label>
      <p>每个完整自然月结束后按最后显式会话标记业务时间; 已结束月只捕获当前可知账本, 不伪造历史月末持仓。无会话明确闭市跳过。无模型/资料档案, 单任务与UTC日预算均NONE/0。Daily启用不授予月频许可。</p>
      <label><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} required/>我独立确认完整月覆盖、全部组合与来源、月频/期限/暂停方式, 仅本地零费用复核。</label>
      <button type="submit">预览完整月度授权（不保存）</button>
    </fieldset></form>
    {preview && <section aria-label="月度授权预览"><h3>完整月度授权预览</h3><p>组合全部: {preview.members.map(value => `${value.name} ${value.symbol}`).join("、")}</p><p>日历 {preview.calendar_source} / {preview.calendar_version} · {preview.calendar_hash}</p><p>{String(preview.command.coverage_start)} 至 {String(preview.command.coverage_end)} · 完整月结束后一次 · 报告使用{String(preview.command.retention_days)}天</p><p>本地报价 {String(preview.command.quote_source_name)} · 本地资料 {String(preview.command.evidence_source_names)} · 授权 {String(preview.command.valid_from)} 至 {String(preview.command.valid_until)}</p><p>固定LOCAL_MONTHLY_REVIEW, 模型/资料档案为空, 费用与Token=0。暂停/永久撤销在此页面。</p><label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/>已核对本次全部月度范围与零成本, 明确保存为暂停。</label><button disabled={working || !healthy || !confirmed} onClick={() => void save()}>保存月度授权为暂停</button></section>}
    <h3>已保存月度任务</h3><p>每页最多50条；记录变化时请刷新后重新浏览。</p>{configs.map(value => <article key={value.schedule_id}><h4>{String(value.prepared.command.name)} · {value.revoked ? "已永久撤销" : value.enabled ? "已启用" : "已暂停"}</h4><p>版本{value.version} · {value.blocker ?? "等待完整自然月结束及Worker轮询"}</p><p>完整月范围{String(value.prepared.command.coverage_start)} 至{String(value.prepared.command.coverage_end)} · {value.prepared.calendar_source} / {value.prepared.calendar_version}</p><p>组合全部{value.prepared.members.map(member => `${member.name} ${member.symbol}`).join("、")} · {String(value.prepared.command.quote_source_name)} · 本地来源{String(value.prepared.command.evidence_source_names)}</p><label><input type="checkbox" checked={modeConfirm.includes(value.schedule_id)} onChange={e => setModeConfirm(old => e.target.checked ? [...old, value.schedule_id] : old.filter(id => id !== value.schedule_id))}/>我已核对此保存月度授权, 明确确认本次启停或永久撤销。</label>{["ENABLE", "PAUSE", "REVOKE"].map((action, index) => <button key={action} disabled={working || !healthy || value.revoked || !modeConfirm.includes(value.schedule_id)} onClick={() => void mode(value, action)}>{["启用月度复核", "暂停月度复核", "永久撤销月度授权"][index]}</button>)}</article>)}
    {moreConfigs && <button disabled={working || !healthy} onClick={() => void loadMore("configs")}>加载更多月度授权</button>}
    <h3>真实月度任务记录</h3>{tasks.length ? tasks.map(task => <p key={task.task_run_id} id={`monthly_task-${task.task_run_id}`} ref={element => { if (element && window.location.hash === `#monthly_task-${task.task_run_id}`) element.scrollIntoView?.(); }}>任务{task.task_run_id} · {task.status} · 尝试{task.attempt} · {task.error_code ?? "无记录错误"}{task.status === "FAILED" && task.attempt >= 3 ? " · 本授权月份重试已耗尽, 修复后保存新暂停授权再确认启用" : ""}</p>) : <p>没有记录不代表Worker健康; 可能尚未到期、暂停或未运行。失败最多三次本地重试, 来源修复须新暂停版本再确认启用。</p>}
    {moreTasks && <button disabled={working || !healthy} onClick={() => void loadMore("tasks")}>加载更多月度任务记录</button>}
    <h3>月报历史与只读重放</h3>{history.map(value => <article key={value.report_id}><h4>{value.period_start} 至 {value.period_end}</h4><p>记录{value.recorded_at} · 正文有效至{value.usable_until} · {value.usable ? "可只读重放" : "已过期, 仅保留审计历史"}</p><p>报告{value.report_id} · hash {value.content_hash}</p><button disabled={working} onClick={() => void replay(value.report_id)}>打开月报冻结快照</button></article>)}
    {moreHistory && <button disabled={working || !healthy} onClick={() => void loadMore("history")}>加载更多月报历史</button>}
    {report && <section aria-label="月报冻结快照"><h3>月度组合复核报告 · {explain(report.phase)}</h3><p>期间{report.period_start} 至{report.period_end} · 业务会话{missing(report.business_as_of)} · 知识截止{report.knowledge_as_of} · 记录{report.recorded_at}</p><p>基线{explain(report.baseline_status)} · 原报告{missing(report.baseline_report_id)}。首次没有基线不填零变化; 变化仅比较实际捕获快照, 不是历史月末收益。</p><h4>参考估值与现金</h4><p>状态{report.valuation ? explain(report.valuation.status) : "未提供"} · 参考NAV{missing(report.valuation?.nav)} · 现金{missing(report.valuation?.cash)} · 现金比例{missing(report.valuation?.cash_weight)} · 总暴露{missing(report.valuation?.gross_exposure)}</p><p>账本实际读取{missing(report.local_inputs?.portfolio.read_at)} · {report.local_inputs?.portfolio.time_semantics ?? "无会话未取数"}。人工参考估值非交易级, 不能推导Risk PASS。</p><h4>持仓、变化与历史风险</h4>{report.holdings.map(holding => <article key={holding.instrument_id}><h5>{holding.symbol}</h5><p>Core {missing(holding.core_quantity)} / Tactical {missing(holding.tactical_quantity)} · Core变化{missing(holding.core_change)} / Tactical变化{missing(holding.tactical_change)} · 报价{explain(holding.quote_status)}</p>{report.local_inputs?.portfolio.positions.filter(position => position.instrument_id === holding.instrument_id).map(position => <p key={position.instrument_id}>Core平均成本{missing(position.core_average_cost)} / 理由{position.core_reason || "未记录"} · Tactical平均成本{missing(position.tactical_average_cost)} / 理由{position.tactical_reason || "未记录"}。成本不作为参考行情。</p>)}{report.quotes?.filter(quote => quote.instrument_id === holding.instrument_id).map(quote => <p key={quote.instrument_id}>参考价格{missing(quote.quote?.price)} · 来源{quote.source_name} · 知识截止{quote.as_of} · Evidence {quote.provenance?.evidence_id ?? "未提供"} · 到期{missing(quote.provenance?.expires_at)}。仅人工参考, 未独立核实。</p>)}<p>若今天未持有是否重新进入: 未提供判断。当前不自动交易或推断再平衡阈值。</p>{holding.references.map(ref => <p key={`${ref.kind}:${ref.record_id}`}>{ref.kind}历史记录 {explain(ref.status)} · {ref.recorded_at} · {ref.record_id} · hash{ref.content_hash} · Evidence {ref.evidence_ids.join("、") || "无范围内有效引用"} · {ref.unknowns.map(explain).join("; ")}{ref.kind === "ANALYSIS" && <a href={`/analysis?run_id=${ref.record_id}`}>查看分析依据</a>}{ref.kind === "DECISION" && <a href={`/decisions?decision_id=${ref.record_id}`}>只读定位决策</a>}</p>)}<p>持仓未知项: {holding.unknowns.map(explain).join("; ")}</p></article>)}<h4>资料变化与日期来源</h4><p>新增Evidence{report.evidence_diff?.added_ids.join("、") || "无"} · 移出有效集合{report.evidence_diff?.removed_ids.join("、") || "无"}（不代表删除历史）</p>{report.local_inputs?.evidence.map(evidence => <p key={evidence.evidence_id}>{evidence.source_name} · {evidence.evidence_id} · 观察 {evidence.observed_at} / 生效 {evidence.effective_at} / 可得 {evidence.available_at} / 入库 {evidence.ingested_at} / 到期 {missing(evidence.expires_at)} · hash {evidence.content_hash}</p>)}<h4>未知与恢复</h4><p>{report.unknowns.map(explain).join("; ")}</p>{report.recovery.map(value => <p key={value}>{value}</p>)}<p>SIMULATION / NO AUTO TRADE · 原历史引用不等于当前风险通过或批准; 报告不创建新的投资动作。</p></section>}
  </div></Panel></section>;
}
