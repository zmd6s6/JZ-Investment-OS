import { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { apiFetch, readApiError, setApiAuthMode, setWriteToken } from "./writeApi";

type AccessState = { mode: "bearer" | "local_session"; authenticated: boolean; expires_at: number | null };
const AccessContext = createContext<{ local: boolean; logout: () => Promise<void> }>({ local: false, logout: async () => {} });
export const useLocalAccess = () => useContext(AccessContext);

export function LocalAccessBoundary({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AccessState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const started = useRef(false);
  const requestSequence = useRef(0);

  async function refresh() {
    const sequence = ++requestSequence.current;
    setLoading(true); setError(null);
    // Fragment never reaches the HTTP server. Remove it before sending any request.
    const fragment = window.location.hash;
    const code = fragment.startsWith("#local-pair=") ? fragment.slice("#local-pair=".length) : null;
    if (code !== null) window.history.replaceState(null, "", window.location.pathname + window.location.search);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      if (code !== null) {
        const paired = await fetch("/api/v1/auth/pair", {
          method: "POST", credentials: "same-origin", cache: "no-store",
          headers: { "Content-Type": "application/json", "X-Investment-OS": "local-ui" },
          body: JSON.stringify({ code }),
          signal: controller.signal,
        });
        if (!paired.ok) throw new Error("本机连接链接已失效或已使用。请重新双击「打开投资工作台.cmd」，无需填写任何令牌。");
      }
      const response = await fetch("/api/v1/auth/session", { credentials: "same-origin", cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error("无法读取本机访问状态。请从本地启动入口重试，并确认地址和服务正常。");
      const next = await response.json() as AccessState;
      if (!["bearer", "local_session"].includes(next.mode) || typeof next.authenticated !== "boolean") throw new Error("本机访问配置暂不可用，请检查服务版本后重试。");
      if (sequence !== requestSequence.current) return;
      setApiAuthMode(next.mode);
      if (next.mode === "local_session") setWriteToken("");
      setState(next);
    } catch (reason) {
      if (sequence === requestSequence.current) setError(controller.signal.aborted ? "本机连接检查超时。请确认 Docker 已启动，再检查连接；不要更换供应商密钥。" : reason instanceof TypeError ? "暂时无法连接本机服务，请检查 Docker 是否已启动。" : reason instanceof Error ? reason.message : "暂时无法连接本机服务，请检查 Docker 是否已启动。");
    } finally { window.clearTimeout(timeout); if (sequence === requestSequence.current) setLoading(false); }
  }

  useEffect(() => {
    if (!started.current) { started.current = true; void refresh(); }
    const expired = () => { requestSequence.current++; setLoading(false); setState((current) => current ? { ...current, authenticated: false } : current); setError("本机访问已过期或被断开。重新从本地启动入口打开即可，无需更换供应商 Key。"); };
    const pairLink = () => { if (window.location.hash.startsWith("#local-pair=")) void refresh(); };
    window.addEventListener("investment-os:session-expired", expired);
    window.addEventListener("hashchange", pairLink);
    return () => { window.removeEventListener("investment-os:session-expired", expired); window.removeEventListener("hashchange", pairLink); };
  }, []);

  async function logout() {
    const response = await apiFetch("/api/v1/auth/logout", { method: "POST" });
    if (!response.ok) throw new Error(await readApiError(response));
    setState((current) => current ? { ...current, authenticated: false } : current);
  }

  if (state && (state.mode === "bearer" || state.authenticated)) {
    return <AccessContext.Provider value={{ local: state.mode === "local_session", logout }}>{children}</AccessContext.Provider>;
  }
  return (
    <div className="app-frame"><header className="app-topbar"><a className="brand" href="/"><span className="brand-mark">JZ</span><strong>Investment OS</strong></a><span className="hint-text">仅本机使用 · 不自动交易</span></header>
      <main className="app-main local-welcome">
        <p className="eyebrow">本机工作台</p>
        <h1>{loading ? "正在连接这台电脑…" : "从本地入口打开，即可开始"}</h1>
        {error ? <p className="banner banner-error" role="alert">{error}</p> : null}
        <section className="panel"><h2>不需要填写访问令牌</h2><p>首次使用请双击项目目录中的 <strong>打开投资工作台.cmd</strong>。启动器会打开浏览器并自动完成本机配对。</p><p className="hint-text">配对后同一浏览器可保持连接 30 天，刷新或新标签页不必重复配置。清理 Cookie、会话过期或手动断开后，重新打开本地入口即可。</p><p className="hint-text">文件位置：项目根目录（与 README.md 同级）。这只授权使用本机产品，不会调用模型或批准交易。</p></section>
        <button type="button" className="btn" disabled={loading} onClick={() => void refresh()}>{loading ? "正在检查…" : "已从本地入口打开？重新检查连接"}</button>
      </main>
    </div>
  );
}
