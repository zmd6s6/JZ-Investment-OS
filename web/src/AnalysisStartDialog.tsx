import { useEffect, useRef, useState } from "react";
import { readAnalysisJson } from "./analysisReads";
import type { AnalysisModelSelection } from "./analysisSubmission";
import { tokenPriceLabel } from "./analysisLabels";

type PortfolioChoice = { portfolio_id: string; name: string; base_currency: string };
type ModelProfile = { profile_id: string; name: string; model_name: string; pricing_version: string | null; pricing_currency: string | null; input_token_price: string | null; output_token_price: string | null };
type ModelOptions = { configuration_hash: string; profiles: ModelProfile[]; default_bindings: { role: string; profile: ModelProfile }[]; missing_roles: string[] };
const roles: Record<string, string> = { MACRO: "宏观", INDUSTRY: "行业", FUNDAMENTAL: "基本面", MARKET_QUANT: "市场量化", EVENT: "事件", DEVILS_ADVOCATE: "反方", PORTFOLIO: "组合经理", RISK: "风险经理" };

export function AnalysisStartDialog({ label, portfolio, evidenceCount, onCancel, onConfirm }: {
  label: string;
  portfolio?: PortfolioChoice;
  evidenceCount?: number;
  onCancel: () => void;
  onConfirm: (portfolioId: string, models: AnalysisModelSelection) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [choices, setChoices] = useState<PortfolioChoice[]>(portfolio ? [portfolio] : []);
  const [selectedId, setSelectedId] = useState(portfolio?.portfolio_id ?? "");
  const [loading, setLoading] = useState(!portfolio);
  const [error, setError] = useState<string | null>(null);
  const [models, setModels] = useState<ModelOptions | null>(null);
  const [modelId, setModelId] = useState("");
  const [modelError, setModelError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const element = dialog.current;
    if (typeof element?.showModal === "function") element.showModal();
    else element?.setAttribute("open", "");
    return () => { if (typeof element?.close === "function") element.close(); };
  }, []);

  useEffect(() => {
    if (portfolio) return;
    let cancelled = false;
    void (async () => {
      try {
        const rows = await readAnalysisJson<PortfolioChoice[]>("/api/v1/portfolios");
        if (!cancelled) setChoices(rows);
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "读取组合失败，请关闭后重试。");
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [portfolio]);

  useEffect(() => {
    const controller = new AbortController();
    let alive = true;
    setModels(null); setModelError(null); setModelId("");
    void readAnalysisJson<ModelOptions>("/api/v1/analysis-model-options", controller.signal, "模型配置读取")
      .then((value) => {
        if (!value || !Array.isArray(value.profiles) || !Array.isArray(value.default_bindings) || !Array.isArray(value.missing_roles) || !/^[0-9a-f]{64}$/.test(value.configuration_hash)) throw new Error("模型配置响应不完整，请重试读取。");
        if (alive) setModels(value);
      }).catch((reason) => { if (alive) setModelError(reason instanceof Error ? reason.message : "模型配置读取失败。"); });
    return () => { alive = false; controller.abort(); };
  }, [revision]);

  const selectedModels = modelId ? models?.profiles.filter((p) => p.profile_id === modelId) ?? [] : models?.default_bindings.map((b) => b.profile) ?? [];
  const ready = Boolean(models && (modelId ? selectedModels.length === 1 : models.missing_roles.length === 0 && models.default_bindings.length === 8));

  return (
    <dialog ref={dialog} className="access-dialog" aria-labelledby="analysis-start-title" onCancel={(event) => { event.preventDefault(); onCancel(); }}>
      <form onSubmit={(event) => { event.preventDefault(); if (selectedId && !loading && ready && models) onConfirm(selectedId, { ...(modelId ? { model_profile_id: modelId } : {}), model_configuration_hash: models.configuration_hash }); }}>
        <div className="panel-header"><div><p className="eyebrow">启动前确认</p><h2 id="analysis-start-title">分析 {label}</h2></div><button type="button" className="btn ghost" onClick={onCancel}>关闭</button></div>
        <label className="field"><span>分析所用组合</span><select value={selectedId} disabled={Boolean(portfolio) || loading} onChange={(event) => setSelectedId(event.target.value)} required><option value="">请选择组合上下文</option>{choices.map((choice) => <option key={choice.portfolio_id} value={choice.portfolio_id}>{choice.name} · {choice.base_currency}</option>)}</select></label>
        {loading ? <p role="status">正在读取组合…</p> : null}
        {error ? <p role="alert" className="banner banner-error">{error}</p> : null}
        <label className="field"><span>本次分析模型</span><select value={modelId} disabled={!models} onChange={(event) => setModelId(event.target.value)}><option value="">按下方角色映射（本次固定）</option>{models?.profiles.map((p) => <option key={p.profile_id} value={p.profile_id}>{p.name} · {p.model_name}（用于全部八角色）</option>)}</select></label>
        {!models && !modelError ? <p role="status">正在读取模型与定价配置…</p> : null}
        {modelError ? <p role="alert" className="banner banner-error">{modelError}</p> : null}
        <button type="button" className="btn ghost" onClick={() => setRevision((v) => v + 1)}>重新读取模型配置</button>
        {models && !modelId && models.missing_roles.length ? <p role="alert">尚未配置：{models.missing_roles.map((r) => roles[r] ?? r).join("、")}。可选择一个模型用于本次全部角色，或到设置完成映射。</p> : null}
        {models ? <details><summary>核对本次模型与定价</summary><ul className="tip-list">{modelId ? selectedModels.map((p) => <li key={p.profile_id}>全部八角色：{p.name} · {p.model_name}；定价版本 {p.pricing_version ?? "未配置"}；币种 {p.pricing_currency ?? "未配置"}；每 Token 输入 {tokenPriceLabel(p.input_token_price)} / 输出 {tokenPriceLabel(p.output_token_price)}</li>) : models.default_bindings.map((b) => <li key={b.role}>{roles[b.role] ?? b.role}：{b.profile.name} · {b.profile.model_name}；定价版本 {b.profile.pricing_version ?? "未配置"}；币种 {b.profile.pricing_currency ?? "未配置"}；每 Token 输入 {tokenPriceLabel(b.profile.input_token_price)} / 输出 {tokenPriceLabel(b.profile.output_token_price)}</li>)}</ul></details> : null}
        {!loading && choices.length === 0 ? <p className="context-note">分析需要现金与持仓上下文。<a href="/portfolio">先创建一个组合 →</a>，不必持有此标的。</p> : null}
        <ul className="tip-list">
          <li>只使用本次确认的模型，可能调用付费模型；受已配置预算约束。任务固定模型档案与定价摘要，修改映射不会换模型；档案修改或停用将明确拒绝，不自动回退。本次选择不修改全局设置。<a href="/settings#models">检查模型与预算</a>。</li>
          <li>{evidenceCount !== undefined ? `本次只使用你勾选的 ${evidenceCount} 条证据，并冻结输入快照；不会偷偷补入其他资料。` : "本轮读取该标的已入库证据，不会自动抓取新闻。缺证据会失败关闭，不编造材料。"}可先去<a href="/research">研究资料</a>核对内容。</li>
          <li>确认后任务进入后台队列，自动打开运行详情；可离开、刷新再回来。取消在阶段边界生效，已发出的上游调用可能仍完成、修复并计费。</li>
          <li>缺行情可阅读研究意见，但不能据此计算完整估值或买入数量；结果不产生订单。</li>
        </ul>
        <div className="dialog-actions"><button type="button" className="btn" onClick={onCancel}>暂不分析</button><button type="submit" className="btn primary" disabled={loading || !selectedId || Boolean(error) || !ready}>确认启动分析</button></div>
      </form>
    </dialog>
  );
}
