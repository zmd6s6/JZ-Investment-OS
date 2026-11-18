import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch, getWriteToken, readApiError } from './writeApi';

type Protocol = '1.0' | '2.0';
type Task = {
  schema_version: '1.0'; protocol: Protocol; task_run_id: string;
  schedule_id: string | null; revision_id: string | null; week_start: string | null;
  scheduled_for: string; created_at: string; started_at: string; finished_at: string | null;
  task_status: string; attempt: number; reason_code: string | null; input_hash: string;
  result_status: string | null; as_of: string | null; candidate_count: number | null;
  unknowns: string[]; auto_trade: false;
};
type Provenance = {
  name: string; venue: string; revision_hash: string; calendar_import_id: string;
  calendar_hash: string; calendar_source: string | null; calendar_version: string | null;
  template_run_id: string; source_name: string; source_locator: string;
  quote_source_name: string; fact_source_name: string; snapshot_id: string | null;
  snapshot_hash: string | null; coverage_start: string; coverage_end: string;
  source_verification: 'SOURCE_DECLARED_UNVERIFIED';
};
type Detail = Task & { provenance: Provenance | null; funnel_run_id: string | null;
  funnel_hash: string | null; attempt_history: 'NOT_PROVIDED_CURRENT_RECORDED_ATTEMPT_ONLY' };
type Page = { schema_version: '1.0'; protocol: Protocol; items: Task[];
  next_cursor: string | null; page_size: 50; ordering: 'created_at_desc_task_id_desc'; auto_trade: false };
const uuid = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const text = (value: unknown): value is string => typeof value === 'string';
const hash = (value: unknown) => text(value) && /^[a-f0-9]{64}$/.test(value);
const time = (value: unknown) => text(value) && Number.isFinite(Date.parse(value));
const optional = (value: unknown, valid: (item: unknown) => boolean) => value === null || valid(value);
const status: Record<string, string> = { FAILED: '任务失败', SUCCEEDED: '任务已完成', RUNNING: '任务运行中', PENDING: '任务等待中', COMPLETE: '筛选已完成', DEGRADED: '资料不完整', EMPTY: '没有候选', SKIPPED_CLOSED: '闭市已跳过' };
const unknown: Record<string, string> = {
  ATTEMPT_TIMELINE_NOT_RECORDED: '未记录逐次尝试时间线，仅显示当前保存的尝试与状态',
  LEGACY_TASK_IDENTITY_NOT_PROVIDED: '旧任务未保存可核对的原修订身份',
  NO_COMMITTED_WEEKLY_RESULT: '没有已提交的周筛选结果', RESULT_REFERENCE_MISMATCH: '结果与原任务修订不一致',
  ORIGINAL_REVISION_MISSING_OR_UNVERIFIED: '原修订缺失或无法核验，不用当前配置替代',
  ORIGINAL_CALENDAR_SOURCE_NOT_PROVIDED: '原日历来源缺失，未推断官方核验',
  NO_VERIFIED_FUNNEL_ARTIFACT: '没有可核验的筛选产物', ORIGINAL_ARTIFACT_MISSING_OR_UNVERIFIED: '原产物缺失或无法核验',
};
function parseTask(raw: unknown, protocol: Protocol): Task {
  const value = raw as Task;
  if (!value || value.schema_version !== '1.0' || value.protocol !== protocol || !uuid(value.task_run_id) ||
    !optional(value.schedule_id, uuid) || !optional(value.revision_id, uuid) || !optional(value.week_start, text) ||
    !time(value.scheduled_for) || !time(value.created_at) || !time(value.started_at) || !optional(value.finished_at, time) ||
    !text(value.task_status) || !Number.isInteger(value.attempt) || value.attempt < 1 ||
    !optional(value.reason_code, text) || !hash(value.input_hash) || !optional(value.result_status, text) ||
    !optional(value.as_of, time) || !optional(value.candidate_count, item => Number.isInteger(item) && Number(item) >= 0 && Number(item) <= 20) ||
    !Array.isArray(value.unknowns) || !value.unknowns.every(text) || value.auto_trade !== false) {
    throw new Error('周任务记录格式异常，未采用其他记录。');
  }
  return value;
}
function parsePage(raw: unknown, protocol: Protocol): Page {
  const value = raw as Page;
  if (!value || value.schema_version !== '1.0' || value.protocol !== protocol || value.page_size !== 50 ||
    value.ordering !== 'created_at_desc_task_id_desc' || value.auto_trade !== false ||
    !Array.isArray(value.items) || value.items.length > 50 || !optional(value.next_cursor, text)) throw new Error('周任务分页格式异常，请重试。');
  value.items.forEach(item => parseTask(item, protocol));
  if (new Set(value.items.map(item => item.task_run_id)).size !== value.items.length) throw new Error('周任务分页包含重复记录，请刷新核对。');
  return value;
}
function parseDetail(raw: unknown, protocol: Protocol, id: string): Detail {
  const value = raw as Detail;
  parseTask(value, protocol);
  if (value.task_run_id !== id || value.attempt_history !== 'NOT_PROVIDED_CURRENT_RECORDED_ATTEMPT_ONLY' ||
    !optional(value.funnel_run_id, uuid) || !optional(value.funnel_hash, hash) ||
    Boolean(value.funnel_run_id) !== Boolean(value.funnel_hash)) throw new Error('周任务详情与原ID不一致，未采用。');
  const p = value.provenance;
  if (p && (!text(p.name) || !text(p.venue) || !hash(p.revision_hash) || !uuid(p.calendar_import_id) ||
    !hash(p.calendar_hash) || !optional(p.calendar_source, text) || !optional(p.calendar_version, text) ||
    !uuid(p.template_run_id) || ![p.source_name, p.source_locator, p.quote_source_name, p.fact_source_name, p.coverage_start, p.coverage_end].every(text) ||
    !optional(p.snapshot_id, uuid) || !optional(p.snapshot_hash, hash) || p.source_verification !== 'SOURCE_DECLARED_UNVERIFIED')) throw new Error('原修订来源格式异常，请重读原任务。');
  if (p === undefined || (value.funnel_run_id && !p)) throw new Error('原任务来源无法核验。');
  return value;
}
async function read(url: string, signal: AbortSignal): Promise<unknown> {
  const response = await apiFetch(url, { signal, headers: { Authorization: `Bearer ${getWriteToken()}` } });
  if (response.status === 401 || response.status === 503) throw new Error('任务审计需要有效令牌或服务装配，请核对右上角令牌后重试。');
  if (!response.ok) throw new Error(await readApiError(response));
  return response.json();
}
const missing = (value: string | number | null) => value ?? '未提供';

export function WeeklyTaskHistory({ version }: { version: Protocol }) {
  const base = version === '2.0' ? '/api/v1/opportunities/complete-weekly' : '/api/v1/opportunities/weekly';
  const queryKey = version === '2.0' ? 'complete_weekly_task_id' : 'weekly_task_id';
  const [rows, setRows] = useState<Task[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [id, setId] = useState(() => new URLSearchParams(window.location.search).get(queryKey) ?? '');
  const [detail, setDetail] = useState<Detail | null>(null);
  const [pageError, setPageError] = useState(''), [detailError, setDetailError] = useState('');
  const [pageBusy, setPageBusy] = useState(false), [detailBusy, setDetailBusy] = useState(false);
  const pageRequest = useRef(0), detailRequest = useRef(0);
  const pageController = useRef<AbortController | null>(null), detailController = useRef<AbortController | null>(null);
  const load = useCallback(async (after: string | null = null) => {
    const generation = ++pageRequest.current;
    pageController.current?.abort();
    const controller = new AbortController(); pageController.current = controller;
    setPageBusy(true); setPageError('');
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const page = parsePage(await read(`${base}/tasks${after ? `?cursor=${encodeURIComponent(after)}` : ''}`, controller.signal), version);
      if (generation !== pageRequest.current) return;
      setRows(previous => after ? [...previous, ...page.items.filter(item => !previous.some(old => old.task_run_id === item.task_run_id))] : page.items);
      setCursor(page.next_cursor);
    } catch (error) {
      if (generation === pageRequest.current) setPageError(error instanceof Error && error.name !== 'AbortError' ? error.message : '周任务分页连接失败或超时，已加载记录保留，请重试。');
    } finally { clearTimeout(timeout); if (generation === pageRequest.current) setPageBusy(false); }
  }, [base, version]);
  const open = useCallback(async (selected: string) => {
    selected = selected.trim().toLowerCase();
    const generation = ++detailRequest.current;
    detailController.current?.abort();
    setId(selected); setDetail(null); setDetailError(''); setDetailBusy(false);
    const url = new URL(window.location.href); url.searchParams.set(queryKey, selected); window.history.replaceState(null, '', url);
    if (!uuid(selected)) { setDetailError('周任务ID格式无效，请核对原任务链接。'); return; }
    const controller = new AbortController(); detailController.current = controller; setDetailBusy(true);
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const value = parseDetail(await read(`${base}/tasks/${encodeURIComponent(selected)}`, controller.signal), version, selected);
      if (generation === detailRequest.current) setDetail(value);
    } catch (error) {
      if (generation === detailRequest.current) setDetailError(error instanceof Error && error.name !== 'AbortError' ? error.message : '任务详情连接失败或超时，旧详情已清除，请重试。');
    } finally { clearTimeout(timeout); if (generation === detailRequest.current) setDetailBusy(false); }
  }, [base, queryKey, version]);
  useEffect(() => {
    setRows([]); setCursor(null); setDetail(null); setDetailError('');
    void load();
    const selected = new URLSearchParams(window.location.search).get(queryKey) ?? '';
    setId(selected); if (selected) void open(selected);
    return () => { ++pageRequest.current; ++detailRequest.current; pageController.current?.abort(); detailController.current?.abort(); };
  }, [load, open, queryKey]);
  function submit(event: FormEvent) { event.preventDefault(); void open(id.trim()); }
  const p = detail?.provenance;
  return <section aria-label={version === '2.0' ? '完整来源周任务审计' : '本地周任务审计'}>
    <h3>周筛选运行历史</h3>
    <p>已加载{rows.length}条，每页最多50条。按首次记录时间和任务ID倒序读取。新增记录请刷新重查。旧失败与闭市记录也可按原ID打开。</p>
    <button type="button" disabled={pageBusy} onClick={() => void load()}>刷新周任务历史</button>
    {pageError && <p role="alert">{pageError}</p>}
    {!pageBusy && !pageError && rows.length === 0 && <p>尚无周筛选任务。</p>}
    {rows.map(row => <article className="evidence-card" key={row.task_run_id}>
      <h4>{missing(row.week_start)} 周 · {status[row.result_status ?? row.task_status] ?? '原记录状态未知'}</h4>
      <p>任务 {row.task_run_id} · 原修订 {missing(row.revision_id)} · 当前记录尝试{row.attempt}</p>
      <button type="button" onClick={() => void open(row.task_run_id)}>查看原周任务 {row.task_run_id}</button>
    </article>)}
    {cursor && <button type="button" disabled={pageBusy} onClick={() => void load(cursor)}>加载更早周任务</button>}
    <form onSubmit={submit}><label>精确周任务ID<input value={id} onChange={event => { ++detailRequest.current; detailController.current?.abort(); setId(event.target.value); setDetail(null); setDetailError(''); setDetailBusy(false); }}/></label><button type="submit" disabled={detailBusy}>打开精确周任务</button></form>
    <button type="button" disabled={detailBusy || !id} onClick={() => void open(id)}>刷新所选周任务</button>
    {detailBusy && <p role="status">正在读取原任务。</p>}
    {detailError && <p role="alert">{detailError}</p>}
    {detail && <section aria-label="原周任务审计详情">
      <h4>原任务 {detail.task_run_id}</h4>
      <p>配置 {missing(detail.schedule_id)} · 修订 {missing(detail.revision_id)} · 周开始 {missing(detail.week_start)}</p>
      <p>任务 {status[detail.task_status] ?? detail.task_status} · 结果 {missing(detail.result_status)} · 当前记录尝试{detail.attempt} · 原因 {missing(detail.reason_code)}</p>
      <p>到期 {detail.scheduled_for} · 首次记录 {detail.created_at} · 当前尝试开始 {detail.started_at} · 完成 {missing(detail.finished_at)} · 业务快照 {missing(detail.as_of)} · 输入hash {detail.input_hash}</p>
      {p ? <><p>原授权 {p.name} · {p.venue} · 覆盖 {p.coverage_start} 至 {p.coverage_end} · 修订hash {p.revision_hash}</p>
        <p>原日历 {p.calendar_import_id} · {missing(p.calendar_source)} / {missing(p.calendar_version)} · hash {p.calendar_hash}</p>
        <p>原模板 {p.template_run_id} · 来源 {p.source_name} / {p.source_locator} · 报价 {p.quote_source_name} · 事实 {p.fact_source_name}</p>
        <p>完整来源快照 {missing(p.snapshot_id)} · hash {missing(p.snapshot_hash)} · SOURCE_DECLARED / UNVERIFIED，未推断官方核验。</p></> : <p>原修订来源未提供或无法核验，未用当前配置代替。</p>}
      {detail.funnel_run_id ? <a href={`/opportunities?${version === '2.0' ? 'complete_run_id' : 'run_id'}=${encodeURIComponent(detail.funnel_run_id)}`}>查看原周筛选产物</a> : <p>本任务没有可核验的筛选产物。</p>}
      {detail.funnel_hash && <p>原产物hash {detail.funnel_hash}</p>}
      {detail.unknowns.map(value => <p key={value}>{unknown[value] ?? `未提供的审计信息 ${value}`}</p>)}
      <p>只读审计。刷新不重试任务、不重新筛选或调用模型。SIMULATION / NO AUTO TRADE。</p>
    </section>}
  </section>;
}
