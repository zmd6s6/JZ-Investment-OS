import { apiFetch, readApiError } from "./writeApi";

// A browser read deadline, not a limit on the background analysis or model call.
export const ANALYSIS_READ_TIMEOUT_MS = 15_000;

export async function readAnalysisJson<T>(url: string, signal?: AbortSignal, label = "读取分析记录"): Promise<T> {
  if (signal?.aborted) throw new Error("读取已取消。");
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancel!: () => void;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new Error(`${label}超时。请重试读取；不会重新启动分析或调用模型。`));
      controller.abort();
    }, ANALYSIS_READ_TIMEOUT_MS);
    cancel = () => { reject(new Error("读取已取消。")); controller.abort(); };
  });
  signal?.addEventListener("abort", cancel, { once: true });
  try {
    return await Promise.race([
      (async () => {
        const response = await apiFetch(url, { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error(await readApiError(response));
        try { return await response.json() as T; }
        catch { throw new Error("分析记录格式异常，未采用该响应；请刷新或联系维护者。"); }
      })(),
      deadline,
    ]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}
