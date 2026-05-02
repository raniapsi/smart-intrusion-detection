import { useState } from 'react'
import type { AlertOut } from '../api/types'
import { api } from '../api/client'
import { formatDateTime } from '../lib/format'
import { ClassificationBadge } from './ClassificationBadge'

type Props = {
  alerts: AlertOut[]
  loading: boolean
  onAcknowledged: () => void
  filterZone: string | null
}

export function AlertFeed({ alerts, loading, onAcknowledged, filterZone }: Props) {
  const filtered = filterZone
    ? alerts.filter((a) => a.zone_id === filterZone)
    : alerts

  return (
    <div className="bg-panel border border-border rounded-lg flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-300">
          Active alerts {filterZone && (
            <span className="text-suspect normal-case font-mono text-xs">
              · zone {filterZone}
            </span>
          )}
        </h2>
        <span className="text-xs font-mono text-gray-500">
          {filtered.length} {filtered.length === 1 ? 'alert' : 'alerts'}
        </span>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-border">
        {loading && (
          <div className="p-4 text-sm text-gray-500 font-mono">Loading…</div>
        )}
        {!loading && filtered.length === 0 && (
          <div className="p-4 text-sm text-gray-500 font-mono">
            No active alerts.
          </div>
        )}
        {filtered.map((alert) => (
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