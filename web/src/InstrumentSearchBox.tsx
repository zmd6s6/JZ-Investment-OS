import { useEffect, useState } from "react";

export type InstrumentHit = {
  instrument_id: string;
  market: string;
  symbol: string;
  name: string;
  asset_type: string;
  currency: string;
  sector: string;
};

export function InstrumentSearchBox({
  onSelect,
  placeholder = "搜索代码或名称…",
}: {
  onSelect: (hit: InstrumentHit) => void;
  placeholder?: string;
}) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<InstrumentHit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    const q = query.trim();
    setHits([]);
    setSearched(false);
    if (q.length < 1) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      void fetch(`/api/v1/instruments/search?q=${encodeURIComponent(q)}&limit=8`, { signal: controller.signal })
        .then(async (response) => {
          if (!response.ok) throw new Error("搜索失败");
          return (await response.json()) as InstrumentHit[];
        })
        .then((rows) => { if (!cancelled) { setHits(rows); setSearched(true); } })
        .catch(() => { if (!cancelled) setError("暂时无法搜索目录。可稍后重试，或在下方手动填写代码、名称与市场。"); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 200);
    return () => { cancelled = true; controller.abort(); window.clearTimeout(timer); };
  }, [query]);

  return (
    <div className="instrument-search">
      <input
        value={query}
        placeholder={placeholder}
        onChange={(e) => {
          setQuery(e.target.value);
          setError(null);
        }}
        aria-label="标的搜索"
      />
      {loading ? <p className="hint-text" role="status">正在搜索标的…</p> : null}
      {searched && !loading && hits.length === 0 ? <p className="hint-text" role="status">目录中没有匹配项。可在下方手动填写代码与名称；目录并不代表全部可交易证券。</p> : null}
      {error ? <p className="banner banner-error" role="alert">{error}</p> : null}
      {hits.length > 0 ? (
        <ul className="search-hits">
          {hits.map((hit) => (
            <li key={hit.instrument_id}>
              <button
                type="button"
                onClick={() => {
                  onSelect(hit);
                  setQuery("");
                  setHits([]);
                }}
              >
                <strong>
                  {hit.market} {hit.symbol}
                </strong>
                <span>
                  {hit.name} · {hit.currency}
                  {hit.sector ? ` · ${hit.sector}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
