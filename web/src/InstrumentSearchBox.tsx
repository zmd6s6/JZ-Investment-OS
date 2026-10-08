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

  useEffect(() => {
    const q = query.trim();
    if (q.length < 1) {
      setHits([]);
      return;
    }
    const timer = window.setTimeout(() => {
      void fetch(`/api/v1/instruments/search?q=${encodeURIComponent(q)}&limit=8`)
        .then(async (response) => {
          if (!response.ok) throw new Error("搜索失败");
          return (await response.json()) as InstrumentHit[];
        })
        .then(setHits)
        .catch((reason: unknown) =>
          setError(reason instanceof Error ? reason.message : "搜索失败"),
        );
    }, 200);
    return () => window.clearTimeout(timer);
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
      {error ? <p className="banner banner-error">{error}</p> : null}
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
