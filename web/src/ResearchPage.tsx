import { FormEvent, useEffect, useRef, useState } from "react";
import { AnalysisStartDialog } from "./AnalysisStartDialog";
import { InstrumentHit, InstrumentSearchBox } from "./InstrumentSearchBox";
import { EmptyState, Panel, ProductChrome, StatusBanner } from "./ProductChrome";
import { apiFetch, readApiError } from "./writeApi";

type Profile = { id: string; name: string; provider_type: string; enabled: boolean; credential_configured: boolean; retention_days: number };
type EvidenceItem = { evidence_id: string; source_name: string; source_locator: string; source_tier: string; provider: string; evidence_type: string; title: string; excerpt: string; observed_at: string; available_at: string; ingested_at: string; expires_at: string | null; freshness_status: string; content_hash: string };
type EvidenceList = { as_of: string; items: EvidenceItem[] };
const freshness: Record<string, string> = { FRESH: "期限内资料（不代表事实已核实）", STALE: "陈旧资料", EXPIRED: "已过期 · 不用于新分析", NOT_YET_AVAILABLE: "尚未可用 · 不用于新分析" };
const tiers: Record<string, string> = { PRIMARY: "一手来源", REPUTABLE_SECONDARY: "可信二手来源", OTHER: "其他来源 / 搜索线索" };
function date(value: string | null) { return value ? `${value.replace("T", " ").replace("+00:00", "Z")}（UTC）` : "未设定"; }
async function read<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await apiFetch(url, { signal });
  if (!response.ok) throw new Error(await readApiError(response));
  return response.json() as Promise<T>;
}

export function ResearchPage() {
  const [instrument, setInstrument] = useState<InstrumentHit | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [profileId, setProfileId] = useState("");
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
  const readSequence = useRef(0);
  const selectionSequence = useRef(0);
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
    const id = new URLSearchParams(window.location.search).get("instrument_id");
    if (id) void read<InstrumentHit>(`/api/v1/instruments/${encodeURIComponent(id)}`).then((hit) => {
      if (active && sequence === selectionSequence.current) { setInstrument(hit); setQuery(`${hit.name} ${hit.symbol} 最新公告`); }
    }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "无法读取标的。"); });
    return () => { active = false; };
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
    setQuery(`${hit.name} ${hit.symbol} 最新公告`);
    window.history.replaceState(null, "", `/research?instrument_id=${encodeURIComponent(hit.instrument_id)}`);
  }
  const selected = profiles.find((item) => item.id === profileId);
  const usable = selected?.enabled && selected.credential_configured && types.includes(selected.provider_type);

  async function collect(event: FormEvent) {
    event.preventDefault();
    if (submitting.current || !instrument || !usable || !consent || !query.trim()) return;
    submitting.current = true; setBusy(true); setError(null); setMessage(null);
    const target = instrument;
    try {
      // Do not timeout/replay a paid request automatically: a lost response may still have committed.
      const response = await apiFetch(`/api/v1/research/providers/${encodeURIComponent(profileId)}/fetch`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), as_of: new Date().toISOString(), instrument_ids: [target.instrument_id], max_results: count }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const result = await response.json() as { results: { evidence_id: string; reused: boolean }[] };
      const reused = result.results.filter((item) => item.reused).length;
      setMessage(result.results.length ? `资料获取完成：${result.results.length - reused} 条新入库，${reused} 条复用。尚未调用模型，请查看下方资料后再分析。` : "本次查询没有结果；未创建证据、未调用模型。可修改公开查询后重新确认。");
      setConsent(false); setRevision((value) => value + 1);
    } catch (reason) {
      setError(`${reason instanceof Error ? reason.message : "资料获取失败。"} 若响应中断，可能已有部分资料入库；先刷新资料核对，不要直接重复付费请求。系统不会切换其他数据源。`);
    } finally { submitting.current = false; setBusy(false); }
  }

  async function analyze(portfolioId: string) {
    if (submitting.current || !instrument) return;
    submitting.current = true; setAnalyzing(true); setAnalysisOpen(false); setError(null);
    try {
      const response = await apiFetch("/api/v1/analysis-runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instrument_id: instrument.instrument_id, portfolio_id: portfolioId, source: "RESEARCH" }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      try { sessionStorage.setItem("selected_portfolio_id", portfolioId); } catch { /* optional */ }
      window.location.href = "/analysis";
    } catch (reason) { setError(reason instanceof Error ? reason.message : "分析未完成，请先查看运行列表。"); }
    finally { submitting.current = false; setAnalyzing(false); }
  }

  return <ProductChrome eyebrow="证据优先" title="研究资料" subtitle="先选标的和来源、核对公开查询，再获取资料。搜索线索不是行情，也不是已核实的事实。">
    {analysisOpen && instrument ? <AnalysisStartDialog label={`${instrument.symbol} ${instrument.name}`} onCancel={() => setAnalysisOpen(false)} onConfirm={(id) => void analyze(id)} /> : null}
    <div className="action-feedback"><StatusBanner kind="error" text={error} /><StatusBanner kind="ok" text={message} /><StatusBanner kind="info" text={busy ? "正在向所选数据源查询并保存资料… 请保留页面，不要重复点击。" : analyzing ? "投资团队正在分析，请保留页面。完成后打开报告。" : null} /></div>
    <Panel title="1 · 选择研究对象" description="从持仓或观察清单进入会自动带入标的；此处也可搜索本地目录。">
      {!busy && !analyzing ? <InstrumentSearchBox onSelect={selectInstrument} /> : null}
      {instrument ? <p className="context-note">当前标的：<strong>{instrument.name} · {instrument.market} {instrument.symbol}</strong>。资料关联不等于证明文章一定相关，请核对内容。</p> : <p>请选择标的。目录为空时，先到<a href="/watchlist">观察清单</a>添加研究对象。</p>}
    </Panel>
    <Panel title="2 · 明确获取来源" description="只调用本次选中的来源，不会自动启用、后台同步或失败换源。无需 Tushare Token。">
      {configLoading ? <p role="status">正在读取数据源…</p> : null}
      {!configLoading && !profiles.some((item) => item.enabled && item.credential_configured && types.includes(item.provider_type)) ? <p className="context-note">尚无可用研究来源。前往<a href="/settings#data">设置与提供方</a>配置、授权并启用研究档案；行情档案不能替代新闻研究来源。</p> : null}
      <form className="form-grid" onSubmit={(event) => void collect(event)}>
        <label className="field"><span>研究数据源</span><select required value={profileId} disabled={busy || analyzing || configLoading} onChange={(event) => { setProfileId(event.target.value); setConsent(false); }}><option value="">请明确选择数据源</option>{profiles.map((item) => <option key={item.id} value={item.id} disabled={!item.enabled || !item.credential_configured || !types.includes(item.provider_type)}>{item.name} · {item.provider_type}{!types.includes(item.provider_type) ? "（不支持研究检索）" : !item.enabled ? "（未启用）" : !item.credential_configured ? "（未配置凭据）" : ""}</option>)}</select></label>
        <label className="field"><span>公开查询内容</span><input value={query} required maxLength={1000} disabled={busy || analyzing} onChange={(event) => { setQuery(event.target.value); setConsent(false); }} placeholder="公司名称 代码 最新公告" /></label>
        <label className="field"><span>最多结果数</span><select value={count} disabled={busy || analyzing} onChange={(event) => { setCount(Number(event.target.value)); setConsent(false); }}>{[1, 5, 10, 20].map((value) => <option key={value} value={value}>{value} 条</option>)}</select></label>
        <div className="full-span"><p className="hint-text">查询会发给所选供应商，可能计费；不会发送持仓、成本或现金。仅输入公开信息。新资料按所选档案保留期限保存{selected ? `（${selected.retention_days} 天）` : ""}，历史不原地覆盖。</p><label className="consent-line"><input type="checkbox" checked={consent} disabled={busy || analyzing} onChange={(event) => setConsent(event.target.checked)} />我确认查询仅含公开信息，允许调用所选来源并将结果入库</label></div>
        <button className="btn primary" type="submit" disabled={busy || analyzing || !instrument || !usable || !consent || !query.trim()}>{busy ? "正在获取并保存…" : "确认获取并入库"}</button>
      </form>
    </Panel>
    <Panel title="3 · 核对已存资料，再分析" description="显示最近 50 条，按入库时间倒序。搜索结果仅保留供应商返回的摘录，不代表已抓取或核验网页全文。">
      <div className="button-row"><button type="button" className="btn" disabled={!instrument || busy || analyzing || loading} onClick={() => { setError(null); setRevision((value) => value + 1); }}>{loading ? "正在读取资料…" : "刷新资料（不调用供应商）"}</button><button type="button" className="btn primary" disabled={!instrument || busy || analyzing || loading || !library?.items.some((item) => item.freshness_status === "FRESH")} onClick={() => setAnalysisOpen(true)}>选择组合并分析</button><a href="/analysis">查看已有报告 →</a></div>
      <p className="hint-text">分析读取此标的当时所有可用的已存证据，不是只读本次查询；这里只准备材料，不自动启动模型。过期和未来资料保留展示，不用于新分析。缺少资料时请先获取；陈旧资料需核实后补充。</p>
      {library ? <p className="hint-text">状态计算时间：{date(library.as_of)}</p> : null}
      {loading ? <p role="status">正在读取资料…</p> : !library ? <EmptyState title={instrument ? "资料尚未读取成功" : "尚未选择标的"} hint="选择标的后读取资料；失败时可点击刷新，不会再次调用供应商。" /> : library.items.length === 0 ? <EmptyState title="这个标的还没有已存资料" hint="先明确选择上方来源，检查公开查询并确认获取。启用档案或测试连接不会自动入库。" /> : <div className="evidence-list">{library.items.map((item) => <article className="evidence-card" key={item.evidence_id}>
        <div className="panel-header"><h3>{item.title}</h3><span className={`pill ${item.freshness_status === "FRESH" ? "valid" : "warn"}`}>{freshness[item.freshness_status] ?? "状态未知"}</span></div>
        <p>{item.source_name} · 获取渠道：{item.provider} · {tiers[item.source_tier] ?? "来源级别未知"}</p>
        <p className="evidence-excerpt">{item.excerpt.slice(0, 260) || "来源未提供摘录；系统不补写正文。"}</p>
        <details><summary>查看已保存摘录与溯源</summary><p className="evidence-excerpt">{item.excerpt || "无摘录"}</p><dl className="evidence-meta"><dt>来源定位（不自动访问）</dt><dd>{item.source_locator}</dd><dt>来源观察时间</dt><dd>{date(item.observed_at)}</dd><dt>资料可用时间</dt><dd>{date(item.available_at)}</dd><dt>本地入库时间</dt><dd>{date(item.ingested_at)}</dd><dt>到期时间</dt><dd>{date(item.expires_at)}</dd><dt>证据 ID</dt><dd>{item.evidence_id}</dd><dt>内容摘要 hash</dt><dd>{item.content_hash}</dd></dl></details>
      </article>)}</div>}
    </Panel>
  </ProductChrome>;
}
