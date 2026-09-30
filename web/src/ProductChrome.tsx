import { ReactNode } from "react";

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
        </nav>
      </header>

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
