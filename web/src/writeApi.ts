const TOKEN_KEY = "investment_os_write_token";

export function getWriteToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setWriteToken(token: string) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const token = getWriteToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(url, { ...init, headers });
}

export async function readApiError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as {
      detail?: string | { message?: string; code?: string };
    };
    if (typeof body.detail === "string") {
      if (body.detail === "write_api_unauthorized") return "写操作需要写入令牌，请先在右上角配置";
      if (body.detail === "write_api_token_not_configured")
        return "服务端未配置写入令牌，写操作已禁用";
      return body.detail;
    }
    if (body.detail && typeof body.detail === "object") {
      return body.detail.message || body.detail.code || "请求被拒绝";
    }
  } catch {
    /* ignore */
  }
  return `请求失败（HTTP ${response.status}）`;
}
