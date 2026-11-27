// Opt-in transport bound. Only WeeklyReviewPanel uses this; apiFetch is unchanged.
export const REQUEST_DEADLINE_MS = 15000;

export class RequestDeadlineError extends Error {
  constructor() { super("请求超过15秒，响应未确认；原输入保留，请明确核对后重试。"); }
}

export async function withRequestDeadline<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  signal?: AbortSignal | null,
): Promise<T> {
  const controller = new AbortController();
  const expires = performance.now() + REQUEST_DEADLINE_MS;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancel = () => {};
  const limit = new Promise<never>((_, reject) => {
    cancel = () => {
      stopped = true;
      reject(new DOMException("请求已取消，未采用迟到响应。", "AbortError"));
      controller.abort();
    };
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) cancel();
    else timer = setTimeout(() => {
      stopped = true;
      // Reject independently of fetch/body honoring AbortSignal. Cancellation
      // is best effort and never establishes that a server write rolled back.
      reject(new RequestDeadlineError());
      controller.abort();
    }, REQUEST_DEADLINE_MS);
  });
  let started: Promise<T>;
  try {
    started = stopped ? Promise.reject(new DOMException("请求已取消。", "AbortError")) : operation(controller.signal);
  } catch (error) {
    started = Promise.reject(error);
  }
  const expired = () => stopped || performance.now() >= expires;
  const task = started.then(value => {
    // A delayed event loop or a transport ignoring abort cannot win at/after
    // the deadline, including when fetch completed but response.json hung.
    if (expired()) throw new RequestDeadlineError();
    return value;
  }, error => {
    if (expired()) throw new RequestDeadlineError();
    throw error;
  });
  try {
    return await Promise.race([task, limit]);
  } finally {
    stopped = true;
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}
