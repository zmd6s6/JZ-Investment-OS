import { afterEach, expect, test, vi } from "vitest";
import { REQUEST_DEADLINE_MS, RequestDeadlineError, withRequestDeadline } from "./requestDeadline";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
function held<T>() { let resolve!: (value: T) => void; return { promise: new Promise<T>(done => { resolve = done; }), resolve: (value: T) => resolve(value) }; }

test("whole-chain deadline accepts body completed one millisecond before expiry and cleans timer and listener", async () => {
  vi.useFakeTimers(); const controller = new AbortController(), body = held<string>();
  const add = vi.spyOn(controller.signal, "addEventListener"), remove = vi.spyOn(controller.signal, "removeEventListener");
  const result = withRequestDeadline(async () => body.promise, controller.signal);
  await vi.advanceTimersByTimeAsync(REQUEST_DEADLINE_MS - 1); body.resolve("complete");
  expect(await result).toBe("complete"); expect(vi.getTimerCount()).toBe(0);
  expect(remove).toHaveBeenCalledWith("abort", add.mock.calls[0][1]);
});

for (const elapsed of [REQUEST_DEADLINE_MS, REQUEST_DEADLINE_MS + 1]) {
  test(`whole-chain deadline rejects completion at elapsed ${elapsed} even before delayed timer runs`, async () => {
    vi.useFakeTimers(); const clock = vi.spyOn(performance, "now").mockReturnValue(100), body = held<string>();
    const result = withRequestDeadline(async () => body.promise);
    const error = result.catch(value => value);
    clock.mockReturnValue(100 + elapsed); body.resolve("late");
    expect(await error).toBeInstanceOf(RequestDeadlineError); expect(vi.getTimerCount()).toBe(0);
  });
}

test("ignored transport abort cannot keep deadline pending and a late resolve cannot change timeout", async () => {
  vi.useFakeTimers(); const body = held<string>(); let received: AbortSignal | undefined;
  const result = withRequestDeadline(async signal => { received = signal; return body.promise; });
  const settled = result.catch(value => value);
  await vi.advanceTimersByTimeAsync(REQUEST_DEADLINE_MS);
  expect(await settled).toBeInstanceOf(RequestDeadlineError); expect(received?.aborted).toBe(true);
  body.resolve("late"); await Promise.resolve(); expect(await settled).toBeInstanceOf(RequestDeadlineError);
  expect(vi.getTimerCount()).toBe(0);
});

test("late rejection cannot bypass the deadline when its timer is delayed", async () => {
  vi.useFakeTimers(); const clock = vi.spyOn(performance, "now").mockReturnValue(100);
  let reject!: (error: Error) => void;
  const response = new Promise<string>((_, done) => { reject = done; });
  const result = withRequestDeadline(async () => response).catch(error => error);
  clock.mockReturnValue(100 + REQUEST_DEADLINE_MS); reject(new Error("late HTTP refusal"));
  expect(await result).toBeInstanceOf(RequestDeadlineError); expect(vi.getTimerCount()).toBe(0);
});

test("explicit caller cancellation rejects independently of a hung body and clears listener and timer", async () => {
  vi.useFakeTimers(); const controller = new AbortController(), remove = vi.spyOn(controller.signal, "removeEventListener");
  const result = withRequestDeadline(async () => new Promise(() => {}), controller.signal).catch(value => value);
  await Promise.resolve(); controller.abort();
  expect(await result).toMatchObject({ name: "AbortError" }); expect(vi.getTimerCount()).toBe(0); expect(remove).toHaveBeenCalledOnce();
});

test("already cancelled caller never starts transport", async () => {
  vi.useFakeTimers(); const controller = new AbortController(); controller.abort(); const operation = vi.fn(async () => "unexpected");
  const error = await withRequestDeadline(operation, controller.signal).catch(value => value);
  expect(error.name).toBe("AbortError"); expect(operation).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
});

test("normal transport rejection remains a failure and clears all deadline resources", async () => {
  vi.useFakeTimers(); const failure = new TypeError("synthetic rejected fetch"), controller = new AbortController();
  const remove = vi.spyOn(controller.signal, "removeEventListener");
  await expect(withRequestDeadline(async () => { throw failure; }, controller.signal)).rejects.toBe(failure);
  expect(vi.getTimerCount()).toBe(0); expect(remove).toHaveBeenCalledOnce();
});
