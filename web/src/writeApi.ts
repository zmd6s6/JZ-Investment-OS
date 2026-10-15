const TOKEN_KEY = "investment_os_write_token";

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
    const token = getWriteToken();
    if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  }
  try {
    return await fetch(url, { ...init, headers });
  } catch {
    throw new Error("无法连接本地服务。请检查服务是否启动；若刚提交过操作，请先刷新核对结果，避免重复提交。");
  }
}

export async function verifyWriteToken(token: string): Promise<void> {
  if (!token.trim()) throw new Error("请输入本系统的写入令牌；它不是模型或数据源的 API Key。");
  const response = await apiFetch("/api/v1/auth/check", {
    method: "POST",
    headers: { Authorization: `Bearer ${token.trim()}` },
  });
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
  if (code === "WRITE_API_UNAUTHORIZED" || response.status === 401)
    return getWriteToken()
      ? "本系统的写入令牌不正确或已失效。请在右上角重新配置，不需要更换模型或数据源 Key。"
      : "尚未配置本系统的写入令牌。请点击右上角“配置写令牌”，保存后重试；它不是模型或数据源的 API Key。";
  if (code === "SECRET_STORE_UNAVAILABLE")
    return "加密凭据存储暂不可用，凭据未能保存。请联系维护者检查服务配置，不要自行更换加密主密钥。";
  if (code === "CREDENTIAL_MISSING")
    return "此提供方尚未配置凭据。请在对应档案中填写它自己的 API Key 或 Token，再测试连接。";
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
