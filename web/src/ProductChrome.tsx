import { ReactNode, useEffect, useState } from "react";

import { getWriteToken, setWriteToken, verifyWriteToken } from "./writeApi";

const navItems = [
  { href: "/", label: "首页" },
  { href: "/portfolio", label: "资产组合" },
  { href: "/watchlist", label: "观察清单" },
  { href: "/analysis", label: "分析运行" },
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
  const [checking, setChecking] = useState(false);
  const [verified, setVerified] = useState(false);
  const [tokenMessage, setTokenMessage] = useState<string | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);

  useEffect(() => {
    setToken(getWriteToken());
  }, []);

  async function saveToken() {
    if (checking) return;
    setChecking(true);
    setTokenError(null);
    setTokenMessage(null);
    try {
      await verifyWriteToken(token);
      if (!setWriteToken(token.trim()))
        throw new Error("浏览器无法保存当前会话。请允许此站点使用会话存储，再验证并保存。");
      setVerified(true);
      setTokenOpen(false);
      setTokenMessage("本地访问已验证，本标签页可进行保存操作。供应商凭据无需重复填写。");
    } catch (reason) {
      setVerified(false);
      setTokenError(reason instanceof Error ? reason.message : "访问验证失败，请重试。");
    } finally {
      setChecking(false);
    }
  }

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
            title="验证或更新本系统的访问令牌；不是供应商 API Key"
          >
            {verified ? "本地访问已验证" : getWriteToken() ? "访问令牌已保存" : "配置写令牌"}
          </button>
        </nav>
      </header>

      {tokenOpen ? (
        <div className="token-bar">
          <label>
            写入令牌
            <input
              type="password"
              disabled={checking}
              value={token}
              placeholder="与服务端 INVESTMENT_OS_API_WRITE_TOKEN 一致"
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
          <p className="hint-text">本系统的操作通行证，与 DeepSeek / 博查 / Tushare 凭据不同。验证不会修改数据或调用供应商。</p>
          <button
            type="button"
            className="btn primary"
            disabled={checking}
            onClick={() => void saveToken()}
          >
            {checking ? "正在验证…" : "验证并保存令牌"}
          </button>
        </div>
      ) : null}
      {tokenError ? <p role="alert" className="banner banner-error">{tokenError}</p> : null}
      {tokenMessage ? <p role="status" className="banner banner-ok">{tokenMessage}</p> : null}

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
