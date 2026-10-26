import { useEffect, useRef, useState } from "react";
import { readAnalysisJson } from "./analysisReads";

export type MarketSelection = { market_profile_ids: string[]; market_configuration_hash?: string; include_market_history?: true };
type Profile = { profile_id: string; name: string; provider_type: string };
type Options = { configuration_hash: string; profiles: Profile[] };

export function AnalysisMarketChoices({ onChange }: { onChange: (choice: MarketSelection) => void }) {
  const [options, setOptions] = useState<Options | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [history, setHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const notify = useRef(onChange); notify.current = onChange;
  useEffect(() => {
    const controller = new AbortController(); let alive = true;
    setOptions(null); setSelected([]); setHistory(false); setError(null); notify.current({ market_profile_ids: [] });
    void readAnalysisJson<Options>("/api/v1/analysis-market-options", controller.signal, "行情配置读取")
      .then((value) => {
        if (!value || !Array.isArray(value.profiles) || !/^[0-9a-f]{64}$/.test(value.configuration_hash)) throw new Error("行情配置响应不完整。");
        if (alive) setOptions(value);
      }).catch((reason) => { if (alive) setError(reason instanceof Error ? reason.message : "行情配置读取失败。"); });
    return () => { alive = false; controller.abort(); };
  }, [revision]);
  function choose(next: string[], withHistory = history) {
    setSelected(next);
    if (!next.length) setHistory(false);
    notify.current({ market_profile_ids: next, ...(next.length ? { market_configuration_hash: options?.configuration_hash, ...(withHistory ? { include_market_history: true as const } : {}) } : {}) });
  }
  function move(index: number, offset: number) {
    const next = [...selected];
    [next[index], next[index + offset]] = [next[index + offset], next[index]];
    choose(next);
  }
  return <section aria-label="本次行情来源与顺序">
    <h3>本次行情来源与顺序</h3>
    <p className="hint-text">默认不读取行情，也不要求填写 Tushare Token。可以继续研究，但缺价时不计算完整估值或买入数量。博查是研究文字来源，不在这里选。</p>
    {!options && !error ? <p role="status">正在读取可选行情档案…</p> : null}
    {error ? <p className="context-note">{error} 可不读取行情继续，或重新读取配置。</p> : null}
    {options?.profiles.length === 0 ? <p className="context-note">暂无已启用、有凭据引用且受支持的行情档案。<a href="/settings#data">按需配置行情源 →</a></p> : null}
    {options?.profiles.map((p) => <label className="checkbox-row" key={p.profile_id}><input type="checkbox" checked={selected.includes(p.profile_id)} disabled={!selected.includes(p.profile_id) && selected.length >= 10} onChange={(event) => choose(event.target.checked ? [...selected, p.profile_id] : selected.filter((id) => id !== p.profile_id))} />使用行情源 {p.name} · {p.provider_type}</label>)}
    {selected.length ? <><p>按以下明确顺序尝试；仅在前一源失败或缺价时读取下一项，可能产生供应商费用。未选来源和合成价格不会加入。</p><ol className="tip-list">{selected.map((id, index) => <li key={id}>{options?.profiles.find((p) => p.profile_id === id)?.name}<div className="button-row"><button type="button" className="btn ghost" aria-label={`上移 ${options?.profiles.find((p) => p.profile_id === id)?.name}`} disabled={index === 0} onClick={() => move(index, -1)}>上移</button><button type="button" className="btn ghost" aria-label={`下移 ${options?.profiles.find((p) => p.profile_id === id)?.name}`} disabled={index === selected.length - 1} onClick={() => move(index, 1)}>下移</button></div></li>)}</ol><button type="button" className="btn ghost" onClick={() => choose([])}>清空行情选择</button></> : <p>本次选择：不读取行情，不会自动调用已启用的行情源。</p>}
    <label className="checkbox-row"><input type="checkbox" aria-label="读取目标历史日线" disabled={!selected.length} checked={history} onChange={event => { setHistory(event.target.checked); choose(selected, event.target.checked); }} />读取目标历史日线（可选，默认关闭）</label>
    <p className="hint-text">勾选后，仅对目标标的在报价成功的同一源额外查询一次：参考日及前89自然日，最多90条，计算最近20条观测的日收益样本波动与均量。可能增加供应商费用和等待；不查询其他持仓历史，历史失败不自动换源补齐。不是年化风险、回测或可交易容量；未勾选不查询历史。</p>
    <button type="button" className="btn ghost" onClick={() => setRevision((v) => v + 1)}>重新读取行情配置</button>
  </section>;
}
