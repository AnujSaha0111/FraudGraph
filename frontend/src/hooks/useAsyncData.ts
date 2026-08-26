import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

export interface AsyncState<T> {
  data: T | null;
  error: ApiError | null;
  /** true only while there is nothing to show yet */
  loading: boolean;
  /** true while a background refresh is in flight (data stays visible) */
  refreshing: boolean;
  reload: () => void;
}

/** Fetch-on-mount(+deps) hook with manual soft reload.
 *  - Dep changes fully reset (loading skeleton for the new resource).
 *  - reload() keeps current data mounted so forms never lose their state
 *    mid-action (regression: case form wiped after every mutation). */
export function useAsyncData<T>(
  loader: () => Promise<T>,
  deps: readonly unknown[],
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const lastDepsKey = useRef<string | null>(null);

  useEffect(() => {
    const depsKey = JSON.stringify(deps);
    const isReset = depsKey !== lastDepsKey.current;
    lastDepsKey.current = depsKey;
    let alive = true;
    if (isReset) {
      setData(null);
      setLoading(true);
      setError(null);
    } else {
      setRefreshing(true);
    }
    loaderRef
      .current()
      .then((d) => {
        if (!alive) return;
        setData(d);
        setLoading(false);
        setRefreshing(false);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setError(
          err instanceof ApiError ? err : new ApiError(0, String(err), "network"),
        );
        setLoading(false);
        setRefreshing(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, refreshing, reload };
}
