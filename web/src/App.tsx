import { useEffect, useState } from "react";

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
  ["01", "市场范围", "先确认研究市场与交易时区；此版本只记录向导进度。"],
  ["02", "模型与数据提供方", "配置界面将在 P2 提供；本阶段不收集凭据。"],
  ["03", "组合与观察清单", "组合导入和观察标的维护尚未开放。"],
  ["04", "投资政策复核", "政策阈值必须经所有者明确批准后才可变更。"],
  ["05", "分析就绪", "仅在配置与证据链完整后，才进入受控分析流程。"],
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
    <main className="product-shell">
      <header className="product-header">
        <div>
          <p className="eyebrow">PR-08 · 开发演示</p>
          <h1>合成只读页面</h1>
        </div>
        <a className="back-link" href="/">返回设置向导</a>
      </header>
      <section className="legacy-page" aria-labelledby="legacy-page-title">
        <p className="legacy-warning">
          此页面只使用合成开发数据。它不代表账户、持仓、研究结论或可执行交易建议。
        </p>
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
        <article className="legacy-demo-content">
          <p className="eyebrow">已选择：{selectedView}</p>
          <h2 id="legacy-page-title">{selectedView}合成演示</h2>
          <p>
            PR-08 的展示结构保留在此处，仅用于验证只读界面的信息组织。真实组合、提供方配置和分析工作流尚未开放。
          </p>
        </article>
      </section>
    </main>
  );
}

export function App() {
  if (window.location.pathname === "/demo/pr-08") return <LegacyDemo />;

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
    <main className="product-shell">
      <header className="product-header">
        <div>
          <p className="eyebrow">PERSONAL AI INVESTMENT OS · P1</p>
          <h1>开始搭建你的研究工作台</h1>
        </div>
        <nav aria-label="产品导航">
          <a href="#setup">设置向导</a>
          <a href="#status">产品状态</a>
        </nav>
      </header>

      <section id="setup" className="onboarding-card" aria-labelledby="setup-title">
        <div className="onboarding-intro">
          <p className="eyebrow">首次使用</p>
          <h2 id="setup-title">先完成受控设置，再开始分析</h2>
          <p>
            这不是交易终端。系统始终默认关闭自动交易，任何真实执行都需要有效的人类审批。
          </p>
          {error ? <p role="alert" className="error-message">{error}</p> : null}
          {state === null ? <p>正在读取本机初始化状态…</p> : null}
          {state?.status === "NOT_STARTED" ? (
            <button type="button" onClick={() => void startSetup()} disabled={saving}>
              {saving ? "正在保存…" : "开始设置"}
            </button>
          ) : null}
          {started ? (
            <p className="status-note" role="status">
              设置已开始。后续配置项会随经过审核的阶段逐步开放。
            </p>
          ) : null}
        </div>

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
      </section>

      <section id="status" className="capability-section" aria-labelledby="status-title">
        <div>
          <p className="eyebrow">系统设置</p>
          <h2 id="status-title">产品功能状态</h2>
          <p>状态由服务端能力矩阵提供，避免把未接入的功能伪装成可操作页面。</p>
        </div>
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
      </section>

      <section className="legacy-section" aria-labelledby="legacy-title">
        <h2 id="legacy-title">PR-08 合成演示</h2>
        <p>
          旧版的组合、机会池、观察清单和决策日志页面仅用于合成数据演示，不代表账户、持仓或可执行建议。
        </p>
        <a className="secondary-button" href="/demo/pr-08">进入合成演示页</a>
      </section>
    </main>
  );
}

export default App;
