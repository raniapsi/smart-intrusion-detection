import { useEffect, useRef, useState } from 'react'

// Generic data-fetching hook. Calls `fetcher` immediately, then again at
// `intervalMs` intervals (when set). Cancels in-flight requests on unmount.
//
// Returning { data, loading, error, refetch } gives the consumer enough
// control without forcing react-query into the project. Sufficient for a
// SOC dashboard that polls a handful of endpoints every few seconds.

export type UseApiState<T> = {
  data: T | null
  loading: boolean
  error: Error | null
  refetch: () => void
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  options?: { intervalMs?: number; deps?: unknown[] },
): UseApiState<T> {
  const { intervalMs, deps = [] } = options ?? {}
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const cancelled = useRef(false)
  // We bump this counter to trigger a manual refetch.
  const [tick, setTick] = useState(0)

  useEffect(() => {
    cancelled.current = false
    let timer: number | undefined

    const run = async () => {
      try {
        setError(null)
        const result = await fetcher()
        if (!cancelled.current) {
          setData(result)
          setLoading(false)
        }
      } catch (e) {
        if (!cancelled.current) {
          setError(e as Error)
          setLoading(false)
        }
      }
    }

    run()
    if (intervalMs && intervalMs > 0) {
      timer = window.setInterval(run, intervalMs)
    }
    return () => {
      cancelled.current = true
      if (timer !== undefined) window.clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, intervalMs, ...deps])

  return {
    data,
    loading,
    error,
    refetch: () => setTick((t) => t + 1),
  }
}