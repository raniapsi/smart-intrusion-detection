import { useState } from 'react'
import type { AlertOut } from '../api/types'
import { api } from '../api/client'
import { formatDateTime } from '../lib/format'
import { ClassificationBadge } from './ClassificationBadge'

type Props = {
  // Already-filtered list — AlertFeed is dumb, it does no filtering.
  alerts: AlertOut[]
  loading: boolean
  onAcknowledged: () => void
  // Optional filter bar / extra header rendered just below the title.
  filterBar?: React.ReactNode
  // Used in the title to indicate active filtering. Caller decides what
  // to pass (e.g. "zone Z8", "filtered", "CRITICAL", etc.).
  filterLabel?: string | null
}

export function AlertFeed({
  alerts,
  loading,
  onAcknowledged,
  filterBar,
  filterLabel = null,
}: Props) {
  return (
    <div className="bg-panel border border-border rounded-lg flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-300">
          Active alerts
          {filterLabel && (
            <span className="text-suspect normal-case font-mono text-xs">
              {' · '}{filterLabel}
            </span>
          )}
        </h2>
        <span className="text-xs font-mono text-gray-500">
          {alerts.length} {alerts.length === 1 ? 'alert' : 'alerts'}
        </span>
      </div>
      {filterBar}
      <div className="flex-1 overflow-y-auto divide-y divide-border">
        {loading && (
          <div className="p-4 text-sm text-gray-500 font-mono">Loading…</div>
        )}
        {!loading && alerts.length === 0 && (
          <div className="p-4 text-sm text-gray-500 font-mono">
            No alerts to show.
          </div>
        )}
        {alerts.map((alert) => (
          <AlertRow key={alert.alert_id} alert={alert} onAcknowledged={onAcknowledged} />
        ))}
      </div>
    </div>
  )
}

function AlertRow({
  alert,
  onAcknowledged,
}: {
  alert: AlertOut
  onAcknowledged: () => void
}) {
  const [busy, setBusy] = useState(false)

  const handleAck = async () => {
    setBusy(true)
    try {
      await api.acknowledgeAlert(alert.alert_id, 'soc-operator')
      onAcknowledged()
    } catch (e) {
      // The user will see that nothing happened; we don't surface the
      // error in the UI for this POC.
      console.error('ack failed', e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="px-4 py-3 hover:bg-black/30 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <ClassificationBadge
              classification={alert.classification}
              score={alert.score}
              size="sm"
            />
            <span className="text-xs font-mono text-gray-400">
              {alert.zone_id}
            </span>
            {alert.user_id && (
              <span className="text-xs font-mono text-gray-500">
                · {alert.user_id}
              </span>
            )}
          </div>
          <p className="text-sm text-gray-100 leading-snug">{alert.title}</p>
          <p className="text-xs text-gray-500 mt-1 line-clamp-2">
            {alert.description}
          </p>
          {alert.suggested_action && (
            <p className="text-[11px] font-mono text-suspect mt-1">
              ↳ {alert.suggested_action}
            </p>
          )}
          {alert.contributing_detectors.length > 0 && (
            <p className="text-[10px] font-mono text-gray-600 mt-1">
              {alert.contributing_detectors.join(' · ')}
            </p>
          )}
        </div>
        <div className="flex flex-col items-end gap-2 shrink-0">
          <span className="text-[10px] font-mono text-gray-500">
            {formatDateTime(alert.created_at)}
          </span>
          <button
            onClick={handleAck}
            disabled={busy}
            className="text-[11px] font-mono uppercase tracking-wide px-2 py-1 rounded border border-border bg-black/30 hover:bg-black/50 transition disabled:opacity-50"
          >
            {busy ? 'Acking…' : 'Acknowledge'}
          </button>
        </div>
      </div>
    </div>
  )
}