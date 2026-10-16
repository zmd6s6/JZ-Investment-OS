import { useEffect, useState } from "react";

import { SettingsPage } from "./SettingsPage";
import { PortfolioPage } from "./PortfolioPage";
import { WatchlistPage } from "./WatchlistPage";
import { PolicyReviewPanel } from "./PolicyReviewPanel";
import { AnalysisPage } from "./AnalysisPage";
import { Panel, ProductChrome, StatusBanner } from "./ProductChrome";
import { apiFetch, readApiError } from "./writeApi";
import { LocalAccessBoundary } from "./LocalAccess";
import { ResearchPage } from "./ResearchPage";

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
      const response = await apiFetch("/api/v1/onboarding/start", { method: "POST" });
      if (!response.ok) throw new Error(await readApiError(response));
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
      title="把持仓变成有据可查的研究"
      subtitle="记录投资组合，让研究团队梳理证据、讨论分歧，再由你判断。这里不会自动下单。"
    >
      <StatusBanner kind="error" text={error} />

      <div className="stat-row">
        <a className="stat-card task-card" href="/portfolio"><span>01 / 已经持有</span><strong>管理我的持仓 →</strong><small>建组合、记现金、录入或导入分仓</small></a>
        <a className="stat-card task-card" href="/watchlist"><span>02 / 正在关注</span><strong>研究观察标的 →</strong><small>不必买入，也能添加并发起研究</small></a>
        <a className="stat-card task-card" href="/analysis"><span>03 / 已有研究</span><strong>查看团队报告 →</strong><small>阅读观点、风险、数据缺口与建议</small></a>
        <a className="stat-card task-card" href="/settings#models"><span>首次使用 / 准备工作</span><strong>配置研究团队 →</strong><small>模型、角色、预算与数据源</small></a>
      </div>

        <Panel
          title="首次使用"
          description="上方指南随时可查看，不必等所有配置齐全才录入持仓。"
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
              设置已开始。下一步：配置研究团队，或先录入组合。此记录不代表模型、预算或数据已就绪。
            </p>
          ) : (
            <p className="page-subtitle">可以直接进入任一入口。「开始设置」仅记录开始时间，不会自动授权、替你填凭据或调用模型。</p>
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

function ProductRoutes() {
  const path = window.location.pathname;
  if (path === "/demo/pr-08") return <LegacyDemo />;
  if (path === "/settings") return <SettingsPage />;
  if (path === "/portfolio") return <PortfolioPage />;
  if (path === "/watchlist") return <WatchlistPage />;
  if (path === "/analysis") return <AnalysisPage />;
  if (path === "/research") return <ResearchPage />;
  return <HomePage />;
}

export function App() {
  return <LocalAccessBoundary><ProductRoutes /></LocalAccessBoundary>;
}

export default App;
