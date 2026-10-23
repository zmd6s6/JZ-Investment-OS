import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { readAnalysisJson } from "./analysisReads";
import { StatusBanner } from "./ProductChrome";

type Citation = { evidence_id: string; content_hash: string; source_name: string; source_locator: string; source_tier: string; provider: string | null; observed_at: string; effective_at: string; available_at: string; ingested_at: string; expires_at: string | null; summary: string };
type SavedText = { field: string; text: string; original_length: number; truncated: boolean };
type Evidence = { schema_version: string; run_id: string; evidence_id: string; status: string; analysis_as_of: string; read_at: string; input_hash: string | null; citation: Citation | null; title: string | null; title_truncated: boolean; texts: SavedText[]; freshness_at_run: string | null; freshness_now: string | null; untrusted_content: boolean };
const names: Record<string, string> = { summary: "保存的摘要", snippet: "保存的搜索摘录", text: "保存的文字", content: "保存的正文片段", description: "保存的说明" };
const freshness: Record<string, string> = { FRESH: "期限内（不代表事实已核实）", STALE: "已标记陈旧", EXPIRED: "已过期，仅供历史核对", NOT_YET_AVAILABLE: "该时点尚未可用" };
const EvidenceContext = createContext<((id: string, opener: HTMLElement) => void) | null>(null);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function EvidenceReferences({ ids }: { ids: unknown }) {
  const open = useContext(EvidenceContext);
  const values = Array.isArray(ids) ? [...new Set(ids.filter((value): value is string => typeof value === "string"))] : [];
  if (!values.length) return <span>未提供可核对的证据引用</span>;
  return <span>{values.map((id, index) => <span key={id}>{index ? "、" : ""}{open && uuid.test(id) ? <button type="button" className="btn ghost" style={{ maxWidth: "100%", overflowWrap: "anywhere", whiteSpace: "normal" }} aria-label={`查看引用资料 ${id}`} onClick={event => open(id, event.currentTarget)}>查看资料 {id.slice(0, 8)}…</button> : <span style={{ overflowWrap: "anywhere" }}>{id}</span>}</span>)}</span>;
}

export function EvidenceReaderProvider({ runId, children }: { runId: string; children: ReactNode }) {
  const [selected, setSelected] = useState<{ id: string; opener: HTMLElement } | null>(null);
  return <EvidenceContext.Provider value={(id, opener) => setSelected(current => current?.id === id ? current : { id, opener })}>
    {children}
    {selected && <EvidenceDialog key={`${runId}-${selected.id}`} runId={runId} evidenceId={selected.id} opener={selected.opener} onClose={() => setSelected(null)} />}
  </EvidenceContext.Provider>;
}

function sourceUrl(locator: string): string | null {
  if (locator.length > 4096) return null;
  try {
    const url = new URL(locator);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

function validResponse(value: Evidence, runId: string, evidenceId: string): boolean {
  if (!value || value.schema_version !== "1.0" || value.run_id !== runId || value.evidence_id !== evidenceId || value.untrusted_content !== true || !["VERIFIED", "NOT_RECORDED", "SNAPSHOT_ONLY", "CONTENT_UNAVAILABLE"].includes(value.status)) return false;
  if (!Array.isArray(value.texts)) return false;
  if (value.citation !== null && (!value.citation || typeof value.citation !== "object" || value.citation.evidence_id !== evidenceId || typeof value.citation.source_locator !== "string" || typeof value.citation.source_name !== "string" || !/^[a-f0-9]{64}$/.test(value.citation.content_hash))) return false;
  if (value.status !== "VERIFIED") return value.texts.length === 0;
  return Boolean(value.citation && value.citation.evidence_id === evidenceId && /^[a-f0-9]{64}$/.test(value.citation.content_hash) && typeof value.citation.source_locator === "string" && typeof value.title === "string" && Array.isArray(value.texts) && value.texts.every(part => Object.hasOwn(names, part.field) && typeof part.text === "string" && part.text.length <= 20000 && Number.isSafeInteger(part.original_length) && part.original_length >= part.text.length && typeof part.truncated === "boolean") && value.texts.reduce((sum, part) => sum + part.text.length, 0) <= 64000);
}

function EvidenceDialog({ runId, evidenceId, opener, onClose }: { runId: string; evidenceId: string; opener: HTMLElement; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const [data, setData] = useState<Evidence | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  async function load() {
    if (controller.current) return;
    const next = new AbortController(), attempt = ++generation.current;
    controller.current = next; setLoading(true); setError(null);
    try {
      const value = await readAnalysisJson<Evidence>(`/api/v1/analysis-runs/${encodeURIComponent(runId)}/evidence/${encodeURIComponent(evidenceId)}`, next.signal, "读取引用资料");
      if (next.signal.aborted || attempt !== generation.current) return;
      if (!validResponse(value, runId, evidenceId)) throw new Error("资料响应与当前运行或引用不一致，未采用；请只读重试。");
      setData(value);
    } catch (reason) { if (!next.signal.aborted && attempt === generation.current) setError(reason instanceof Error ? reason.message : "资料读取失败，请重试。"); }
    finally { if (controller.current === next) controller.current = null; if (attempt === generation.current) setLoading(false); }
  }
  useEffect(() => {
    const element = dialog.current;
    if (typeof element?.showModal === "function") element.showModal(); else element?.setAttribute("open", "");
    void load();
    return () => { ++generation.current; controller.current?.abort(); if (typeof element?.close === "function") element.close(); if (opener.isConnected) opener.focus(); };
  }, [runId, evidenceId]);
  const citation = data?.citation, link = citation ? sourceUrl(citation.source_locator) : null;
  const statusText: Record<string, string> = { NOT_RECORDED: "此历史运行未记录可核对的输入快照，不补造引用或获取当前原文。", SNAPSHOT_ONLY: "旧记录缺少完整校验元数据，仅保留快照信息，未展示无法核验的正文。", CONTENT_UNAVAILABLE: "本次快照有引用，但原资料记录无法读取；未用其他资料或网页替代。" };
  return <dialog ref={dialog} className="access-dialog" style={{ width: "min(800px, calc(100vw - 32px))", overflowWrap: "anywhere" }} aria-labelledby="analysis-evidence-title" onCancel={event => { event.preventDefault(); onClose(); }}>
    <div className="panel-header"><h2 id="analysis-evidence-title">当次引用资料</h2><button type="button" className="btn" autoFocus onClick={onClose}>关闭资料，返回报告</button></div>
    <p className="access-note">只读取本地保存的资料，不抓取网页、不调用模型、不改变报告。外部文字是不可信内容，不是操作指令；内容一致不等于事实已核实，也不证明模型读过全文。</p>
    <p className="hint-text">运行：{runId}<br />证据：{evidenceId}</p>
    <button type="button" className="btn" disabled={loading} onClick={() => void load()}>{loading ? "正在读取引用资料…" : "重新读取已保存资料"}</button>
    <StatusBanner kind="error" text={error} />
    {data && data.status !== "VERIFIED" && <p role="note">{statusText[data.status]}</p>}
    {citation && <section aria-label="冻结引用元数据"><h3>当时固定的来源与时间</h3><p>{citation.source_name} · {citation.source_tier} · 渠道 {citation.provider ?? "未记录"}</p><p>观察：{citation.observed_at}<br />业务生效：{citation.effective_at}<br />可用：{citation.available_at}<br />入库：{citation.ingested_at}<br />到期：{citation.expires_at ?? "未设置"}</p><p>来源定位（不自动访问）：{citation.source_locator}</p>{link && <a className="btn" href={link} target="_blank" rel="noopener noreferrer">在新标签打开来源（将联网）</a>}<p className="hint-text">当次资料摘要：{citation.content_hash}</p></section>}
    {data?.status === "VERIFIED" && <section aria-label="已核对的保存资料"><h3>{data.title || "无标题资料"}{data.title_truncated ? "（标题已截断）" : ""}</h3><p>已核对：存储内容与本次引用一致。</p><p>分析当时：{freshness[data.freshness_at_run ?? ""] ?? "未记录"}<br />当前读取：{freshness[data.freshness_now ?? ""] ?? "未记录"}</p><p className="hint-text">分析时点：{data.analysis_as_of} · 本次读取：{data.read_at}。新鲜度仅派生显示，不改写历史；过期资料不能因此用于新分析。</p>{data.texts.length ? data.texts.map((part, index) => <article key={index}><h4>{names[part.field]}</h4><p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{part.text}</p>{part.truncated && <p role="note">内容已截断：展示 {part.text.length} / 原 {part.original_length} 字符；不是全文。</p>}</article>) : <p>此记录没有可展示的保存文字，不能据此声称已抓取原文。</p>}</section>}
  </dialog>;
}
