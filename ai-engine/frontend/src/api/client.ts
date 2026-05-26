import type {
  AlertOut,
  CurrentScoreOut,
  DeviceOut,
  EventOut,
  UserProfileOut,
} from './types'

// Thin typed wrapper around fetch. We rely on Vite's dev-server proxy
// (/api → :8000) so URLs are always relative; production deployments
// can serve frontend + backend from the same origin.

class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly url: string,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new ApiError(
      response.status,
      path,
      `${response.status} ${response.statusText}: ${text}`,
    )
  }
  return (await response.json()) as T
}

// ---- typed endpoints ------------------------------------------------------

export type EventsQuery = {
  zone?: string
  user_id?: string
  classification?: string
  from?: string
  to?: string
  limit?: number
}

function qs(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== '',
  )
  if (entries.length === 0) return ''
  const usp = new URLSearchParams()
  for (const [k, v] of entries) usp.set(k, String(v))
  return `?${usp.toString()}`
}

export const api = {
  events: (q: EventsQuery = {}) =>
    request<EventOut[]>(`/api/events${qs(q)}`),

  alertsActive: () =>
    request<AlertOut[]>('/api/alerts/active'),

  alertsAll: () =>
    request<AlertOut[]>('/api/alerts'),

  acknowledgeAlert: (alertId: string, by: string) =>
    request<{ alert_id: string; acknowledged: boolean; acknowledged_by: string; acknowledged_at: string }>(
      `/api/alert/${alertId}/acknowledge`,
      { method: 'POST', body: JSON.stringify({ by }) },
    ),

  users: () =>
    request<string[]>('/api/users'),

  userProfile: (userId: string) =>
    request<UserProfileOut>(`/api/users/${encodeURIComponent(userId)}/profile`),

  devices: () =>
    request<DeviceOut[]>('/api/devices'),

  scoreCurrent: () =>
    request<CurrentScoreOut>('/api/score/current'),
}