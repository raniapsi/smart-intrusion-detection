import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { EventOut, UserProfileOut } from '../api/types'
import { useApi } from '../hooks/useApi'
import { ClassificationBadge } from '../components/ClassificationBadge'
import { formatDateTime } from '../lib/format'

export default function UserDetail() {
  const users = useApi(api.users)
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    // Default to the first user once the list loads.
    if (selected === null && users.data && users.data.length > 0) {
      setSelected(users.data[0])
    }
  }, [users.data, selected])

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-4">
      <h1 className="text-lg font-semibold tracking-wide">User detail</h1>

      <div className="flex items-center gap-3">
        <label className="text-xs uppercase tracking-wider text-gray-500 font-mono">
          User
        </label>
        <select
          value={selected ?? ''}
          onChange={(e) => setSelected(e.target.value || null)}
          className="bg-panel border border-border rounded px-3 py-1.5 text-sm font-mono"
        >
          <option value="">—</option>
          {users.data?.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
      </div>

      {selected && <UserBlock userId={selected} />}
    </div>
  )
}

function UserBlock({ userId }: { userId: string }) {
  const profile = useApi<UserProfileOut>(
    () => api.userProfile(userId),
    { deps: [userId] },
  )
  const events = useApi<EventOut[]>(
    () => api.events({ user_id: userId, limit: 200 }),
    { deps: [userId] },
  )

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="lg:col-span-1">
        <div className="bg-panel border border-border rounded-lg p-4 space-y-2">
          {profile.loading && (
            <p className="text-sm text-gray-500 font-mono">Loading…</p>
          )}
          {profile.data && (
            <>
              <h2 className="text-base font-semibold">{profile.data.name}</h2>
              <KV k="user_id" v={profile.data.user_id} />
              <KV k="badge_id" v={profile.data.badge_id} />
              <KV
                k="typical zones"
                v={profile.data.typical_zones.join(', ')}
              />
              <KV
                k="typical hours"
                v={`${profile.data.typical_arrival.slice(0, 5)} – ${profile.data.typical_departure.slice(0, 5)}`}
              />
              <KV k="events total" v={profile.data.n_events_total} />
              <KV
                k="critical events"
                v={profile.data.n_critical_events}
                accent="critical"
              />
              <KV
                k="suspect events"
                v={profile.data.n_suspect_events}
                accent="suspect"
              />
              <KV
                k="last seen"
                v={
                  profile.data.last_seen
                    ? formatDateTime(profile.data.last_seen)
                    : '—'
                }
              />
            </>
          )}
        </div>
      </div>

      <div className="lg:col-span-2">
        <div className="bg-panel border border-border rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-300">
              Recent events
            </h3>
          </div>
          <div className="max-h-[600px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-black/40 text-[10px] uppercase tracking-wider text-gray-500 font-mono sticky top-0">
                <tr>
                  <th className="text-left px-3 py-2">When</th>
                  <th className="text-left px-3 py-2">Class.</th>
                  <th className="text-left px-3 py-2">Zone</th>
                  <th className="text-left px-3 py-2">Type</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {events.loading && (
                  <tr>
                    <td colSpan={4} className="px-3 py-3 text-gray-500 font-mono">
                      Loading…
                    </td>
                  </tr>
                )}
                {(events.data ?? []).map((e) => (
                  <tr key={e.event_id} className="hover:bg-black/30">
                    <td className="px-3 py-1.5 text-[11px] font-mono text-gray-400 whitespace-nowrap">
                      {formatDateTime(e.timestamp)}
                    </td>
                    <td className="px-3 py-1.5">
                      <ClassificationBadge
                        classification={e.ai_classification}
                        score={e.ai_score}
                        size="sm"
                      />
                    </td>
                    <td className="px-3 py-1.5 font-mono text-xs">
                      {e.zone_id}
                    </td>
                    <td className="px-3 py-1.5 text-xs">{e.event_type}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

function KV({
  k,
  v,
  accent,
}: {
  k: string
  v: string | number
  accent?: 'critical' | 'suspect'
}) {
  const accentClass =
    accent === 'critical'
      ? 'text-critical'
      : accent === 'suspect'
      ? 'text-suspect'
      : 'text-gray-100'
  return (
    <div className="flex justify-between items-baseline border-b border-border/60 last:border-0 py-1">
      <span className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
        {k}
      </span>
      <span className={`text-sm font-mono ${accentClass}`}>{v}</span>
    </div>
  )
}