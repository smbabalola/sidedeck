import { useCallback, useEffect, useState } from "react";

export type Resource<T> =
  | { state: "loading"; data: null; error: null; fetchedAt: null }
  | { state: "ready"; data: T; error: null; fetchedAt: number }
  | { state: "error"; data: null; error: string; fetchedAt: number };

/** Fetch a read-only endpoint and accept it only if ``guard`` validates the payload. */
export function useResource<T>(path: string, guard: (d: unknown) => d is T): Resource<T> & { reload: () => void } {
  const [resource, setResource] = useState<Resource<T>>({ state: "loading", data: null, error: null, fetchedAt: null });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setResource({ state: "loading", data: null, error: null, fetchedAt: null });
    fetch(path, { signal: controller.signal, cache: "no-store", headers: { Accept: "application/json" } })
      .then(async response => {
        if (!response.ok) throw new Error(`The local service answered ${response.status}.`);
        const data: unknown = await response.json();
        if (!guard(data)) throw new Error("The response did not match the expected contract, so it was not shown.");
        setResource({ state: "ready", data, error: null, fetchedAt: Date.now() });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message = error instanceof Error && error.message ? error.message : "Request failed.";
        setResource({ state: "error", data: null, error: message.includes("fetch") ? "The local SideDeck service is not reachable." : message, fetchedAt: Date.now() });
      });
    return () => controller.abort();
  }, [path, guard, nonce]);
  const reload = useCallback(() => setNonce(n => n + 1), []);
  return { ...resource, reload };
}
