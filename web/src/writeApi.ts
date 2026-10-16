const TOKEN_KEY = "investment_os_write_token";
let apiAuthMode: "bearer" | "local_session" = "bearer";
export function setApiAuthMode(mode: "bearer" | "local_session") { apiAuthMode = mode; }

export function getWriteToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setWriteToken(token: string): boolean {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
    return true;
  } catch {
    return false;
  }
}

export async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-Investment-OS", "local-ui");
    const token = apiAuthMode === "bearer" ? getWriteToken() : "";
    if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  }
  try {
    const response = await fetch(url, { ...init, credentials: "same-origin", headers });
    if (response.status === 401 && apiAuthMode === "local_session") window.dispatchEvent(new Event("investment-os:session-expired"));
    return response;
  } catch {
    throw new Error("无法连接本地服务。请检查服务是否启动；若刚提交过操作，请先刷新核对结果，避免重复提交。");
  }
}

export async function verifyWriteToken(token: string): Promise<void> {
  if (!token.trim()) throw new Error("请输入本系统的写入令牌；它不是模型或数据源的 API Key。");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  let response: Response;
  try {
    response = await apiFetch("/api/v1/auth/check", {
      method: "POST",
      headers: { Authorization: `Bearer ${token.trim()}` },
      signal: controller.signal,
    });
  } catch (reason) {
    if (controller.signal.aborted) throw new Error("本地访问验证超时，令牌未保存。请检查服务状态后重试。");
    throw reason;
  } finally {
    clearTimeout(timeout);
  }
  if (response.status === 401)
    throw new Error("写入令牌不正确或已失效。请核对服务端配置；不要填写模型或数据源的 API Key。");
  if (!response.ok) throw new Error(await readApiError(response));
}

export async function readApiError(response: Response): Promise<string> {
  let detail: unknown;
  try {
    const body = (await response.json()) as { detail?: unknown; code?: unknown };
    detail = body.detail ?? body.code;
  } catch {
    // HTML errors and proxy failures still get a useful, non-sensitive message.
  }
  const code = typeof detail === "string"
    ? detail.toUpperCase()
    : detail && typeof detail === "object" && "code" in detail
      ? String(detail.code).toUpperCase()
      : "";
  if (code === "WRITE_API_TOKEN_NOT_CONFIGURED")
    return "服务端尚未配置本系统的写入令牌，保存操作已禁用。请联系维护者配置；这不是模型或数据源 Key 的问题。";
  if (code === "LOCAL_ACCESS_REQUIRED") return "本机访问已过期或未连接。请重新从「打开投资工作台.cmd」进入，不需要填写令牌或更换供应商 Key。";
  if (code === "LOCAL_ORIGIN_MISMATCH" || code === "LOCAL_ORIGIN_REQUIRED") return "请求来源与本机工作台不一致，操作已阻止。请从本地启动入口打开正确地址。";
  if (code === "LOCAL_ACCESS_UNAVAILABLE") return "本机会话存储暂不可用，操作未完成。请检查运行目录权限后重试，不要更换供应商密钥。";
  if (code === "WRITE_API_UNAUTHORIZED" || response.status === 401)
    return getWriteToken()
      ? "本系统的写入令牌不正确或已失效。请在右上角重新配置，不需要更换模型或数据源 Key。"
      : "尚未配置本系统的写入令牌。请点击右上角“配置写令牌”，保存后重试；它不是模型或数据源的 API Key。";
  if (code === "SECRET_STORE_UNAVAILABLE")
    return "加密凭据存储暂不可用，凭据未能保存。请联系维护者检查服务配置，不要自行更换加密主密钥。";
  if (code === "CREDENTIAL_MISSING")
    return "此提供方尚未配置凭据。请在对应档案中填写它自己的 API Key 或 Token，再测试连接。";
  if (code === "RESEARCH_PROVIDER_REQUEST_REJECTED") return "所选研究来源暂不可用：请检查档案已启用、凭据可用、类型受支持，以及查询和单标的范围正确。未切换其他来源。";
  if (code === "RESEARCH_PREVIEW_EXPIRED") return "预览确认窗口已过期，所选内容未入库。请明确重新查询并检查资料，系统不会自动产生费用。";
  if (code === "RESEARCH_PREVIEW_NOT_FOUND") return "没有找到原预览；可能未成功取得结果。重新查询可能再次计费，请核对后明确发起。";
  if (code === "RESEARCH_PREVIEW_SOURCE_DISABLED") return "预览对应的来源已停用、移除或没有凭据，本次确认已阻止；不会自动启用来源。";
  if (code.startsWith("RESEARCH_PREVIEW_") && code.endsWith("CONFLICT")) return "这个预览已使用其他请求或选择确认过，不能覆盖原记录。请找回原预览查看已保存结果。";
  if (code.startsWith("RESEARCH_PREVIEW_")) return "预览或所选候选已不可用，整批确认未完成。请找回预览核对标的、有效期和所选内容。";
  if (code === "ANALYSIS_EVIDENCE_SELECTION_INVALID") return "所选证据含缺失、跨标的、重复、未来或过期内容，分析未启动。请刷新并重新勾选，不会偷偷替换成其他资料。";
  if (code === "ANALYSIS_JOB_REQUEST_CONFLICT") return "同一任务标识对应了不同请求，不能覆盖原任务。请先到分析运行核对原结果。";
  if (code === "ANALYSIS_JOB_NOT_RETRYABLE") return "此运行尚未失败或取消，不能重新发起。请先查看当前运行，避免重复费用。";
  if (code === "ANALYSIS_JOB_NOT_FOUND") return "该记录不是可操作的后台任务，或已不存在。旧同步报告仍可阅读。";
  if (code === "ANALYSIS_JOBS_UNAVAILABLE") return "后台分析服务尚未部署或暂不可用。请联系维护者检查 API、Worker 和迁移，不要更换供应商密钥。";
  if (code === "RESEARCH_PROVIDER_UNAVAILABLE") return "所选研究供应商连接失败或超时。请先检查已存资料，再决定是否重新调用；没有切换其他来源。";
  if (code === "RESEARCH_INGESTION_UNAVAILABLE" || code === "RESEARCH_PROVIDER_RUNTIME_UNAVAILABLE") return "研究服务暂不可用。请检查 API 部署与数据库，不要更换模型密钥。";
  if (response.status === 403) return "当前操作没有权限，未获授权。请检查本系统的访问配置，不要更换供应商 Key。";
  if (response.status === 404) return "记录不存在或已被移除。请刷新列表后重新选择。";
  if (response.status === 409) return "数据已被其他操作更新。请先刷新核对最新内容，再重新提交。";
  if (response.status === 422) {
    const fields: Record<string, string> = {
      name: "名称", base_url: "基础 URL", provider_type: "提供方类型",
      model_name: "模型名", timeout_seconds: "超时秒数", max_tokens: "最大 Tokens",
      credential: "提供方凭据", retention_days: "本地保留天数",
      market_timezone: "市场时区", task_token_limit: "单任务 Token 上限",
    };
    const names = Array.isArray(detail)
      ? [...new Set(detail.flatMap((issue) => {
          const loc = issue && typeof issue === "object" && "loc" in issue ? issue.loc : null;
          const field = Array.isArray(loc) ? String(loc[loc.length - 1]) : "";
          return fields[field] ? [fields[field]] : [];
        }))]
      : [];
    return names.length
      ? `填写内容未通过校验：${names.join("、")}。请检查这些字段的格式和允许范围，输入内容已保留。`
      : "填写内容未通过校验。请检查必填项、格式和数值范围，输入内容已保留。";
  }
  if (response.status === 429) return "请求过于频繁或额度已用完。请稍后重试，并检查提供方额度和系统预算。";
  if (response.status === 408 || response.status === 504)
    return "等待服务响应超时，结果尚未确认。请先刷新核对运行或保存结果，不要立即重复提交。";
  return `服务暂时无法完成请求（HTTP ${response.status}）。请先刷新核对结果；仍失败时联系维护者。请勿因此更换 API Key 或加密主密钥。`;
}
