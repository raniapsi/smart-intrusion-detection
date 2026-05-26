import { useMemo, useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../hooks/useApi'
import { AlertFilterBar } from '../components/AlertFilterBar'
import { ClassificationBadge } from '../components/ClassificationBadge'
import { formatDateTime } from '../lib/format'
import { EMPTY_FILTER, filterAlerts, type AlertFilter } from '../lib/alertFilter'

export default function AlertsPage() {
  const [showAcked, setShowAcked] = useState(false)
  const fetcher = showAcked ? api.alertsAll : api.alertsActive
  const alerts = useApi(fetcher, { intervalMs: 5000, deps: [showAcked] })

  const [filter, setFilter] = useState<AlertFilter>(EMPTY_FILTER)
  const allAlerts = alerts.data ?? []

  // Pass null for the zone — clicking the building map is a Dashboard-only
  // affordance. The bar will not display the zone chip.
  const visibleAlerts = useMemo(
    () => filterAlerts(allAlerts, filter, null),
    [allAlerts, filter],
  )

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold tracking-wide">Alerts</h1>
        <label className="flex items-center gap-2 text-sm font-mono text-gray-400">
          <input
            type="checkbox"
            checked={showAcked}
            onChange={(e) => setShowAcked(e.target.checked)}
            className="accent-critical"
          />
          Include acknowledged
        </label>
      </div>

      <div className="bg-panel border border-border rounded-lg overflow-hidden">
        <AlertFilterBar
          alerts={allAlerts}
          filter={filter}
          onChange={setFilter}
          filteredCount={visibleAlerts.length}
          totalCount={allAlerts.length}
        />
        <table className="w-full text-sm">
          <thead className="bg-black/40 text-[10px] uppercase tracking-wider text-gray-500 font-mono">
            <tr>
              <th className="text-left px-3 py-2">Created</th>
              <th className="text-left px-3 py-2">Class.</th>
              <th className="text-left px-3 py-2">Zone</th>
              <th className="text-left px-3 py-2">User</th>
              <th className="text-left px-3 py-2">Title</th>
              <th className="text-left px-3 py-2">Detectors</th>
              <th className="text-left px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {alerts.loading && (
              <tr>
                <td colSpan={7} className="px-3 py-4 text-gray-500 font-mono">
                  Loading…
                </td>
              </tr>
            )}
            {!alerts.loading && visibleAlerts.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-4 text-gray-500 font-mono">
                  No alerts to show.
                </td>
              </tr>
            )}
            {visibleAlerts.map((a) => (
              <tr key={a.alert_id} className="hover:bg-black/30">
                <td className="px-3 py-2 text-xs font-mono text-gray-400 whitespace-nowrap">
                  {formatDateTime(a.created_at)}
                </td>
                <td className="px-3 py-2">
                  <ClassificationBadge
                    classification={a.classification}
                    score={a.score}
                    size="sm"
                  />
                </td>
                <td className="px-3 py-2 font-mono text-xs">{a.zone_id}</td>
                <td className="px-3 py-2 font-mono text-xs text-gray-400">
                  {a.user_id ?? '—'}
                </td>
                <td className="px-3 py-2">{a.title}</td>
                <td className="px-3 py-2 text-[10px] font-mono text-gray-500">
                  {a.contributing_detectors.join(' · ')}
                </td>
                <td className="px-3 py-2 text-xs font-mono">
                  {a.acknowledged ? (
                    <span className="text-normal">
                      acked by {a.acknowledged_by}
                    </span>
                  ) : (
                    <span className="text-suspect">open</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}