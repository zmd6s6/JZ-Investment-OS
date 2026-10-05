import { ReactNode, useEffect, useState } from "react";

import { getWriteToken, setWriteToken } from "./writeApi";

const navItems = [
  { href: "/", label: "首页" },
  { href: "/portfolio", label: "资产组合" },
  { href: "/watchlist", label: "观察清单" },
  { href: "/settings", label: "设置与提供方" },
] as const;

export function ProductChrome({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  const [token, setToken] = useState("");
  const [tokenOpen, setTokenOpen] = useState(false);

  useEffect(() => {
    setToken(getWriteToken());
  }, []);

  return (
    <div className="app-frame">
      <header className="app-topbar">
        <a className="brand" href="/">
          <span className="brand-mark">JZ</span>
          <span>
            <strong>Investment OS</strong>
            <small>本地个人投资参谋 · NO AUTO TRADE</small>
          </span>
        </a>
        <nav className="app-nav" aria-label="主导航">
          {navItems.map((item) => {
            const active =
              item.href === "/"
                ? window.location.pathname === "/"
                : window.location.pathname.startsWith(item.href);
            return (
              <a key={item.href} href={item.href} className={active ? "active" : undefined}>
                {item.label}
              </a>
            );
          })}
          <button
            type="button"
            className="token-toggle"
            onClick={() => setTokenOpen((v) => !v)}
            title="写操作令牌"
          >
            {getWriteToken() ? "令牌已配置" : "配置写令牌"}
          </button>
        </nav>
      </header>

      {tokenOpen ? (
        <div className="token-bar">
          <label>
            写入令牌
            <input
              type="password"
              value={token}
              placeholder="与服务端 INVESTMENT_OS_API_WRITE_TOKEN 一致"
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="btn primary"
            onClick={() => {
              setWriteToken(token.trim());
              setTokenOpen(false);
            }}
          >
            保存令牌
          </button>
        </div>
      ) : null}

      <div className="safety-strip">SIMULATION / NO AUTO TRADE · 建议不等于成交 · 风控否决不可覆盖</div>

      <main className="app-main">
        <header className="page-hero">
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <h1>{title}</h1>
            {subtitle ? <p className="page-subtitle">{subtitle}</p> : null}
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}

export function Panel({
  title,
  description,
  actions,
  children,
  tone = "default",
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  tone?: "default" | "muted" | "warn";
}) {
  return (
    <section className={`panel panel-${tone}`}>
      <header className="panel-header">
        <div>
          <h2>{title}</h2>
          {description ? <p>{description}</p> : null}
        </div>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}

export function StatusBanner({
  kind,
  text,
}: {
  kind: "ok" | "error" | "info";
  text: string | null;
}) {
  if (!text) return null;
  return (
    <p className={`banner banner-${kind}`} role="status">
      {text}
    </p>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {hint ? <p>{hint}</p> : null}
    </div>
  );
}

export function Field({
  label,
  value,
  onChange,
  hint,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  placeholder?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      {hint ? <small>{hint}</small> : null}
    </label>
  );
}
