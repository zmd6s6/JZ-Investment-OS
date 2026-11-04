import { useEffect, useRef, useState } from "react";
import { Panel } from "./ProductChrome";
import { apiFetch, readApiError } from "./writeApi";
type Hit = {
    instrument_id: string;
    symbol: string;
    name: string;
    market?: string;
};
type Book = {
    portfolio_id: string;
    name: string;
    positions: Hit[];
};
type Calendar = {
    venue: string;
    import_id: string;
    source_name: string;
    source_version: string;
    first_business_date: string;
    last_business_date: string;
};
type Model = {
    profile_id: string;
    name: string;
    model_name: string;
    pricing_configured: boolean;
};
type Prepared = {
    input_hash: string;
    calendar_source: string;
    calendar_version: string;
    calendar_hash: string;
    members: (Hit & {
        in_portfolio: boolean;
        in_watchlist: boolean;
    })[];
    models: Record<string, {
        name: string;
        model_name: string;
    }>;
    model_pricing: Record<string, {
        base_url: string;
        version: string;
        currency: string;
        input_token_price: string;
        output_token_price: string;
        effective_at: string;
    }>;
    budget_snapshot: {
        version: string;
        limits: Record<string, string | number>;
    } | null;
    command: Record<string, unknown>;
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
type Section = {
    availability: string;
    messages: string[];
    analysis_run_ids: string[];
};
type Task = {
    task_run_id: string;
    schedule_id: string;
    status: string;
    attempt: number;
    error_code: string | null;
    started_at: string;
    finished_at: string | null;
};
type Report = {
    local_inputs: {
        portfolio: {
            portfolio_id: string;
        };
    };
    report_id: string;
    recorded_at: string;
    business_as_of: string;
    as_of: string;
    phase: string;
    action_required: Section;
    hold_watch: Section;
    new_opportunity: Section;
    risk_veto: Section;
    approvals: Section;
    data_job_degraded: Section;
};
const roleNames: Record<string, string> = { MACRO: "宏观", INDUSTRY: "行业", FUNDAMENTAL: "基本面", MARKET_QUANT: "市场与量化", EVENT: "事件", DEVILS_ADVOCATE: "反方", PORTFOLIO: "组合经理", RISK: "风险", CIO: "投资负责人" };
const limitNames: Record<string, string> = { currency: "计费币种", task_tokens: "单任务Token上限", day_tokens: "UTC日Token上限", task_cost: "单任务费用上限", day_cost: "UTC日费用上限" };
const sectionNames = { action_required: "需要处理", hold_watch: "持有 / 观察", new_opportunity: "新机会", risk_veto: "风险否决", approvals: "待处理审批", data_job_degraded: "数据 / 任务异常" };
async function read<T>(url: string, init?: RequestInit): Promise<T> { const response = await apiFetch(url, { ...init, signal: init?.signal ?? AbortSignal.timeout(15000) }); if (!response.ok)
    throw new Error(await readApiError(response)); return response.json() as Promise<T>; }
const post = (body: unknown) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export function DailyRuntimePanel() {
    const [healthy, setHealthy] = useState(false);
    const [tasks, setTasks] = useState<Task[]>([]);
    const [books, setBooks] = useState<Book[]>([]), [watches, setWatches] = useState<Hit[]>([]), [calendars, setCalendars] = useState<Calendar[]>([]), [configs, setConfigs] = useState<Config[]>([]), [reports, setReports] = useState<Report[]>([]);
    const [book, setBook] = useState(""), [calendar, setCalendar] = useState(""), [selected, setSelected] = useState<string[]>([]), [mode, setMode] = useState("LOCAL_STATUS_ONLY"), [name, setName] = useState(""), [source, setSource] = useState(""), [sources, setSources] = useState(""), [start, setStart] = useState(""), [end, setEnd] = useState(""), [validFrom, setValidFrom] = useState(""), [validUntil, setValidUntil] = useState(""), [retention, setRetention] = useState("");
    const [roles, setRoles] = useState<string[]>([]), [models, setModels] = useState<Model[]>([]), [chosen, setChosen] = useState<Record<string, string>>({});
    const [limits, setLimits] = useState({ currency: "", task_tokens: "", day_tokens: "", task_cost: "", day_cost: "" });
    const [ack, setAck] = useState(false), [costAck, setCostAck] = useState(false), [confirmed, setConfirmed] = useState(false), [preview, setPreview] = useState<Prepared | null>(null), [error, setError] = useState<string | null>(null), [message, setMessage] = useState<string | null>(null), [working, setWorking] = useState(false);
    const [modeConfirm, setModeConfirm] = useState<string[]>([]);
    const busy = useRef(false), request = useRef<{
        key: string;
        body: Record<string, unknown>;
    } | null>(null), modeRequests = useRef(new Map<string, string>());
    const currentBook = books.find(b => b.portfolio_id === book), currentCalendar = calendars.find(c => c.import_id === calendar);
    async function load(signal?: AbortSignal) { setHealthy(false); setModeConfirm([]); const [b, w, c, conf, r, t] = await Promise.all([read<Book[]>("/api/v1/portfolios", { signal }), read<Hit[]>("/api/v1/watchlist", { signal }), read<{
            configurations: Calendar[];
        }>("/api/v1/calendar", { signal }), read<Config[]>("/api/v1/runtime/daily", { signal }), read<Report[]>("/api/v1/runtime/daily/reports", { signal }), read<Task[]>("/api/v1/runtime/daily/runs", { signal })]); if (!Array.isArray(b) || !Array.isArray(w) || !Array.isArray(c.configurations) || !Array.isArray(conf) || !Array.isArray(r))
        throw new Error("每日运行时响应格式不符, 未显示旧状态。"); setBooks(b); setWatches(w); setCalendars(c.configurations.filter(v => ["SSE", "SZSE"].includes(v.venue))); setConfigs(conf); setReports(r); setTasks(t); setHealthy(true); }
    useEffect(() => { const controller = new AbortController(); void load(controller.signal).catch(e => { if (!controller.signal.aborted)
        setError(String(e)); }); return () => controller.abort(); }, []);
    const firstInstrument = currentBook?.positions[0]?.instrument_id ?? selected[0];
    useEffect(() => { setChosen({}); setModels([]); setRoles([]); if (!firstInstrument)
        return; const controller = new AbortController(); void read<{
        roles: string[];
        models: Model[];
    }>(`/api/v1/analysis/choices?instrument_id=${encodeURIComponent(firstInstrument)}`, { signal: controller.signal }).then(v => { if (!controller.signal.aborted) {
        setRoles(v.roles);
        setModels(v.models);
    } }).catch(e => { if (!controller.signal.aborted)
        setError(String(e)); }); return () => controller.abort(); }, [firstInstrument]);
    function invalidate() { setPreview(null); setConfirmed(false); setMessage(null); }
    async function act(operation: () => Promise<void>) { if (busy.current)
        return; busy.current = true; setWorking(true); setError(null); try {
        await operation();
    }
    catch (e) {
        setHealthy(false);
        setError(`${String(e)} 若写入结果未确认, 请保留输入用同一按钮重试核对; 不会自动重新提交或出站。`);
    }
    finally {
        busy.current = false;
        setWorking(false);
    } }
    async function prepare() { await act(async () => { if (!currentBook || !currentCalendar || !ack)
        throw new Error("请选择组合和已导入日历, 完整确认范围与日期覆盖。"); const fields = { name, mode, market: currentCalendar.venue, portfolio_id: book, portfolio_instrument_ids: currentBook.positions.map(p => p.instrument_id), watchlist_instrument_ids: selected, calendar_import_id: calendar, coverage_start: start, coverage_end: end, frequency: "DAILY_AFTER_EXPLICIT_CLOSE", missed_run_policy: "LOCAL_REPORT_ONLY_NO_RESEARCH", quote_source_name: source, evidence_source_names: sources.split("\n").map(s => s.trim()).filter(Boolean), retention_days: Number(retention), valid_from: new Date(validFrom).toISOString(), valid_until: new Date(validUntil).toISOString(), model_profiles: mode === "LOCAL_STATUS_ONLY" ? {} : chosen, data_profile_ids: [], limits: mode === "LOCAL_STATUS_ONLY" ? { currency: "NONE", task_tokens: 0, day_tokens: 0, task_cost: "0", day_cost: "0" } : { ...limits, task_tokens: Number(limits.task_tokens), day_tokens: Number(limits.day_tokens) }, pause_method: "DAILY_UI_PAUSE_OR_REVOKE", complete_calendar_acknowledgement: ack, scope_acknowledgement: ack, local_only_acknowledgement: mode === "LOCAL_STATUS_ONLY", model_egress_acknowledgement: mode === "SCHEDULED_SHADOW" && costAck, cost_acknowledgement: mode === "SCHEDULED_SHADOW" && costAck }; const key = JSON.stringify(fields); if (request.current?.key !== key)
        request.current = { key, body: { ...fields, request_id: crypto.randomUUID(), schedule_id: crypto.randomUUID(), expected_version: 0 } }; const value = await read<Prepared>("/api/v1/runtime/daily/preview", post(request.current.body)); setPreview(value); setConfirmed(false); setMessage("已从真实本地数据预览完整授权, 尚未保存或启用。"); }); }
    async function save() { if (!preview || !confirmed || !request.current)
        return; const body = request.current.body; await act(async () => { await read<Config>("/api/v1/runtime/daily", post(body)); setMessage("已保存新授权, 默认暂停。请另行核对并明确启用。没有立即研究调用。"); await load(); }); }
    async function changeMode(config: Config, action: string) { if (!modeConfirm.includes(config.schedule_id))
        return; const key = `${config.schedule_id}:${config.version}:${action}`; if (!modeRequests.current.has(key))
        modeRequests.current.set(key, crypto.randomUUID()); await act(async () => { await read<Config>(`/api/v1/runtime/daily/${config.schedule_id}/mode`, post({ request_id: modeRequests.current.get(key), expected_version: config.version, action, confirmed: true })); setMessage(action === "ENABLE" ? "已启用; 仅等待显式日历到期, 不补发历史付费研究。" : "暂停 / 撤销已确认; 已出站的调用可能收费, 后续调用受阻。撤销不可恢复。"); setModeConfirm([]); await load(); }); }
    return <Panel title="每日检查与影子研究" description="默认暂停。独立于上方日历状态报告; 不产生交易或自动批准。">
 {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
 <button type="button" disabled={working} onClick={() => void act(async () => { await load(); setMessage("已刷新真实每日配置与报告。"); })}>刷新每日状态与报告</button>
 <form onChange={invalidate} onSubmit={e => { e.preventDefault(); void prepare(); }}>
 <fieldset disabled={working || !healthy}><legend>创建新每日授权（保存后暂停）</legend>
 <label>任务名称<input value={name} onChange={e => setName(e.target.value)} required/></label>
 <label>组合<select aria-label="组合" value={book} onChange={e => setBook(e.target.value)} required><option value="">请选择</option>{books.map(b => <option value={b.portfolio_id} key={b.portfolio_id}>{b.name}</option>)}</select></label>
 <p>将包含所选组合全部当前持仓: {currentBook?.positions.map(p => `${p.name} ${p.symbol}`).join("、") || "尚未选择 / 没有持仓"}。后续成员漂移会阻断调用, 不自动扩张。</p>
 <p>额外观察标的（仅明确选中项）:</p>{watches.map(w => <label key={w.instrument_id}><input type="checkbox" checked={selected.includes(w.instrument_id)} onChange={e => setSelected(old => e.target.checked ? [...old, w.instrument_id] : old.filter(v => v !== w.instrument_id))}/>{w.name} {w.symbol}</label>)}
 <label>显式交易日历<select aria-label="显式交易日历" value={calendar} onChange={e => setCalendar(e.target.value)} required><option value="">请选择已导入日历</option>{calendars.map(c => <option key={c.import_id} value={c.import_id}>{c.venue} · {c.source_name} {c.source_version}</option>)}</select></label>
 <label>完整日期覆盖起日<input type="date" value={start} onChange={e => setStart(e.target.value)} required/></label><label>完整日期覆盖止日<input type="date" value={end} onChange={e => setEnd(e.target.value)} required/></label>
 <label>授权开始（浏览器本地时区, 保存为UTC）<input type="datetime-local" value={validFrom} onChange={e => setValidFrom(e.target.value)} required/></label><label>授权截止<input type="datetime-local" value={validUntil} onChange={e => setValidUntil(e.target.value)} required/></label>
 <label>报告使用期限（天）<input type="number" min="1" max="3650" value={retention} onChange={e => setRetention(e.target.value)} required/></label>
 <label>本地报价来源名称<input value={source} onChange={e => setSource(e.target.value)} required/></label><label>允许本地资料来源（每行一个, 空白表示无资料许可）<textarea value={sources} onChange={e => setSources(e.target.value)}/></label>
 <label>运行模式<select aria-label="运行模式" value={mode} onChange={e => { setMode(e.target.value); setCostAck(false); }}><option value="LOCAL_STATUS_ONLY">仅本地状态, 零外部 / 模型 / 费用</option><option value="SCHEDULED_SHADOW">明确授权模型的定时影子研究</option></select></label>
 {mode === "SCHEDULED_SHADOW" && <><p>外部资料费用准入尚未提供, 资料档案固定为空; 只允许上面明确的本地资料。必须逐角色选择模型并填写费用上限。</p>{roles.map(role => <label key={role}>{roleNames[role] ?? role}模型<select aria-label={`${roleNames[role] ?? role}模型`} value={chosen[role] ?? ""} onChange={e => setChosen(old => ({ ...old, [role]: e.target.value }))} required><option value="">请选择</option>{models.filter(m => m.pricing_configured).map(m => <option value={m.profile_id} key={m.profile_id}>{m.name} / {m.model_name}</option>)}</select></label>)}{(Object.keys(limits) as (keyof typeof limits)[]).map(key => <label key={key}>{limitNames[key]}<input value={limits[key]} onChange={e => setLimits(old => ({ ...old, [key]: e.target.value }))} required/></label>)}<label><input type="checkbox" checked={costAck} onChange={e => setCostAck(e.target.checked)}/>我明确允许所选模型出站及上述费用边界, 会另行核对完整价格与预算快照。</label></>}
 <p>频率: 每个显式会话收盘后一次。错过原业务日只补本地状态, 不补历史收费研究。可在此页暂停或永久撤销; 报告保留审计历史, 到期停止展示正文。</p>
 <label><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} required/>我确认所列组合全体、选中观察项、市场、来源和完整日历日期覆盖, 以及上述频率 / 期限 / 暂停方式。</label>
 <button type="submit">预览完整授权（不保存、不启用）</button></fieldset></form>
 {preview && <section aria-label="每日授权预览"><h3>完整授权预览</h3><p>日历: {preview.calendar_source} / {preview.calendar_version} · {preview.calendar_hash}</p><p>标的: {preview.members.map(m => `${m.name} ${m.symbol}`).join("、")}</p>{Object.entries(preview.models).map(([role, m]) => <div key={role}><strong>{role}: {m.name} / {m.model_name}</strong><p>{preview.model_pricing[role]?.base_url} · {preview.model_pricing[role]?.currency} · 输入每Token {preview.model_pricing[role]?.input_token_price} / 输出每Token {preview.model_pricing[role]?.output_token_price} · 生效 {preview.model_pricing[role]?.effective_at}</p></div>)}{preview.budget_snapshot && <p>预算版本 {preview.budget_snapshot.version}: {Object.entries(preview.budget_snapshot.limits).map(([k, v]) => `${limitNames[k] ?? k}=${v}`).join("; ")}</p>}<label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/>已核对全部范围、频率、期限、来源、价格、预算与暂停方式; 保存为暂停授权。</label><button disabled={working || !healthy || !confirmed} onClick={() => void save()}>保存为暂停（另行启用）</button></section>}
 <h3>已保存任务</h3>{configs.map(c => <article key={c.schedule_id}><h4>{String(c.prepared.command.name)} · {c.revoked ? "已永久撤销" : c.enabled ? "已启用" : "已暂停"}</h4><p>版本 {c.version} · {c.blocker ?? "等待显式日历到期"}</p><p>保存范围: {c.prepared.members.map(m => `${m.name} ${m.symbol}`).join("、")} · 日历 {c.prepared.calendar_source} / {c.prepared.calendar_version}</p><p>每日显式收盘后一次 · 完整覆盖 {String(c.prepared.command.coverage_start)} 至 {String(c.prepared.command.coverage_end)} · 期限 {String(c.prepared.command.retention_days)} 天 · 仅本地资料 {String(c.prepared.command.evidence_source_names)}</p>{Object.entries(c.prepared.model_pricing).map(([role, p]) => <p key={role}>{role} · {p.base_url} · {p.currency} · 输入每Token {p.input_token_price} / 输出每Token {p.output_token_price} · 价格生效 {p.effective_at}</p>)}{c.prepared.budget_snapshot && <p>保存预算 {c.prepared.budget_snapshot.version}: {Object.entries(c.prepared.budget_snapshot.limits).map(([k, v]) => `${limitNames[k] ?? k}=${v}`).join("; ")}</p>}<p>模式 {String(c.prepared.command.mode)} · {String(c.prepared.command.valid_from)} 至 {String(c.prepared.command.valid_until)}</p><label><input type="checkbox" checked={modeConfirm.includes(c.schedule_id)} onChange={e => setModeConfirm(old => e.target.checked ? [...old, c.schedule_id] : old.filter(v => v !== c.schedule_id))}/>我已核对此保存授权, 明确确认本次启用 / 暂停 / 永久撤销</label>{["ENABLE", "PAUSE", "REVOKE"].map((a, i) => <button key={a} disabled={working || !healthy || c.revoked || !modeConfirm.includes(c.schedule_id)} onClick={() => void changeMode(c, a)}>{["启用每日任务", "暂停每日任务", "永久撤销授权"][i]}</button>)}</article>)}
 <h3>真实每日任务记录</h3><p>这里只表示本地调度与报告事务状态; SUCCEEDED不代表模型分析成功。请同时核对日报阶段与原始Analysis。</p>{tasks.map(t => <p key={t.task_run_id}>{t.status} · 第{t.attempt}次本地尝试 · {t.started_at} · {t.error_code ?? "无已记录错误"}</p>)}
 <h3>实际日报历史</h3>{reports.length === 0 ? <p>尚无有效日报; 不代表任务成功或没有风险。请核对启用、完整日历与真实Worker状态。</p> : reports.map(r => <article key={r.report_id}><h4>{r.phase}</h4><p>业务收盘 {r.business_as_of} · 实际知识时点 {r.as_of} · 记录 {r.recorded_at}</p>{(Object.keys(sectionNames) as (keyof typeof sectionNames)[]).map(key => <section key={key}><h5>{sectionNames[key]} · {r[key].availability}</h5>{r[key].messages.map((m, i) => <p key={i}>{m}</p>)}{r[key].analysis_run_ids.map(id => <a key={id} href={`/analysis?portfolio_id=${encodeURIComponent(r.local_inputs.portfolio.portfolio_id)}&run_id=${encodeURIComponent(id)}`}>查看真实影子分析</a>)}</section>)}</article>)}
 </Panel>;
}
