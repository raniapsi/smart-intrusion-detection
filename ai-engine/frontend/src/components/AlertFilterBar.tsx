import type { AlertOut } from '../api/types'
import {
  type AlertFilter,
  EMPTY_FILTER,
  distinctEventTypes,
  filterIsActive,
} from '../lib/alertFilter'

type Props = {
  // Source list — used to populate the event-type dropdown options.
  alerts: AlertOut[]
  // Currently applied filter; AlertFilterBar is fully controlled.
  filter: AlertFilter
  onChange: (next: AlertFilter) => void
  // Optional zone filter coming from elsewhere (the building map click).
  // Displayed in the badge bar and reset alongside the others.
  zone?: string | null
  onZoneClear?: () => void
  // Counts displayed on the right ("X / Y").
  filteredCount: number
  totalCount: number
}

export function AlertFilterBar({
  alerts,
  filter,
  onChange,
  zone = null,
  onZoneClear,
  filteredCount,
  totalCount,
}: Props) {
  const eventTypes = distinctEventTypes(alerts)
  const isFiltering = filterIsActive(filter, zone)

  const setClassification = (c: 'CRITICAL' | 'SUSPECT') => {
    onChange({
      ...filter,
      classification: filter.classification === c ? null : c,
    })
  }

  const setEventType = (t: string) => {
    onChange({ ...filter, eventType: t === 'ALL' ? null : t })
  }

  const reset = () => {
    onChange(EMPTY_FILTER)
    if (zone !== null && onZoneClear) onZoneClear()
  }

  return (
    <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-border bg-black/20">
      {/* Classification toggles */}
      <div className="flex items-center gap-1">
        <FilterToggle
          label="CRITICAL"
          active={filter.classification === 'CRITICAL'}
          accent="critical"
          onClick={() => setClassification('CRITICAL')}
        />
        <FilterToggle
          label="SUSPECT"
          active={filter.classification === 'SUSPECT'}
          accent="suspect"
          onClick={() => setClassification('SUSPECT')}
        />
      </div>

      <span className="text-border">·</span>

      {/* Event-type dropdown */}
      <div className="flex items-center gap-1.5">
        <label className="text-[10px] uppercase tracking-wider font-mono text-gray-500">
          Type
        </label>
        <select
          value={filter.eventType ?? 'ALL'}
          onChange={(e) => setEventType(e.target.value)}
          className="bg-panel border border-border rounded px-2 py-1 text-xs font-mono text-gray-200"
        >
          <option value="ALL">all</option>
          {eventTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      {/* Active zone filter chip (driven by the building map) */}
      {zone !== null && (
        <>
          <span className="text-border">·</span>
          <button
            onClick={onZoneClear}
            className="inline-flex items-center gap-1 text-[11px] font-mono uppercase tracking-wider px-2 py-1 rounded bg-suspect-soft text-suspect border border-suspect/40 hover:bg-suspect/20"
            title="Clear zone filter"
          >
            zone {zone}
            <span aria-hidden="true">×</span>
          </button>
        </>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Reset + counter */}
      {isFiltering && (
        <button
          onClick={reset}
          className="text-[10px] uppercase tracking-wider font-mono text-gray-400 hover:text-gray-100 px-2 py-1 rounded border border-border bg-black/30"
        >
          reset
        </button>
      )}
      <span className="text-xs font-mono text-gray-500">
        {filteredCount} / {totalCount}
      </span>
    </div>
  )
}

function FilterToggle({
  label,
  active,
  accent,
  onClick,
}: {
  label: string
  active: boolean
  accent: 'critical' | 'suspect'
  onClick: () => void
}) {
  // When active, use the accent color background; otherwise neutral.
  const accentBg =
    accent === 'critical'
      ? active
        ? 'bg-critical text-white border-critical'
        : 'border-critical/40 text-critical hover:bg-critical-soft'
      : active
      ? 'bg-suspect text-black border-suspect'
      : 'border-suspect/40 text-suspect hover:bg-suspect-soft'

  return (
    <button
      onClick={onClick}
      className={`text-[10px] font-mono uppercase tracking-wider px-2 py-1 rounded border transition ${accentBg}`}
    >
      {label}
    </button>
  )
}