import type { WsEvent } from '../api/types'
import { ClassificationBadge } from './ClassificationBadge'
import { formatTime } from '../lib/format'

type Props = {
  events: WsEvent[]
  filterZone: string | null
}

export function LiveTicker({ events, filterZone }: Props) {
  const filtered = filterZone
    ? events.filter((e) => e.zone_id === filterZone)
    : events

  return (
    <div className="bg-panel border border-border rounded-lg flex flex-col h-full">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-300">
          Live event stream{' '}
          {filterZone && (
            <span className="text-suspect normal-case font-mono text-xs">
              · zone {filterZone}
            </span>
          )}
        </h2>
        <span className="text-xs font-mono text-gray-500">
          {filtered.length} recent
        </span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="p-4 text-sm text-gray-500 font-mono">
            Waiting for live events…
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {filtered.slice(0, 50).map((e) => (
              <li key={e.event_id} className="px-4 py-2 flex items-center gap-3">
                <span className="text-[10px] font-mono text-gray-500 w-16 shrink-0">
                  {formatTime(e.timestamp)}
                </span>
                <ClassificationBadge
                  classification={e.ai_classification}
                  score={e.ai_score}
                  size="sm"
                />
                <span className="text-xs font-mono text-gray-400 w-12 shrink-0">
                  {e.zone_id}
                </span>
                <span className="text-xs text-gray-200 truncate">
                  {e.event_type}
                  {e.user_id && (
                    <span className="text-gray-500"> · {e.user_id}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}