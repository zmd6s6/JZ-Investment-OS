import { FormEvent, useEffect, useState } from "react";

type SystemSettings = {
  market_timezone: string;
  market_scopes: string[];
  auto_trade: false;
};

type ModelProfile = {
  id: string;
  name: string;
  provider_type: string;
  base_url: string;
  model_name: string;
  timeout_seconds: number;
  max_tokens: number;
  enabled: boolean;
  credential_configured: boolean;
  pricing_version: string | null;
  pricing_currency: string | null;
  input_token_price: string | null;
  output_token_price: string | null;
  pricing_effective_at: string | null;
};

type Budget = { status: "CONFIGURED" | "NOT_CONFIGURED"; version: string | null; currency: string | null; task_token_limit: number | null; daily_token_limit: number | null; task_cost_limit: string | null; daily_cost_limit: string | null; usage: { remaining_tokens: number; remaining_cost: string } | null };

type DataProfile = {
  id: string;
  name: string;
  provider_type: string;
  base_url: string;
  timeout_seconds: number;
  enabled: boolean;
  retention_days: number;
  credential_configured: boolean;
};

type Assignment = {
  role: string;
  model_provider_profile_id: string;
};

type TestResult = {
  status:
    | "CONFIGURATION_VALID"
    | "CREDENTIAL_MISSING"
    | "SECRET_STORE_UNAVAILABLE"
    | "CONNECTION_SUCCEEDED"
    | "CONNECTION_FAILED"
    | "UNSUPPORTED_PROVIDER";
  detail: string;
  latency_ms: number | null;
};

type TestHistory = {
  status: TestResult["status"];
  occurred_at: string;
  latency_ms: number | null;
};

type SyncHistory = { occurred_at: string; artifact_count: number; latency_ms: number };

const requestJson = async <T,>(url: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error("保存失败，请检查配置或加密密钥是否可用。");
  return response.json() as Promise<T>;
};

const formText = (form: HTMLFormElement, name: string): string =>
  String(new FormData(form).get(name) ?? "").trim();

const roles = ["DEFAULT", "MACRO", "INDUSTRY", "FUNDAMENTAL", "MARKET_QUANT", "EVENT", "PORTFOLIO", "RISK", "DEVILS_ADVOCATE", "CIO", "REVIEW"];

function CredentialStatus({ configured }: { configured: boolean }) {
  return (
    <span className={configured ? "credential-ok" : "credential-missing"}>
      {configured ? "凭据已配置" : "未配置凭据"}
    </span>
  );
}

function DataProviderTestStatus({ history }: { history: TestHistory | null | undefined }) {
  if (!history) return <p>最近连接：尚未测试</p>;

  const latency = history.latency_ms === null ? "" : ` · ${history.latency_ms}ms`;
  return (
    <p>
      最近连接：{history.status} · {new Date(history.occurred_at).toLocaleString()}
      {latency}
    </p>
  );
}

function DataProviderSyncStatus({ history }: { history: SyncHistory | null | undefined }) {
  if (!history) return <p>最近同步：尚未成功同步</p>;
  return <p>最近同步：{new Date(history.occurred_at).toLocaleString()} · {history.artifact_count} 条 · {history.latency_ms}ms</p>;
}

export function SettingsPage() {
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [dataProfiles, setDataProfiles] = useState<DataProfile[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [dataTestHistory, setDataTestHistory] = useState<Record<string, TestHistory | null>>({});
  const [dataSyncHistory, setDataSyncHistory] = useState<Record<string, SyncHistory | null>>({});
  const [editingModel, setEditingModel] = useState<ModelProfile | null>(null);
  const [editingData, setEditingData] = useState<DataProfile | null>(null);

  const load = async () => {
    try {
      const [nextSettings, nextModels, nextData, nextAssignments, nextBudget] = await Promise.all([
        requestJson<SystemSettings>("/api/v1/settings/system"),
        requestJson<ModelProfile[]>("/api/v1/settings/model-providers"),
        requestJson<DataProfile[]>("/api/v1/settings/data-providers"),
        requestJson<Assignment[]>("/api/v1/settings/role-model-assignments"),
        requestJson<Budget>("/api/v1/settings/llm-budget"),
      ]);
      setSettings(nextSettings);
      setModels(nextModels);
      setDataProfiles(nextData);
      const histories = await Promise.all(
        nextData.map(async (profile) => [
          profile.id,
          await requestJson<TestHistory | null>(`/api/v1/settings/data-providers/${profile.id}/last-test`),
        ] as const),
      );
      setDataTestHistory(Object.fromEntries(histories));
      const syncs = await Promise.all(nextData.map(async (profile) => [profile.id, await requestJson<SyncHistory | null>(`/api/v1/settings/data-providers/${profile.id}/last-sync`)] as const));
      setDataSyncHistory(Object.fromEntries(syncs));
      setAssignments(nextAssignments);
      setBudget(nextBudget);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取设置");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const saveSystem = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    try {
      const form = event.currentTarget;
      const next = await requestJson<SystemSettings>("/api/v1/settings/system", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          market_timezone: formText(form, "market_timezone"),
          market_scopes: formText(form, "market_scopes")
            .split(",")
            .map((scope) => scope.trim())
            .filter(Boolean),
        }),
      });
      setSettings(next);
      setMessage("系统设置已保存；自动交易始终关闭。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法保存系统设置");
    }
  };

  const saveModel = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    try {
      const form = event.currentTarget;
      const credential = formText(form, "credential");
      const profile = await requestJson<ModelProfile>(
        editingModel?.id
          ? `/api/v1/settings/model-providers/${editingModel.id}`
          : "/api/v1/settings/model-providers",
        {
        method: editingModel?.id ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: formText(form, "name"),
          provider_type: formText(form, "provider_type"),
          base_url: formText(form, "base_url"),
          model_name: formText(form, "model_name"),
          timeout_seconds: Number(formText(form, "timeout_seconds")),
          max_tokens: Number(formText(form, "max_tokens")),
          enabled: formText(form, "enabled") === "true",
          pricing_version: formText(form, "pricing_version") || null,
          pricing_currency: formText(form, "pricing_currency") || null,
          input_token_price: formText(form, "input_token_price") || null,
          output_token_price: formText(form, "output_token_price") || null,
          ...(credential ? { credential } : {}),
        }),
        },
      );
      form.reset();
      setModels((current) =>
        editingModel?.id
          ? current.map((item) => (item.id === profile.id ? profile : item))
          : [...current, profile],
      );
      setEditingModel(null);
      setMessage("模型档案已保存；浏览器不会读取或回显凭据。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法保存模型档案");
    }
  };

  const saveData = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    try {
      const form = event.currentTarget;
      const credential = formText(form, "credential");
      const profile = await requestJson<DataProfile>(
        editingData
          ? `/api/v1/settings/data-providers/${editingData.id}`
          : "/api/v1/settings/data-providers",
        {
        method: editingData ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: formText(form, "name"),
          provider_type: formText(form, "provider_type"),
          base_url: formText(form, "base_url"),
          timeout_seconds: Number(formText(form, "timeout_seconds")),
          enabled: formText(form, "enabled") === "true",
          retention_days: Number(formText(form, "retention_days")),
          ...(credential ? { credential } : {}),
        }),
        },
      );
      form.reset();
      setDataProfiles((current) =>
        editingData
          ? current.map((item) => (item.id === profile.id ? profile : item))
          : [...current, profile],
      );
      setEditingData(null);
      setMessage("数据提供方档案已保存，尚未启用任何数据同步。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法保存数据档案");
    }
  };

  const testProfile = async (kind: "model-providers" | "data-providers", id: string) => {
    setError(null);
    try {
      const result = await requestJson<TestResult>(
        `/api/v1/settings/${kind}/${id}/test`,
        { method: "POST" },
      );
      setTestResults((current) => ({ ...current, [id]: result }));
      if (kind === "data-providers") {
        const history = await requestJson<TestHistory | null>(
          `/api/v1/settings/data-providers/${id}/last-test`,
        );
        setDataTestHistory((current) => ({ ...current, [id]: history }));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法校验配置");
    }
  };

  const setDefaultModel = async (id: string) => {
    setError(null);
    try {
      const assignment = await requestJson<Assignment>(
        "/api/v1/settings/role-model-assignments/DEFAULT",
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_provider_profile_id: id }),
        },
      );
      setAssignments((current) => [
        ...current.filter((item) => item.role !== "DEFAULT"),
        assignment,
      ]);
      setMessage("默认模型已分配；未单独分配的角色会显式使用该模型。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法分配默认模型");
    }
  };

  const setRoleModel = async (role: string, id: string) => {
    setError(null);
    try {
      if (!id) {
        const response = await fetch(`/api/v1/settings/role-model-assignments/${role}`, { method: "DELETE" });
        if (!response.ok && response.status !== 404) throw new Error("无法更新角色映射");
        setAssignments((current) => current.filter((item) => item.role !== role));
      } else {
        const assignment = await requestJson<Assignment>(`/api/v1/settings/role-model-assignments/${role}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model_provider_profile_id: id }) });
        setAssignments((current) => [...current.filter((item) => item.role !== role), assignment]);
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法更新角色映射"); }
  };

  const saveBudget = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; setError(null);
    try {
      const next = await requestJson<Budget>("/api/v1/settings/llm-budget", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: formText(form, "version"), currency: formText(form, "currency"), task_token_limit: Number(formText(form, "task_token_limit")), daily_token_limit: Number(formText(form, "daily_token_limit")), task_cost_limit: formText(form, "task_cost_limit"), daily_cost_limit: formText(form, "daily_cost_limit") }) });
      setBudget(next); setMessage("预算门禁已保存；预算或定价不可用时模型请求会被阻止。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法保存预算"); }
  };

  const useDeepSeekTemplate = () => setEditingModel({ id: "", name: "DeepSeek V4.1 Flash", provider_type: "OPENAI_COMPATIBLE", base_url: "https://api.deepseek.com", model_name: "deepseek-flash", timeout_seconds: 30, max_tokens: 1024, enabled: false, credential_configured: false, pricing_version: null, pricing_currency: null, input_token_price: null, output_token_price: null, pricing_effective_at: null });

  const toggleModel = async (profile: ModelProfile) => {
    setError(null);
    try {
      const updated = await requestJson<ModelProfile>(
        `/api/v1/settings/model-providers/${profile.id}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: profile.name,
            provider_type: profile.provider_type,
            base_url: profile.base_url,
            model_name: profile.model_name,
            timeout_seconds: profile.timeout_seconds,
            max_tokens: profile.max_tokens,
            enabled: !profile.enabled,
            pricing_version: profile.pricing_version,
            pricing_currency: profile.pricing_currency,
            input_token_price: profile.input_token_price,
            output_token_price: profile.output_token_price,
          }),
        },
      );
      setModels((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法更新模型档案");
    }
  };

  const toggleData = async (profile: DataProfile) => {
    setError(null);
    try {
      const updated = await requestJson<DataProfile>(
        `/api/v1/settings/data-providers/${profile.id}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: profile.name,
            provider_type: profile.provider_type,
            base_url: profile.base_url,
            timeout_seconds: profile.timeout_seconds,
            enabled: !profile.enabled,
            retention_days: profile.retention_days,
          }),
        },
      );
      setDataProfiles((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法更新数据档案");
    }
  };

  const defaultAssignment = assignments.find((item) => item.role === "DEFAULT");

  return (
    <main className="product-shell settings-shell">
      <header className="product-header">
        <div>
          <p className="eyebrow">PERSONAL AI INVESTMENT OS · P3</p>
          <h1>设置与提供方</h1>
        </div>
        <nav aria-label="产品导航">
          <a href="/">设置向导</a>
          <a href="#models">模型提供方</a>
          <a href="#data">数据提供方</a>
        </nav>
      </header>

      <p className="settings-safety">
        自动交易始终关闭。模型“测试连接”仅在您明确点击后发起，检查认证与 JSON 输出；
        已支持的数据提供方也只会在您明确点击“测试连接”后发起受限网络校验；未支持的类型
        和未配置凭据会失败关闭。
      </p>
      {error ? <p role="alert" className="error-message">{error}</p> : null}
      {message ? <p role="status" className="status-note">{message}</p> : null}

      <section className="settings-card" aria-labelledby="system-settings-title">
        <h2 id="system-settings-title">系统范围</h2>
        <form className="settings-form compact-form" onSubmit={(event) => void saveSystem(event)}>
          <label>
            市场时区
            <input name="market_timezone" defaultValue={settings?.market_timezone ?? "Asia/Shanghai"} required />
          </label>
          <label>
            市场范围（逗号分隔）
            <input name="market_scopes" defaultValue={settings?.market_scopes.join(", ") ?? ""} />
          </label>
          <p>自动交易：<strong>已关闭且不可在此修改</strong></p>
          <button type="submit">保存系统设置</button>
        </form>
      </section>

      <section id="models" className="settings-card" aria-labelledby="model-settings-title">
        <h2 id="model-settings-title">模型提供方</h2>
        <p>配置只保存端点、模型和加密凭据引用。凭据输入框不会用响应回填。</p>
        <button type="button" onClick={useDeepSeekTemplate}>填入 DeepSeek V4.1 Flash 模板</button>
        <form key={editingModel?.id ?? "new-model"} className="settings-form" onSubmit={(event) => void saveModel(event)}>
          <label>名称<input name="name" defaultValue={editingModel?.name} required /></label>
          <label>类型<input name="provider_type" defaultValue={editingModel?.provider_type ?? "OPENAI_COMPATIBLE"} required /></label>
          <label>基础 URL<input name="base_url" type="url" defaultValue={editingModel?.base_url} placeholder="https://provider.example/v1" required /></label>
          <label>模型名<input name="model_name" defaultValue={editingModel?.model_name} required /></label>
          <label>超时秒数<input name="timeout_seconds" type="number" min="1" max="300" defaultValue={editingModel?.timeout_seconds ?? "30"} required /></label>
          <label>最大 Tokens<input name="max_tokens" type="number" min="1" defaultValue={editingModel?.max_tokens ?? "1024"} required /></label>
          <label>定价版本<input name="pricing_version" defaultValue={editingModel?.pricing_version ?? ""} /></label>
          <label>定价币种<input name="pricing_currency" defaultValue={editingModel?.pricing_currency ?? ""} /></label>
          <label>输入 Token 单价<input name="input_token_price" type="number" min="0" step="any" defaultValue={editingModel?.input_token_price ?? ""} /></label>
          <label>输出 Token 单价<input name="output_token_price" type="number" min="0" step="any" defaultValue={editingModel?.output_token_price ?? ""} /></label>
          <label>启用状态<select name="enabled" defaultValue={String(editingModel?.enabled ?? false)}><option value="false">先禁用</option><option value="true">启用</option></select></label>
          <label>凭据（仅写入）<input name="credential" type="password" autoComplete="new-password" /></label>
          <button type="submit">{editingModel ? "保存模型修改" : "新增模型档案"}</button>
          {editingModel ? <button type="button" onClick={() => setEditingModel(null)}>取消编辑</button> : null}
        </form>
        <div className="provider-list">
          {models.map((profile) => (
            <article key={profile.id} className="provider-card">
              <div>
                <h3>{profile.name}</h3>
                <p>{profile.provider_type} · {profile.model_name}</p>
                <p>{profile.base_url}</p>
                <CredentialStatus configured={profile.credential_configured} />
                <DataProviderTestStatus history={dataTestHistory[profile.id]} />
              </div>
              <div className="provider-actions">
                <button type="button" onClick={() => void testProfile("model-providers", profile.id)}>测试模型连接</button>
                <button type="button" onClick={() => setEditingModel(profile)}>编辑</button>
                <button type="button" onClick={() => void toggleModel(profile)}>{profile.enabled ? "停用" : "启用"}</button>
                {profile.enabled ? <button type="button" onClick={() => void setDefaultModel(profile.id)}>设为默认模型</button> : null}
                {testResults[profile.id] ? <p role="status">{testResults[profile.id].detail}</p> : null}
              </div>
            </article>
          ))}
        </div>
        <p>当前默认模型：{defaultAssignment ? defaultAssignment.model_provider_profile_id : "未分配"}</p>
        <h3>Agent → 模型映射</h3>
        <p>明确映射优先；未映射的角色继承 DEFAULT。DEFAULT 不可用时不会改用其他提供方。</p>
        {roles.map((role) => <label key={role}>{role}<select aria-label={`${role} 模型`} value={assignments.find((item) => item.role === role)?.model_provider_profile_id ?? ""} onChange={(event) => void setRoleModel(role, event.target.value)}><option value="">{role === "DEFAULT" ? "未分配（不可运行）" : "继承 DEFAULT"}</option>{models.filter((model) => model.enabled).map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>)}
      </section>

      <section className="settings-card" aria-labelledby="budget-title"><h2 id="budget-title">LLM 预算门禁</h2><p>状态：{budget?.status ?? "读取中"}；每日剩余 Tokens：{budget?.usage?.remaining_tokens ?? "不可用"}；剩余成本：{budget?.usage?.remaining_cost ?? "不可用"}</p><form className="settings-form compact-form" onSubmit={(event) => void saveBudget(event)}><label>版本<input name="version" defaultValue={budget?.version ?? "TEST_DEFAULT"} required /></label><label>币种<input name="currency" defaultValue={budget?.currency ?? "USD"} required /></label><label>单任务 Tokens<input name="task_token_limit" type="number" defaultValue={budget?.task_token_limit ?? 10000} required /></label><label>每日 Tokens<input name="daily_token_limit" type="number" defaultValue={budget?.daily_token_limit ?? 100000} required /></label><label>单任务成本<input name="task_cost_limit" defaultValue={budget?.task_cost_limit ?? "1"} required /></label><label>每日成本<input name="daily_cost_limit" defaultValue={budget?.daily_cost_limit ?? "10"} required /></label><button type="submit">保存预算</button></form></section>

      <section id="data" className="settings-card" aria-labelledby="data-settings-title">
        <h2 id="data-settings-title">数据 / 研究提供方</h2>
        <p>启用仅记录配置状态，不代表已授权或已开始同步；真实运行时属于 P4。</p>
        <form key={editingData?.id ?? "new-data"} className="settings-form" onSubmit={(event) => void saveData(event)}>
          <label>名称<input name="name" defaultValue={editingData?.name} required /></label>
          <label>类型<input name="provider_type" defaultValue={editingData?.provider_type ?? "DSA_ADAPTER"} required /></label>
          <label>基础 URL<input name="base_url" type="url" defaultValue={editingData?.base_url} placeholder="https://provider.example" required /></label>
          <label>超时秒数<input name="timeout_seconds" type="number" min="1" max="300" defaultValue={editingData?.timeout_seconds ?? "30"} required /></label>
          <label>本地保留天数<input name="retention_days" type="number" min="1" max="3650" defaultValue={editingData?.retention_days ?? "365"} required /></label>
          <label>启用状态<select name="enabled" defaultValue={String(editingData?.enabled ?? false)}><option value="false">先禁用</option><option value="true">启用</option></select></label>
          <label>凭据（仅写入）<input name="credential" type="password" autoComplete="new-password" /></label>
          <button type="submit">{editingData ? "保存数据修改" : "新增数据档案"}</button>
          {editingData ? <button type="button" onClick={() => setEditingData(null)}>取消编辑</button> : null}
        </form>
        <div className="provider-list">
          {dataProfiles.map((profile) => (
            <article key={profile.id} className="provider-card">
              <div>
                <h3>{profile.name}</h3>
                <p>{profile.provider_type} · {profile.base_url}</p>
                <p>本地保留：{profile.retention_days} 天</p>
                <CredentialStatus configured={profile.credential_configured} />
                <DataProviderTestStatus history={dataTestHistory[profile.id]} />
                <DataProviderSyncStatus history={dataSyncHistory[profile.id]} />
              </div>
              <div className="provider-actions">
                <button type="button" onClick={() => void testProfile("data-providers", profile.id)}>测试连接</button>
                <button type="button" onClick={() => setEditingData(profile)}>编辑</button>
                <button type="button" onClick={() => void toggleData(profile)}>{profile.enabled ? "停用" : "启用"}</button>
                {testResults[profile.id] ? <p role="status">{testResults[profile.id].detail}</p> : null}
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
