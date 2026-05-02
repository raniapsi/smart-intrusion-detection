import type { CurrentScoreOut, ZoneScoreOut } from '../api/types'
import { classificationColors } from '../lib/format'

// Hand-authored SVG floor plan that mirrors the building_b1.yaml layout.
// We don't try to match real-world coordinates — this is a SOC schematic.
//
// Layout:
//   row 1 (y=20):   Z1 Lobby   |   Z2 Open Office   |   Z3 Meeting
//   row 2 (y=160):  Z5 Cafet.  |   Z4 Engineering   |   Z6 HR
//   far right:      Z7 Archives                        Z8 Server Room
//
// Coordinates are in user-space SVG units; the viewBox handles scaling.

const ZONE_RECTS: Record<string, { x: number; y: number; w: number; h: number }> = {
  Z1: { x: 20,  y: 20,  w: 160, h: 130 },
  Z2: { x: 200, y: 20,  w: 200, h: 130 },
  Z3: { x: 420, y: 20,  w: 160, h: 130 },
  Z5: { x: 20,  y: 170, w: 160, h: 130 },
  Z4: { x: 200, y: 170, w: 200, h: 130 },
  Z6: { x: 420, y: 170, w: 160, h: 130 },
  Z7: { x: 600, y: 20,  w: 160, h: 130 },
  Z8: { x: 600, y: 170, w: 160, h: 130 },
}

type Props = {
  data: CurrentScoreOut | null
  selectedZone: string | null
  onSelectZone: (zoneId: string | null) => void
}

export function BuildingMap({ data, selectedZone, onSelectZone }: Props) {
  return (
    <div className="bg-panel border border-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-300">
          Building B1 — Threat Map
        </h2>
        <div className="flex items-center gap-3 text-[10px] font-mono uppercase">
          <LegendDot color="bg-normal" label="Normal" />
          <LegendDot color="bg-suspect" label="Suspect" />
          <LegendDot color="bg-critical" label="Critical" />
        </div>
      </div>
      <svg viewBox="0 0 780 320" className="w-full h-auto" role="img" aria-label="Building threat map">
        {data?.zones.map((z) => (
          <ZoneShape
            key={z.zone_id}
            zone={z}
            selected={selectedZone === z.zone_id}
            onClick={() => onSelectZone(selectedZone === z.zone_id ? null : z.zone_id)}
          />
        ))}
      </svg>
    </div>
  )
}

function ZoneShape({
  zone,
  selected,
  onClick,
}: {
  zone: ZoneScoreOut
  selected: boolean
  onClick: () => void
}) {
  const r = ZONE_RECTS[zone.zone_id]
  if (r === undefined) return null

  // Color the zone according to its current_score classification.
  const fill = (() => {
    switch (zone.classification) {
      case 'CRITICAL':
        return 'rgba(239, 68, 68, 0.55)'
      case 'SUSPECT':
        return 'rgba(245, 158, 11, 0.45)'
      default:
        return 'rgba(31, 41, 55, 0.85)'
    }
  })()

  const stroke = selected ? '#fbbf24' : 'rgba(75, 85, 99, 1)'
  const strokeWidth = selected ? 3 : 1.5

  return (
    <g
      onClick={onClick}
      style={{ cursor: 'pointer' }}
      className="transition-opacity hover:opacity-90"
    >
      <rect
        x={r.x}
        y={r.y}
        width={r.w}
        height={r.h}
        fill={fill}
        stroke={stroke}
        strokeWidth={strokeWidth}
        rx={6}
      />
      <text
        x={r.x + 10}
        y={r.y + 22}
        className="fill-gray-100 text-[12px] font-semibold font-mono"
      >
        {zone.zone_id} — {zone.zone_name}
      </text>
      <text
        x={r.x + 10}
        y={r.y + 42}
        className="fill-gray-400 text-[10px] font-mono uppercase"
      >
        {zone.sensitivity}
      </text>
      <text
        x={r.x + r.w - 10}
        y={r.y + r.h - 12}
        textAnchor="end"
        className="fill-gray-100 text-[18px] font-mono font-bold"
      >
        {zone.current_score.toFixed(2)}
      </text>
      <text
        x={r.x + r.w - 10}
        y={r.y + r.h - 30}
        textAnchor="end"
        className="fill-gray-300 text-[9px] font-mono uppercase tracking-wider"
      >
        {zone.classification}
      </text>
    </g>
  )
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block w-2.5 h-2.5 rounded-full ${color}`} />
      <span className="text-gray-400">{label}</span>
    </span>
  )
}