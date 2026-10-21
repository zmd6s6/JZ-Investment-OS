import { ReactNode, useEffect, useRef, useState } from "react";

import { getWriteToken, setWriteToken, verifyWriteToken } from "./writeApi";
import { requestAccessSetup, UsageGuide } from "./UsageGuide";
import { useLocalAccess } from "./LocalAccess";

const navItems = [
  { href: "/", label: "首页" },
  { href: "/portfolio", label: "资产组合" },
  { href: "/watchlist", label: "观察清单" },
  { href: "/research", label: "研究资料" },
  { href: "/thesis", label: "投资逻辑" },
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
  const [showToken, setShowToken] = useState(false);
  const accessDialog = useRef<HTMLDialogElement>(null);
  const tokenInput = useRef<HTMLInputElement>(null);
  const submitting = useRef(false);
  const access = useLocalAccess();
  const [accessInfo, setAccessInfo] = useState(false);

  function openAccess() {
    if (access.local) { setAccessInfo(true); return; }
    setToken(getWriteToken());
    setShowToken(false);
    setTokenError(null);
    setTokenOpen(true);
  }

  useEffect(() => {
    window.addEventListener("investment-os:configure-access", openAccess);
    return () => window.removeEventListener("investment-os:configure-access", openAccess);
  }, [access.local]);

  useEffect(() => {
    const dialog = accessDialog.current;
    if (!tokenOpen || !dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    tokenInput.current?.focus();
    return () => { if (typeof dialog.close === "function") dialog.close(); };
  }, [tokenOpen]);

  function closeAccess() {
    if (submitting.current) return;
    setTokenOpen(false);
    setToken("");
    setShowToken(false);
  }

  async function saveToken() {
    if (submitting.current) return;
    submitting.current = true;
    setChecking(true);
    setTokenError(null);
    setTokenMessage(null);
    try {
      await verifyWriteToken(token);
      if (!setWriteToken(token.trim()))
        throw new Error("浏览器无法保存当前会话。请允许此站点使用会话存储，再验证并保存。");
      setVerified(true);
      window.dispatchEvent(new Event("investment-os:access-verified"));
      setTokenOpen(false);
      setToken("");
      setShowToken(false);
      setTokenMessage("本地访问已验证。请重新点击刚才的保存操作，系统不会自动重发；供应商凭据无需重复填写。");
    } catch (reason) {
      setVerified(false);
      setTokenError(reason instanceof Error ? reason.message : "访问验证失败，请重试。");
    } finally {
      submitting.current = false;
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
          {access.local ? <button type="button" className="token-toggle" onClick={() => setAccessInfo((value) => !value)}>本机已连接</button> : <button
            type="button"
            className="token-toggle"
            onClick={openAccess}
            title="验证或更新本系统的访问令牌；不是供应商 API Key"
          >
            {verified ? "本地访问已验证" : getWriteToken() ? "访问令牌已保存" : "配置写令牌"}
          </button>}
        </nav>
      </header>

      {accessInfo ? <section className="local-access-info"><strong>本机访问已建立</strong><p>当前浏览器保持会话，无需填写开发令牌。手动断开后，可双击本地启动入口重新连接；不会删除持仓或供应商凭据。</p><button type="button" className="btn" disabled={checking} onClick={() => setAccessInfo(false)}>返回工作台</button> <button type="button" className="btn" disabled={checking} onClick={async () => { setChecking(true); try { await access.logout(); } catch { setTokenMessage("暂时无法断开本机访问，请稍后重试。"); } finally { setChecking(false); } }}>断开本机访问</button></section> : null}
      {!access.local && tokenOpen ? (
        <dialog ref={accessDialog} className="access-dialog" aria-labelledby="access-title" aria-describedby="access-description" onCancel={(event) => { event.preventDefault(); closeAccess(); }}>
          <form onSubmit={(event) => { event.preventDefault(); void saveToken(); }}>
          <div className="panel-header">
            <div><p className="eyebrow">本机操作授权</p><h2 id="access-title">配置本地访问</h2></div>
            <button type="button" className="btn ghost" disabled={checking} onClick={closeAccess}>关闭</button>
          </div>
          <p id="access-description">此令牌用于在本系统保存持仓和配置。它不是 DeepSeek / 博查 / Tushare 的 API Key。</p>
          <label className="field" htmlFor="local-access-token">写入令牌</label>
          <div className="access-input-row">
            <input
              id="local-access-token"
              ref={tokenInput}
              type={showToken ? "text" : "password"}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              disabled={checking}
              value={token}
              aria-invalid={Boolean(tokenError)}
              aria-describedby="access-help"
              placeholder="粘贴服务端配置的访问令牌"
              onChange={(e) => setToken(e.target.value)}
            />
            <button type="button" className="btn" aria-pressed={showToken} onClick={() => setShowToken((value) => !value)}>{showToken ? "隐藏" : "显示"}</button>
          </div>
          <p id="access-help" className="hint-text">由部署者在服务端配置（INVESTMENT_OS_API_WRITE_TOKEN）。随机填写不会生效；不知道时请向部署者获取。仅保存在当前标签页会话，不回显服务端令牌。</p>
          {tokenError ? <p role="alert" className="banner banner-error">{tokenError}</p> : null}
          <p className="access-note">验证不修改业务数据、不调用供应商，也不会消耗模型额度。</p>
          <div className="dialog-actions">
          <button type="button" className="btn" disabled={checking} onClick={closeAccess}>取消</button>
          <button
            type="submit"
            className="btn primary"
            disabled={checking}
          >
            {checking ? "正在验证…" : "验证并保存令牌"}
          </button>
          </div>
          </form>
        </dialog>
      ) : null}

      <div className="safety-strip">SIMULATION / NO AUTO TRADE · 建议不等于成交 · 风控否决不可覆盖</div>

      <main className="app-main">
        {tokenMessage ? <p role="status" className="banner banner-ok">{tokenMessage}</p> : null}
        <header className="page-hero">
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <h1>{title}</h1>
            {subtitle ? <p className="page-subtitle">{subtitle}</p> : null}
          </div>
        </header>
        <UsageGuide onAccess={openAccess} local={access.local} expanded={window.location.pathname === "/"} />
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
  const [accessRepaired, setAccessRepaired] = useState(false);
  useEffect(() => {
    const markRepaired = () => setAccessRepaired(true);
    window.addEventListener("investment-os:access-verified", markRepaired);
    return () => window.removeEventListener("investment-os:access-verified", markRepaired);
  }, []);
  useEffect(() => setAccessRepaired(false), [text]);
  if (!text) return null;
  if (kind === "error" && text.includes("令牌") && accessRepaired) return null;
  return (
    <p className={`banner banner-${kind}`} role={kind === "error" ? "alert" : "status"}>
      {text}
      {kind === "error" && text.includes("令牌") ? <button type="button" className="feedback-action" onClick={requestAccessSetup}>配置本地访问 →</button> : null}
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
