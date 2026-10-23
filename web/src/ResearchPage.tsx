import { FormEvent, useEffect, useRef, useState } from "react";
import { AnalysisStartDialog } from "./AnalysisStartDialog";
import { InstrumentHit, InstrumentSearchBox } from "./InstrumentSearchBox";
import { EmptyState, Panel, ProductChrome, StatusBanner } from "./ProductChrome";
import { apiFetch, readApiError } from "./writeApi";
import { submitAnalysis, type AnalysisLaunchSelection } from "./analysisSubmission";
import { readAnalysisJson } from "./analysisReads";

type Profile = { id: string; name: string; provider_type: string; enabled: boolean; credential_configured: boolean; retention_days: number };
type EvidenceItem = { evidence_id: string; source_name: string; source_locator: string; source_tier: string; provider: string; evidence_type: string; title: string; excerpt: string; observed_at: string; available_at: string; ingested_at: string; expires_at: string | null; freshness_status: string; content_hash: string };
type EvidenceList = { as_of: string; items: EvidenceItem[] };
type CommitResult = { candidate_id: string; evidence_id: string; reused: boolean };
type Candidate = Omit<EvidenceItem, "evidence_id" | "ingested_at" | "content_hash" | "evidence_type"> & { candidate_id: string };
type Preview = { preview_id: string; profile_id: string; instrument_id: string; query: string; created_at: string; expires_at: string; as_of: string; candidates: Candidate[]; confirmation: CommitResult[] | null };
const freshness: Record<string, string> = { FRESH: "期限内资料（不代表事实已核实）", STALE: "陈旧资料", EXPIRED: "已过期 · 不用于新分析", NOT_YET_AVAILABLE: "尚未可用 · 不用于新分析" };
const tiers: Record<string, string> = { PRIMARY: "一手来源", REPUTABLE_SECONDARY: "可信二手来源", OTHER: "其他来源 / 搜索线索" };
function date(value: string | null) { return value ? `${value.replace("T", " ").replace("+00:00", "Z")}（UTC）` : "未设定"; }
async function read<T>(url: string, signal?: AbortSignal): Promise<T> {
  return readAnalysisJson<T>(url, signal, "读取研究资料");
}
type Attempt = { id: string; profileId: string; status: "WAITING" | "RUNNING" | "READY" | "UNKNOWN"; error?: string };

export function ResearchPage() {
  const [instrument, setInstrument] = useState<InstrumentHit | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [profileId, setProfileId] = useState("");
  const [extraProfileIds, setExtraProfileIds] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [count, setCount] = useState(5);
  const [consent, setConsent] = useState(false);
  const [library, setLibrary] = useState<EvidenceList | null>(null);
  const [loading, setLoading] = useState(false);
  const [configLoading, setConfigLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [revision, setRevision] = useState(0);
  const [previews, setPreviews] = useState<Preview[]>([]);
  const [activePreviewId, setActivePreviewId] = useState("");
  const [candidateSelections, setCandidateSelections] = useState<Record<string, string[]>>({});
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const preview = previews.find((item) => item.preview_id === activePreviewId) ?? null;
  const candidateIds = preview ? candidateSelections[preview.preview_id] ?? [] : [];
  function setCandidateIds(value: string[] | ((ids: string[]) => string[])) {
    if (!preview) return;
    setCandidateSelections((previous) => ({ ...previous, [preview.preview_id]: typeof value === "function" ? value(previous[preview.preview_id] ?? []) : value }));
  }
  function retainPreview(value: Preview, selectConfirmed = true) {
    setPreviews((previous) => [...previous.filter((item) => item.preview_id !== value.preview_id), value]);
    setActivePreviewId((previous) => previous || value.preview_id);
    setCandidateSelections((previous) => ({ ...previous, [value.preview_id]: value.confirmation?.map((item) => item.candidate_id) ?? previous[value.preview_id] ?? [] }));
    const confirmedIds = value.confirmation?.map((item) => item.evidence_id);
    if (selectConfirmed && confirmedIds) setEvidenceIds((previous) => [...new Set([...previous, ...confirmedIds])]);
  }
  const [evidenceIds, setEvidenceIds] = useState<string[]>([]);
  const [recoveryId, setRecoveryId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const readSequence = useRef(0);
  const selectionSequence = useRef(0);
  const evidenceSelectionSequence = useRef(0);
  const submitting = useRef(false);

  useEffect(() => {
    let active = true;
    void Promise.all([
      read<Profile[]>("/api/v1/settings/data-providers"),
      read<{ provider_types: string[] }>("/api/v1/research/capabilities"),
    ]).then(([rows, capabilities]) => { if (active) { setProfiles(rows); setTypes(capabilities.provider_types); } })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "无法读取数据源，请刷新重试。"); })
      .finally(() => { if (active) setConfigLoading(false); });
    const sequence = selectionSequence.current;
    const evidenceSequence = evidenceSelectionSequence.current;
    const id = new URLSearchParams(window.location.search).get("instrument_id");
    const drafts = [...new Set(new URLSearchParams(window.location.search).getAll("preview_id"))];
    const draft = drafts[0];
    if (drafts.length > 5) setError("一次最多找回 5 个来源预览；未发送任何供应商查询。");
    else if (id && draft) {
      setRecoveryId(draft);
      setAttempts(drafts.map((key) => ({ id: key, profileId: "", status: "WAITING" })));
      void Promise.all(drafts.map(async (key) => {
        try {
          const value = await read<Preview>(`/api/v1/research/previews/${encodeURIComponent(key)}`);
          if (!active || sequence !== selectionSequence.current) return;
          if (value.instrument_id !== id || value.preview_id !== key) throw new Error("预览与当前标的或请求不一致，未采用。");
          retainPreview(value, evidenceSequence === evidenceSelectionSequence.current);
          setAttempts((rows) => rows.map((row) => row.id === key ? { ...row, profileId: value.profile_id, status: "READY" } : row));
          if (key === draft) { setQuery(value.query); setProfileId(value.profile_id); setActivePreviewId(key); setConsent(false); }
        } catch (reason) {
          if (active && sequence === selectionSequence.current) {
            const detail = reason instanceof Error ? reason.message : "预览读取失败。";
            setAttempts((rows) => rows.map((row) => row.id === key ? { ...row, status: "UNKNOWN", error: detail } : row));
            setError(`${detail} 只读找回未调用供应商；没有结果不等于未计费。`);
          }
        }
      }));
    }
    if (id) void read<InstrumentHit>(`/api/v1/instruments/${encodeURIComponent(id)}`).then((hit) => {
      if (active && sequence === selectionSequence.current) { setInstrument(hit); if (!draft) { setQuery(`${hit.name} ${hit.symbol} 最新公告`); setConsent(false); } }
    }).catch((reason) => { if (active && sequence === selectionSequence.current) setError(reason instanceof Error ? reason.message : "无法读取标的。"); });
    return () => { active = false; selectionSequence.current++; };
  }, []);

  useEffect(() => {
    const sequence = ++readSequence.current;
    setLibrary(null);
    if (!instrument) { setLoading(false); return; }
    let active = true;
    setLoading(true);
    void read<EvidenceList>(`/api/v1/instruments/${encodeURIComponent(instrument.instrument_id)}/evidence?limit=50`)
      .then((rows) => { if (active && sequence === readSequence.current) setLibrary(rows); })
      .catch((reason) => { if (active && sequence === readSequence.current) setError(reason instanceof Error ? reason.message : "资料读取失败。"); })
      .finally(() => { if (active && sequence === readSequence.current) setLoading(false); });
    return () => { active = false; };
  }, [instrument?.instrument_id, revision]);

  function selectInstrument(hit: InstrumentHit) {
    if (submitting.current) return;
    selectionSequence.current++;
    readSequence.current++;
    setInstrument(hit); setLibrary(null); setError(null); setMessage(null); setConsent(false);
    setPreviews([]); setActivePreviewId(""); setCandidateSelections({}); setAttempts([]); setEvidenceIds([]); setRecoveryId(null);
    setQuery(`${hit.name} ${hit.symbol} 最新公告`);
    window.history.replaceState(null, "", `/research?instrument_id=${encodeURIComponent(hit.instrument_id)}`);
  }
  const selected = profiles.find((item) => item.id === profileId);
  const selectedIds = profileId ? [profileId, ...extraProfileIds] : [];
  const usable = selectedIds.length > 0 && selectedIds.length <= 5 && selectedIds.length * count <= 50 && selectedIds.every((id) => profiles.some((item) => item.id === id && item.enabled && item.credential_configured && types.includes(item.provider_type)));

  function clearPreview() {
    if (instrument) selectionSequence.current++;
    setConsent(false); setPreviews([]); setActivePreviewId(""); setCandidateSelections({}); setAttempts([]); setRecoveryId(null);
    if (instrument) window.history.replaceState(null, "", `/research?instrument_id=${encodeURIComponent(instrument.instrument_id)}`);
  }

  async function recoverPreview(key = recoveryId) {
    if (!key || !instrument || submitting.current) return;
    submitting.current = true; setSaving(true); setError(null);
    const sequence = selectionSequence.current;
    try {
      const value = await read<Preview>(`/api/v1/research/previews/${encodeURIComponent(key)}`);
      if (sequence !== selectionSequence.current) return;
      const expectedProfile = attempts.find((item) => item.id === key)?.profileId;
      if (value.instrument_id !== instrument.instrument_id || value.preview_id !== key || (expectedProfile && value.profile_id !== expectedProfile)) throw new Error("预览不属于当前标的、来源或请求，请重新核对。");
      retainPreview(value); setActivePreviewId(key);
      setAttempts((rows) => rows.map((row) => row.id === key ? { ...row, profileId: value.profile_id, status: "READY", error: undefined } : row));
      if (value.confirmation) setRevision((v) => v + 1);
      setMessage("已读取原预览；没有再次查询供应商。");
    } catch (reason) { if (sequence === selectionSequence.current) setError(reason instanceof Error ? reason.message : "预览读取失败。"); }
    finally { submitting.current = false; setSaving(false); }
  }

  async function collect(event: FormEvent) {
    event.preventDefault();
    if (submitting.current || !instrument || !usable || !consent || !query.trim()) return;
    submitting.current = true; setBusy(true); setError(null); setMessage(null);
    const target = instrument;
    const sequence = selectionSequence.current;
    const plan: Attempt[] = selectedIds.map((id) => ({ id: crypto.randomUUID(), profileId: id, status: "WAITING" }));
    setRecoveryId(plan[0].id); setPreviews([]); setActivePreviewId(""); setCandidateSelections({}); setAttempts(plan);
    const params = new URLSearchParams({ instrument_id: target.instrument_id });
    plan.forEach((item) => params.append("preview_id", item.id));
    window.history.replaceState(null, "", `/research?${params}`);
    let failed = 0;
    let total = 0;
    try {
      for (const item of plan) {
        if (sequence !== selectionSequence.current) break;
        setAttempts((rows) => rows.map((row) => row.id === item.id ? { ...row, status: "RUNNING" } : row));
        try {
          // Every source was explicitly selected. Never replay a lost paid response.
          const response = await apiFetch(`/api/v1/research/providers/${encodeURIComponent(item.profileId)}/preview`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ request_id: item.id, query: query.trim(), instrument_id: target.instrument_id, max_results: count }),
          });
          if (!response.ok) throw new Error(await readApiError(response));
          const result = await response.json() as Preview;
          if (result.instrument_id !== target.instrument_id || result.profile_id !== item.profileId || result.preview_id !== item.id) throw new Error("返回预览与本次标的、来源或请求不一致，未采用。");
          if (sequence !== selectionSequence.current) break;
          retainPreview(result); total += result.candidates.length;
          setAttempts((rows) => rows.map((row) => row.id === item.id ? { ...row, status: "READY" } : row));
        } catch (reason) {
          failed++;
          if (sequence !== selectionSequence.current) break;
          const detail = reason instanceof Error ? reason.message : "资料获取失败。";
          setAttempts((rows) => rows.map((row) => row.id === item.id ? { ...row, status: "UNKNOWN", error: detail } : row));
          setError(`${detail} 若响应中断，请先找回原预览；不要直接重复付费查询。预览不会进入分析证据库，系统不会切换其他数据源；只会继续本次明确勾选的来源。`);
        }
      }
      if (sequence === selectionSequence.current) setMessage(total ? `已取得 ${total} 条候选资料，尚未写入证据库、未调用模型。请按来源分别勾选并保存。${failed ? `另有 ${failed} 个来源失败或结果未知，成功结果仍保留。` : ""}` : failed ? "所选来源未全部取得结果；请按来源只读找回核对，不会自动重发。" : "本次查询没有结果；未创建证据、未调用模型。可修改公开查询后重新确认。");
    } finally {
      setConsent(false);
      submitting.current = false; setBusy(false);
    }
  }

  async function confirmPreview(continueAnalysis: boolean) {
    if (submitting.current || !preview || !instrument || !candidateIds.length) return;
    submitting.current = true; setSaving(true); setError(null);
    const sequence = selectionSequence.current;
    try {
      const response = await apiFetch(`/api/v1/research/previews/${encodeURIComponent(preview.preview_id)}/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instrument_id: instrument.instrument_id, candidate_ids: candidateIds }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const results = await response.json() as CommitResult[];
      if (sequence !== selectionSequence.current) return;
      retainPreview({ ...preview, confirmation: results });
      setMessage(`所选 ${results.length} 条资料已保存；未调用模型。确认响应丢失时可找回原结果，不会重复入库。`);
      setRevision((value) => value + 1);
      if (continueAnalysis && new Set([...evidenceIds, ...results.map((item) => item.evidence_id)]).size <= 50) setAnalysisOpen(true);
    } catch (reason) { if (sequence === selectionSequence.current) setError(`${reason instanceof Error ? reason.message : "保存失败。"} 没有再次调用供应商；可找回预览核对确认结果。`); }
    finally { submitting.current = false; setSaving(false); }
  }

  async function analyze(portfolioId: string, models: AnalysisLaunchSelection) {
    if (submitting.current || !instrument || !evidenceIds.length || evidenceIds.length > 50) return;
    submitting.current = true; setAnalyzing(true); setAnalysisOpen(false); setError(null);
    try {
      const run = await submitAnalysis({ instrument_id: instrument.instrument_id, portfolio_id: portfolioId, source: "RESEARCH", evidence_ids: evidenceIds, ...models });
      try { sessionStorage.setItem("selected_portfolio_id", portfolioId); } catch { /* optional */ }
      window.location.href = `/analysis?run_id=${encodeURIComponent(run.id)}`;
    } catch (reason) { setError(reason instanceof Error ? reason.message : "分析未完成，请先查看运行列表。"); }
    finally { submitting.current = false; setAnalyzing(false); }
  }

  return <ProductChrome eyebrow="证据优先" title="研究资料" subtitle="先选标的和来源、核对公开查询，再获取资料。搜索线索不是行情，也不是已核实的事实。">
    {analysisOpen && instrument ? <AnalysisStartDialog label={`${instrument.symbol} ${instrument.name}`} evidenceCount={evidenceIds.length} onCancel={() => setAnalysisOpen(false)} onConfirm={(id, models) => void analyze(id, models)} /> : null}
    <div className="action-feedback"><StatusBanner kind="error" text={error} /><StatusBanner kind="ok" text={message} /><StatusBanner kind="info" text={busy ? "正在向所选数据源查询候选资料… 请保留页面，不要重复点击。" : saving ? "正在读取或确认所选资料… 不调用供应商或模型。" : analyzing ? "正在保存后台分析任务；成功后打开真实运行进度，可离开或刷新页面。" : null} /></div>
    <Panel title="1 · 选择研究对象" description="从持仓或观察清单进入会自动带入标的；此处也可搜索本地目录。">
      {!busy && !saving && !analyzing ? <InstrumentSearchBox onSelect={selectInstrument} /> : null}
      {instrument ? <a className="btn" href={`/thesis?instrument_id=${encodeURIComponent(instrument.instrument_id)}`}>维护此标的的投资逻辑</a> : null}
      {instrument ? <p className="context-note">当前标的：<strong>{instrument.name} · {instrument.market} {instrument.symbol}</strong>。资料关联不等于证明文章一定相关，请核对内容。</p> : <p>请选择标的。目录为空时，先到<a href="/watchlist">观察清单</a>添加研究对象。</p>}
    </Panel>
    <Panel title="2 · 明确获取来源" description="只调用本次选中的来源，不会自动启用、后台同步或失败换源。无需 Tushare Token。">
      {configLoading ? <p role="status">正在读取数据源…</p> : null}
      {!configLoading && !profiles.some((item) => item.enabled && item.credential_configured && types.includes(item.provider_type)) ? <p className="context-note">尚无可用研究来源。前往<a href="/settings#data">设置与提供方</a>配置、授权并启用研究档案；行情档案不能替代新闻研究来源。</p> : null}
      <form className="form-grid" onSubmit={(event) => void collect(event)}>
        <label className="field"><span>研究数据源</span><select required value={profileId} disabled={busy || saving || analyzing || configLoading} onChange={(event) => { clearPreview(); setProfileId(event.target.value); setExtraProfileIds([]); }}><option value="">请明确选择数据源</option>{profiles.map((item) => <option key={item.id} value={item.id} disabled={!item.enabled || !item.credential_configured || !types.includes(item.provider_type)}>{item.name} · {item.provider_type}{!types.includes(item.provider_type) ? "（不支持研究检索）" : !item.enabled ? "（未启用）" : !item.credential_configured ? "（未配置凭据）" : ""}</option>)}</select></label>
        {profileId ? <fieldset className="full-span"><legend>同时查询其他来源（可选，默认不选）</legend><p className="hint-text">最多 5 个来源，按勾选顺序逐个查询。全部属于本次明确授权，不是失败回退；每个来源都可能单独计费。</p>{profiles.filter((item) => item.id !== profileId).map((item) => <label className="consent-line" key={item.id}><input type="checkbox" aria-label={`同时查询 ${item.name}`} checked={extraProfileIds.includes(item.id)} disabled={busy || saving || analyzing || !item.enabled || !item.credential_configured || !types.includes(item.provider_type) || (!extraProfileIds.includes(item.id) && extraProfileIds.length >= 4)} onChange={(event) => { clearPreview(); setExtraProfileIds((ids) => event.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id)); }} />{item.name} · {item.provider_type}{!item.enabled || !item.credential_configured || !types.includes(item.provider_type) ? "（不可用，不调用）" : ` · 保留 ${item.retention_days} 天`}</label>)}<p className="context-note">本次顺序：{selectedIds.map((id) => profiles.find((item) => item.id === id)?.name ?? id).join(" → ")}；每源最多 {count} 条，共最多 {selectedIds.length * count} 条。总上限 50 条，超出请减少来源或每源数量。</p></fieldset> : null}
        <label className="field"><span>公开查询内容</span><input value={query} required maxLength={1000} disabled={busy || saving || analyzing} onChange={(event) => { clearPreview(); setQuery(event.target.value); }} placeholder="公司名称 代码 最新公告" /></label>
        <label className="field"><span>最多结果数</span><select value={count} disabled={busy || saving || analyzing} onChange={(event) => { clearPreview(); setCount(Number(event.target.value)); }}>{[1, 5, 10, 20].map((value) => <option key={value} value={value}>{value} 条 / 来源</option>)}</select></label>
        <div className="full-span"><p className="hint-text">查询会发给所选供应商，可能计费；不会发送持仓、成本或现金。候选先保存在受保护的预览中，只有你勾选确认后才进入证据库。保留上限遵守档案配置{selected ? `（${selected.retention_days} 天）` : ""}；预览确认窗口为 10 分钟。</p><label className="consent-line"><input type="checkbox" checked={consent} disabled={busy || saving || analyzing} onChange={(event) => setConsent(event.target.checked)} />我确认查询仅含公开信息，允许调用所选来源获取候选资料</label></div>
        <button className="btn primary" type="submit" disabled={busy || saving || analyzing || !instrument || !usable || !consent || !query.trim()}>{busy ? "正在获取预览…" : "获取资料预览"}</button>
      </form>
      {recoveryId ? <button type="button" className="btn" disabled={busy || saving || analyzing} onClick={() => void recoverPreview()}>找回原预览（不重新查询）</button> : null}
    </Panel>
    {attempts.length > 1 ? <Panel title="本次各来源结果" description="成功、空结果和失败分别保留，不合并为一份已核实结论。刷新只找回原预览，不重复查询。每个来源单独确认入库，不保证跨来源全部成功或全部回滚。">
      <ol>{attempts.map((item) => <li key={item.id} className="evidence-card"><p><strong>{profiles.find((row) => row.id === item.profileId)?.name ?? "待找回的来源"}</strong> · {item.status === "WAITING" ? "等待查询 / 找回（不代表已调用）" : item.status === "RUNNING" ? "正在查询，可能计费" : item.status === "READY" ? `${previews.find((row) => row.preview_id === item.id)?.candidates.length ?? 0} 条候选；${previews.find((row) => row.preview_id === item.id)?.confirmation ? "已确认入库" : "未确认入库"}` : "失败或结果未知；不等于未计费"}</p>{item.error ? <p className="hint-text">{item.error}</p> : null}<p className="hint-text">预览标识：{item.id}</p><div className="button-row">{previews.some((row) => row.preview_id === item.id) ? <button type="button" className="btn" disabled={busy || saving || analyzing} onClick={() => setActivePreviewId(item.id)}>查看此来源预览{activePreviewId === item.id ? "（当前）" : ""}</button> : null}<button type="button" className="btn" disabled={busy || saving || analyzing} onClick={() => void recoverPreview(item.id)}>只读找回此来源</button></div></li>)}</ol>
    </Panel> : null}
    {preview ? <Panel title="3 · 预览并选择要保存的资料" description={`候选不参与分析。确认截止：${date(preview.expires_at)}；过期后需明确重新查询，系统不会自动重发。`}>
      <p className="context-note">来源：{profiles.find((item) => item.id === preview.profile_id)?.name ?? preview.profile_id} · 本次查询：{preview.query} · {preview.confirmation ? `已确认 ${preview.confirmation.length} 条` : "尚未写入分析证据库"}</p>
      {preview.candidates.length === 0 ? <p>没有候选资料，请调整查询后重新确认获取。</p> : <>
        <button type="button" className="btn" disabled={busy || saving || analyzing || Boolean(preview.confirmation)} onClick={() => setCandidateIds(preview.candidates.filter((item) => item.freshness_status === "FRESH").map((item) => item.candidate_id))}>全选可用候选</button>
        <div className="evidence-list">{preview.candidates.map((item) => <article className="evidence-card" key={item.candidate_id}><label className="consent-line"><input type="checkbox" aria-label={`保存候选 ${item.title}`} checked={candidateIds.includes(item.candidate_id)} disabled={busy || saving || analyzing || Boolean(preview.confirmation) || item.freshness_status !== "FRESH"} onChange={(event) => setCandidateIds((ids) => event.target.checked ? [...ids, item.candidate_id] : ids.filter((id) => id !== item.candidate_id))} /><strong>{item.title}</strong></label><p>{item.source_name} · {item.provider} · {tiers[item.source_tier] ?? "来源未知"}</p><p className="evidence-excerpt">{item.excerpt || "未提供摘录"}</p><p className="hint-text">{freshness[item.freshness_status] ?? "状态未知"} · 观察：{date(item.observed_at)} · 可用：{date(item.available_at)}</p><p className="hint-text">来源定位（不自动访问）：{item.source_locator}</p></article>)}</div>
        {!preview.confirmation ? <div className="button-row"><button type="button" className="btn" disabled={busy || saving || analyzing || candidateIds.length === 0} onClick={() => void confirmPreview(false)}>仅保存所选资料</button><button type="button" className="btn primary" disabled={busy || saving || analyzing || candidateIds.length === 0} onClick={() => void confirmPreview(true)}>保存所选并继续分析</button></div> : <p>所选资料已保存；可在下方调整本次分析证据，再选择组合确认模型调用。</p>}
      </>}
    </Panel> : null}
    <Panel title="4 · 选择本次分析使用的已存资料" description="显示最近 50 条，按入库时间倒序。只分析明确勾选的证据；没有勾选时不会自动补入其他资料。">
      <div className="button-row"><button type="button" className="btn" disabled={!instrument || busy || saving || analyzing || loading} onClick={() => { setError(null); setRevision((value) => value + 1); }}>{loading ? "正在读取资料…" : "刷新资料（不调用供应商）"}</button><button type="button" className="btn primary" disabled={!instrument || busy || saving || analyzing || loading || evidenceIds.length === 0 || evidenceIds.length > 50} onClick={() => setAnalysisOpen(true)}>选择组合并分析</button><a href="/analysis">查看已有报告 →</a></div>
      <p className="hint-text">本次已选 {evidenceIds.length} 条证据（跨来源按证据 ID 去重，上限 50 条）。{evidenceIds.length > 50 ? "超出分析上限，请清空或减少选择；已保存内容不会删除。" : "来源不同不等于独立事实，矛盾资料不会被自动裁决。"}</p>
      <p className="hint-text">已选 {evidenceIds.length} 条。模型调用前固定证据 ID / hash、来源和时间、组合快照与政策标签；过期或跨标的输入会被拒绝，不会自动换成其他材料。搜索摘录不是网页全文或已核实事实。</p>
      <button type="button" className="btn" disabled={busy || saving || analyzing || evidenceIds.length === 0} onClick={() => { evidenceSelectionSequence.current++; setEvidenceIds([]); }}>清空分析选择</button>
      {library ? <p className="hint-text">状态计算时间：{date(library.as_of)}</p> : null}
      {loading ? <p role="status">正在读取资料…</p> : !library ? <EmptyState title={instrument ? "资料尚未读取成功" : "尚未选择标的"} hint="选择标的后读取资料；失败时可点击刷新，不会再次调用供应商。" /> : library.items.length === 0 ? <EmptyState title="这个标的还没有已存资料" hint="先明确选择上方来源，检查公开查询并确认获取。启用档案或测试连接不会自动入库。" /> : <div className="evidence-list">{library.items.map((item) => <article className="evidence-card" key={item.evidence_id}>
        <label className="consent-line"><input type="checkbox" aria-label={`用于本次分析 ${item.title}`} checked={evidenceIds.includes(item.evidence_id)} disabled={busy || saving || analyzing || item.freshness_status !== "FRESH"} onChange={(event) => { evidenceSelectionSequence.current++; setEvidenceIds((ids) => event.target.checked ? [...ids, item.evidence_id] : ids.filter((id) => id !== item.evidence_id)); }} />用于本次分析</label>
        <div className="panel-header"><h3>{item.title}</h3><span className={`pill ${item.freshness_status === "FRESH" ? "valid" : "warn"}`}>{freshness[item.freshness_status] ?? "状态未知"}</span></div>
        <p>{item.source_name} · 获取渠道：{item.provider} · {tiers[item.source_tier] ?? "来源级别未知"}</p>
        <p className="evidence-excerpt">{item.excerpt.slice(0, 260) || "来源未提供摘录；系统不补写正文。"}</p>
        <details><summary>查看已保存摘录与溯源</summary><p className="evidence-excerpt">{item.excerpt || "无摘录"}</p><dl className="evidence-meta"><dt>来源定位（不自动访问）</dt><dd>{item.source_locator}</dd><dt>来源观察时间</dt><dd>{date(item.observed_at)}</dd><dt>资料可用时间</dt><dd>{date(item.available_at)}</dd><dt>本地入库时间</dt><dd>{date(item.ingested_at)}</dd><dt>到期时间</dt><dd>{date(item.expires_at)}</dd><dt>证据 ID</dt><dd>{item.evidence_id}</dd><dt>内容摘要 hash</dt><dd>{item.content_hash}</dd></dl></details>
      </article>)}</div>}
    </Panel>
  </ProductChrome>;
}
