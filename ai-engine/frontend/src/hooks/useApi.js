import { useEffect, useRef, useState } from 'react';
export function useApi(fetcher, options) {
    const { intervalMs, deps = [] } = options ?? {};
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const cancelled = useRef(false);
    // We bump this counter to trigger a manual refetch.
    const [tick, setTick] = useState(0);
    useEffect(() => {
        cancelled.current = false;
        let timer;
        const run = async () => {
            try {
                setError(null);
                const result = await fetcher();
                if (!cancelled.current) {
                    setData(result);
                    setLoading(false);
                }
            }
            catch (e) {
                if (!cancelled.current) {
                    setError(e);
                    setLoading(false);
                }
            }
        };
        run();
        if (intervalMs && intervalMs > 0) {
            timer = window.setInterval(run, intervalMs);
        }
        return () => {
            cancelled.current = true;
            if (timer !== undefined)
                window.clearInterval(timer);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tick, intervalMs, ...deps]);
    return {
        data,
        loading,
        error,
        refetch: () => setTick((t) => t + 1),
    };
}
