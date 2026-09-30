import { useEffect, useState } from "react";

import { SettingsPage } from "./SettingsPage";
import { PortfolioPage } from "./PortfolioPage";
import { WatchlistPage } from "./WatchlistPage";
import { PolicyReviewPanel } from "./PolicyReviewPanel";
import { Panel, ProductChrome, StatusBanner } from "./ProductChrome";

type OnboardingStatus = "NOT_STARTED" | "IN_PROGRESS";
type CapabilityStatus = "AVAILABLE" | "CONFIGURATION_REQUIRED" | "NOT_IMPLEMENTED";

type OnboardingState = {
  schema_version: "1.0";
  status: OnboardingStatus;
  started_at: string | null;
};

type Capability = {
  key: string;
  label: string;
  status: CapabilityStatus;
  detail: string;
};

const setupSteps = [
  ["01", "市场与时区", "确认研究市场；此版本只记录向导进度。"],
  ["02", "模型与数据源", "配置已授权的模型与研究数据提供方。"],
  ["03", "组合与观察", "录入持仓、维护观察清单。"],
  ["04", "投资政策", "只读审阅当前纪律；真实限额由你治理决定。"],
  ["05", "开始分析", "配置与证据就绪后，进入受控分析。"],
] as const;

const capabilityLabel: Record<CapabilityStatus, string> = {
  AVAILABLE: "可用",
  CONFIGURATION_REQUIRED: "需要配置",
  NOT_IMPLEMENTED: "尚未实现",
};

function validCapabilities(value: unknown): Capability[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is Capability =>
      typeof item === "object" &&
      item !== null &&
      typeof (item as Capability).key === "string" &&
      typeof (item as Capability).label === "string" &&
      typeof (item as Capability).detail === "string" &&
      ["AVAILABLE", "CONFIGURATION_REQUIRED", "NOT_IMPLEMENTED"].includes(
        (item as Capability).status,
      ),
  );
}

const legacyViews = ["概览", "资产组合", "机会池", "观察清单", "决策日志"] as const;

function LegacyDemo() {
  const [selectedView, setSelectedView] = useState<(typeof legacyViews)[number]>("概览");

  return (
    <ProductChrome
      eyebrow="开发演示"
      title="合成只读页面"
      subtitle="仅用于界面结构演示，不代表真实账户或可执行建议。"
    >
      <Panel title="演示视图" tone="muted">
        <div className="legacy-tabs" aria-label="PR-08 演示页面导航">
          {legacyViews.map((view) => (
            <button
              type="button"
              key={view}
              className={selectedView === view ? "selected" : ""}
              onClick={() => setSelectedView(view)}
            >
              {view}
            </button>
          ))}
        </div>
        <p className="eyebrow">已选择：{selectedView}</p>
        <h2>{selectedView}</h2>
        <p className="page-subtitle">此区域只保留合成演示结构，真实功能请用「资产组合 / 观察清单」。</p>
      </Panel>
    </ProductChrome>
  );
}

function HomePage() {
  const [state, setState] = useState<OnboardingState | null>(null);
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void Promise.all([
      fetch("/api/v1/onboarding").then((response) => {
        if (!response.ok) throw new Error("无法读取初始化状态");
        return response.json() as Promise<OnboardingState>;
      }),
      fetch("/api/v1/product-capabilities").then((response) => {
        if (!response.ok) throw new Error("无法读取功能状态");
        return response.json() as Promise<unknown>;
      }),
    ])
      .then(([onboarding, featureList]) => {
        setState(onboarding);
        setCapabilities(validCapabilities(featureList));
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "加载失败");
      });
  }, []);

  const startSetup = async () => {
    setSaving(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/onboarding/start", { method: "POST" });
      if (!response.ok) throw new Error("无法保存向导进度");
      setState((await response.json()) as OnboardingState);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const started = state?.status === "IN_PROGRESS";

  return (
    <ProductChrome
      eyebrow="个人投资工作台"
      title="先搭好底座，再开始研究"
      subtitle="这不是交易终端。系统默认关闭自动交易；买入加仓需风险关卡与你本人批准。"
    >
      <StatusBanner kind="error" text={error} />

      <div className="stat-row">
        <article className="stat-card">
          <span>向导</span>
          <strong>{started ? "进行中" : "未开始"}</strong>
          <small>首次使用从这里启动</small>
        </article>
        <article className="stat-card">
          <span>自动交易</span>
          <strong>始终关闭</strong>
          <small>建议 ≠ 成交</small>
        </article>
        <article className="stat-card">
          <span>数据原则</span>
          <strong>证据优先</strong>
          <small>缺数据会标未提供</small>
        </article>
        <article className="stat-card warn">
          <span>政策</span>
          <strong>TEST_DEFAULT</strong>
          <small>真实限额需你批准</small>
        </article>
      </div>

      <div className="two-col">
        <Panel
          title="开始设置"
          description="完成向导后，再配置供应商与持仓。"
          actions={
            state?.status === "NOT_STARTED" ? (
              <button type="button" className="btn primary" onClick={() => void startSetup()} disabled={saving}>
                {saving ? "保存中…" : "开始设置"}
              </button>
            ) : null
          }
        >
          {state === null ? <p>正在读取本机状态…</p> : null}
          {started ? (
            <p className="banner banner-ok" role="status">
              设置已开始。下一步：录入组合，或去设置里配置模型与数据源。
            </p>
          ) : (
            <p className="page-subtitle">点击右上角「开始设置」，记录你的使用进度。</p>
          )}
          <div className="btn-row">
            <a className="btn" href="/portfolio">
              去录入持仓
            </a>
            <a className="btn" href="/watchlist">
              去维护观察
            </a>
            <a className="btn" href="/settings">
              去配置提供方
            </a>
          </div>
        </Panel>

        <Panel title="推荐路径" description="按顺序做，不容易绕晕。">
          <ol className="setup-steps">
            {setupSteps.map(([number, title, detail]) => (
              <li key={number}>
                <span>{number}</span>
                <div>
                  <h3>{title}</h3>
                  <p>{detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </Panel>
      </div>

      <div id="policy">
        <PolicyReviewPanel />
      </div>

      <Panel title="功能状态" description="由服务端能力矩阵提供，不假装未完成的功能可用。">
        <div className="capability-grid">
          {capabilities.map((item) => (
            <article key={item.key} className="capability-card">
              <p className={`capability-status ${item.status.toLowerCase()}`}>
                {capabilityLabel[item.status]}
              </p>
              <h3>{item.label}</h3>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </Panel>
    </ProductChrome>
  );
}

export function App() {
  const path = window.location.pathname;
  if (path === "/demo/pr-08") return <LegacyDemo />;
  if (path === "/settings") return <SettingsPage />;
  if (path === "/portfolio") return <PortfolioPage />;
  if (path === "/watchlist") return <WatchlistPage />;
  return <HomePage />;
}

export default App;
