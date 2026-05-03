import { useMemo, useState } from 'react'
import type { Classification, CurrentScoreOut, ZoneScoreOut } from '../api/types'

type Props = {
  data: CurrentScoreOut | null
  selectedZone: string | null
  onSelectZone: (zoneId: string | null) => void
}

type LayerLayout = {
  zoneId: string
  fallbackName: string
  fallbackSensitivity: ZoneScoreOut['sensitivity']
  x: number
  y: number
  w: number
  dx: number
  dy: number
  thickness: number
  statX: number
  statY: number
}

type DisplayZone = ZoneScoreOut & {
  isFallback: boolean
}

// Layout constants — bumping vertical spacing and slab thickness so the
// zone label fits comfortably inside the front face. The viewBox grows
// accordingly: more vertical room is fine since users can scroll the page.
const LAYER_THICKNESS = 56
const LAYER_GAP_Y = 68
const LAYER_DX = 54
const LAYER_DY = 28
const LAYER_W = 380
const FIRST_LAYER_Y = 60
const STAT_X = 830
const STAT_BASE_Y = 60
// Step right by this many user-space units when going UP one layer.
const STAIR_STEP = 38

// Defined in order: top of the stack first (Z8 = server room, most sensitive
// → on top), bottom last (Z1 = lobby).
const ZONE_ORDER: Array<
  Pick<LayerLayout, 'zoneId' | 'fallbackName' | 'fallbackSensitivity'>
> = [
  { zoneId: 'Z8', fallbackName: 'Server Room',   fallbackSensitivity: 'CRITICAL'   },
  { zoneId: 'Z7', fallbackName: 'Archives',      fallbackSensitivity: 'RESTRICTED' },
  { zoneId: 'Z6', fallbackName: 'HR Offices',    fallbackSensitivity: 'STANDARD'   },
  { zoneId: 'Z5', fallbackName: 'Cafeteria',     fallbackSensitivity: 'STANDARD'   },
  { zoneId: 'Z4', fallbackName: 'Engineering',   fallbackSensitivity: 'STANDARD'   },
  { zoneId: 'Z3', fallbackName: 'Meeting Rooms', fallbackSensitivity: 'STANDARD'   },
  { zoneId: 'Z2', fallbackName: 'Open Office',   fallbackSensitivity: 'STANDARD'   },
  { zoneId: 'Z1', fallbackName: 'Lobby',         fallbackSensitivity: 'PUBLIC'     },
]

const LAYERS: LayerLayout[] = ZONE_ORDER.map((entry, i) => {
  // Highest layer (i=0) sits furthest to the right; each step down moves
  // a bit to the left, giving the staircase / depth illusion.
  const stairsAbove = ZONE_ORDER.length - 1 - i
  return {
    ...entry,
    x: 64 + stairsAbove * STAIR_STEP,
    y: FIRST_LAYER_Y + i * LAYER_GAP_Y,
    w: LAYER_W,
    dx: LAYER_DX,
    dy: LAYER_DY,
    thickness: LAYER_THICKNESS,
    statX: STAT_X,
    statY: STAT_BASE_Y + i * LAYER_GAP_Y,
  }
})

const VIEWBOX_W = 1120
const VIEWBOX_H =
  FIRST_LAYER_Y + (LAYERS.length - 1) * LAYER_GAP_Y + LAYER_DY + LAYER_THICKNESS + 80

export function BuildingMap({ data, selectedZone, onSelectZone }: Props) {
  const [hoveredZone, setHoveredZone] = useState<string | null>(null)

  const zonesById = useMemo(() => {
    const map = new Map<string, ZoneScoreOut>()
    for (const zone of data?.zones ?? []) {
      map.set(zone.zone_id, zone)
    }
    return map
  }, [data])

  const displayLayers = useMemo(
    () =>
      LAYERS.map((layout) => ({
        layout,
        zone: toDisplayZone(layout, zonesById.get(layout.zoneId)),
      })),
    [zonesById],
  )

  const toggleZone = (zoneId: string) => {
    onSelectZone(selectedZone === zoneId ? null : zoneId)
  }

  return (
    <div className="bg-panel border border-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-300">
            Building B1 — Layered Threat Map
          </h2>
          <p className="mt-1 text-[10px] font-mono uppercase tracking-wider text-gray-500">
            Stacked perspective view · click a zone to filter alerts and live events
          </p>
        </div>

        <div className="flex items-center gap-3 text-[10px] font-mono uppercase">
          <LegendDot color="bg-normal" label="Normal" />
          <LegendDot color="bg-suspect" label="Suspect" />
          <LegendDot color="bg-critical" label="Critical" />
        </div>
      </div>

      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${VIEWBOX_W} ${VIEWBOX_H}`}
          className="w-full min-w-[900px] h-auto"
          role="img"
          aria-label="Building B1 layered threat map"
        >
          <defs>
            <filter id="softShadow" x="-20%" y="-20%" width="160%" height="160%">
              <feDropShadow
                dx="0"
                dy="10"
                stdDeviation="8"
                floodColor="#020617"
                floodOpacity="0.55"
              />
            </filter>

            <filter id="zoneGlow" x="-30%" y="-30%" width="180%" height="180%">
              <feDropShadow
                dx="0"
                dy="0"
                stdDeviation="4"
                floodColor="#e5e7eb"
                floodOpacity="0.35"
              />
              <feDropShadow
                dx="0"
                dy="12"
                stdDeviation="9"
                floodColor="#020617"
                floodOpacity="0.6"
              />
            </filter>

            <linearGradient id="panelGradient" x1="0" x2="1" y1="0" y2="1">
              <stop offset="0%" stopColor="#111827" />
              <stop offset="100%" stopColor="#0b0f17" />
            </linearGradient>
          </defs>

          <rect x="0" y="0" width={VIEWBOX_W} height={VIEWBOX_H} rx="14" fill="#0b0f17" />

          <g opacity="0.16">
            {Array.from({ length: 18 }).map((_, i) => (
              <line
                key={`grid-v-${i}`}
                x1={i * 70}
                y1="0"
                x2={i * 70}
                y2={VIEWBOX_H}
                stroke="#374151"
              />
            ))}
            {Array.from({ length: Math.ceil(VIEWBOX_H / 65) }).map((_, i) => (
              <line
                key={`grid-h-${i}`}
                x1="0"
                y1={i * 65}
                x2={VIEWBOX_W}
                y2={i * 65}
                stroke="#374151"
              />
            ))}
          </g>

          <text
            x="40"
            y="34"
            className="fill-gray-500 text-[10px] font-mono uppercase tracking-widest"
          >
            Building depth view · restricted areas are represented on upper layers
          </text>

          {displayLayers.map(({ layout, zone }) => {
            const active =
              selectedZone === zone.zone_id || hoveredZone === zone.zone_id
            return (
              <Connector
                key={`connector-${zone.zone_id}`}
                layout={layout}
                zone={zone}
                active={active}
              />
            )
          })}

          {displayLayers.map(({ layout, zone }) => (
            <LayerShape
              key={`layer-${zone.zone_id}`}
              layout={layout}
              zone={zone}
              selected={selectedZone === zone.zone_id}
              hovered={hoveredZone === zone.zone_id}
              onHover={(isHovered) =>
                setHoveredZone(isHovered ? zone.zone_id : null)
              }
              onClick={() => toggleZone(zone.zone_id)}
            />
          ))}

          {displayLayers.map(({ layout, zone }) => {
            const active =
              selectedZone === zone.zone_id || hoveredZone === zone.zone_id
            return (
              <StatsPanel
                key={`panel-${zone.zone_id}`}
                layout={layout}
                zone={zone}
                active={active}
                onClick={() => toggleZone(zone.zone_id)}
              />
            )
          })}

          {selectedZone && (
            <text
              x="40"
              y={VIEWBOX_H - 20}
              className="fill-suspect text-[10px] font-mono uppercase tracking-widest"
            >
              Filter active · selected zone {selectedZone} · click the same layer to reset
            </text>
          )}
        </svg>
      </div>
    </div>
  )
}

function toDisplayZone(layout: LayerLayout, zone?: ZoneScoreOut): DisplayZone {
  if (zone !== undefined) {
    return { ...zone, isFallback: false }
  }
  return {
    zone_id: layout.zoneId,
    zone_name: layout.fallbackName,
    sensitivity: layout.fallbackSensitivity,
    current_score: 0,
    classification: 'NORMAL',
    isFallback: true,
  }
}

function LayerShape({
  layout,
  zone,
  selected,
  hovered,
  onHover,
  onClick,
}: {
  layout: LayerLayout
  zone: DisplayZone
  selected: boolean
  hovered: boolean
  onHover: (isHovered: boolean) => void
  onClick: () => void
}) {
  const colors = svgColors(zone.classification)
  const active = selected || hovered || zone.classification === 'CRITICAL'
  const p = layerPolygons(layout)

  const [nameLine1, nameLine2] = splitZoneName(zone.zone_name, 16)

  // ---- Label placement --------------------------------------------------
  // We anchor the label inside the FRONT FACE of the slab — the bottom
  // rectangle of the perspective shape, which is the only fully visible
  // and rectangular surface. This guarantees the label cannot overflow
  // the zone's outline. Front face spans:
  //   x ∈ [layout.x + layout.dx, layout.x + layout.dx + layout.w]
  //   y ∈ [layout.y + layout.dy, layout.y + layout.dy + layout.thickness]
  const frontX = layout.x + layout.dx
  const frontY = layout.y + layout.dy

  const badgeW = 38
  const badgeH = 22
  const badgeX = frontX + 14
  const badgeY = frontY + (layout.thickness - badgeH) / 2

  const nameX = badgeX + badgeW + 10
  // Vertical baseline for the (single- or two-line) name. We tweak so the
  // text is visually centred on the badge.
  const nameTextY = nameLine2
    ? badgeY + 11    // first of two lines: top half of the badge area
    : badgeY + 16    // single line: vertically centred on the badge

  // Background pill for the whole label group, sized to the longest line.
  const longestNameChars = Math.max(
    nameLine1.length,
    nameLine2 ? nameLine2.length : 0,
  )
  const labelBgWidth = badgeW + 12 + Math.max(longestNameChars * 7.4, 60)
  const labelBgHeight = nameLine2 ? 42 : 32
  const labelBgY = frontY + (layout.thickness - labelBgHeight) / 2

  return (
    <g
      onClick={onClick}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      style={{ cursor: 'pointer' }}
      filter={active ? 'url(#zoneGlow)' : 'url(#softShadow)'}
      opacity={zone.isFallback ? 0.55 : 1}
    >
      <polygon points={p.shadow} fill="#020617" opacity="0.42" />
      <polygon points={p.right} fill={colors.side} stroke="#1f2937" strokeWidth="1.4" />
      <polygon points={p.front} fill={colors.front} stroke="#1f2937" strokeWidth="1.4" />

      <polygon
        points={p.top}
        fill={colors.top}
        stroke={selected ? '#f8fafc' : colors.stroke}
        strokeWidth={selected ? 2.8 : zone.classification === 'CRITICAL' ? 2.1 : 1.5}
      />

      {/* Label background pill — fully inside the front face */}
      <rect
        x={frontX + 8}
        y={labelBgY}
        width={labelBgWidth}
        height={labelBgHeight}
        rx="9"
        fill="rgba(3, 7, 18, 0.55)"
        stroke="rgba(255,255,255,0.08)"
        strokeWidth="1"
      />

      {/* Zone-id badge */}
      <rect
        x={badgeX}
        y={badgeY}
        width={badgeW}
        height={badgeH}
        rx="6"
        fill="rgba(2, 6, 23, 0.85)"
        stroke="rgba(255,255,255,0.1)"
        strokeWidth="1"
      />
      <text
        x={badgeX + badgeW / 2}
        y={badgeY + 15}
        textAnchor="middle"
        fill="#f8fafc"
        style={{
          fontSize: '11px',
          fontWeight: 800,
          fontFamily: 'monospace',
          letterSpacing: '0.08em',
        }}
      >
        {zone.zone_id}
      </text>

      {/* Zone name */}
      <text
        x={nameX}
        y={nameTextY}
        fill="#f8fafc"
        style={{
          fontSize: '13px',
          fontWeight: 800,
          fontFamily: 'monospace',
        }}
      >
        {nameLine1}
      </text>
      {nameLine2 && (
        <text
          x={nameX}
          y={nameTextY + 14}
          fill="#f8fafc"
          style={{
            fontSize: '12px',
            fontWeight: 800,
            fontFamily: 'monospace',
          }}
        >
          {nameLine2}
        </text>
      )}

      {/* Classification + score on the right side of the front face */}
      <text
        x={layout.x + layout.w + layout.dx - 18}
        y={frontY + layout.thickness - 36}
        textAnchor="end"
        fill={colors.stroke}
        className="text-[10px] font-mono font-bold uppercase tracking-wider"
      >
        {zone.classification}
      </text>
      <text
        x={layout.x + layout.w + layout.dx - 18}
        y={frontY + layout.thickness - 12}
        textAnchor="end"
        className="fill-gray-100 text-[22px] font-mono font-bold"
      >
        {zone.current_score.toFixed(2)}
      </text>
    </g>
  )
}

function Connector({
  layout,
  zone,
  active,
}: {
  layout: LayerLayout
  zone: DisplayZone
  active: boolean
}) {
  const colors = svgColors(zone.classification)

  const startX = layout.x + layout.w + layout.dx
  const startY = layout.y + layout.dy + layout.thickness / 2
  const endX = layout.statX
  const endY = layout.statY + 32
  const midX = startX + (endX - startX) * 0.55

  return (
    <g opacity={active ? 1 : 0.42}>
      <path
        d={`M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`}
        fill="none"
        stroke={active ? colors.stroke : '#4b5563'}
        strokeWidth={active ? 2.4 : 1.4}
        strokeDasharray={active ? undefined : '5 7'}
      />
      <circle cx={startX} cy={startY} r={active ? 4 : 3} fill={colors.stroke} />
      <circle cx={endX} cy={endY} r={active ? 4 : 3} fill={colors.stroke} />
    </g>
  )
}

function StatsPanel({
  layout,
  zone,
  active,
  onClick,
}: {
  layout: LayerLayout
  zone: DisplayZone
  active: boolean
  onClick: () => void
}) {
  const colors = svgColors(zone.classification)
  const [nameLine1, nameLine2] = splitZoneName(zone.zone_name, 15)

  const panelWidth = 285
  const panelHeight = nameLine2 ? 78 : 66

  const x = layout.statX
  const y = layout.statY

  const scoreX = x + panelWidth - 18
  const classificationX = x + 208
  const separatorX = x + 214

  return (
    <g
      onClick={onClick}
      style={{ cursor: 'pointer' }}
      filter={active ? 'url(#zoneGlow)' : undefined}
    >
      <rect
        x={x}
        y={y}
        width={panelWidth}
        height={panelHeight}
        rx="10"
        fill="url(#panelGradient)"
        stroke={active ? colors.stroke : '#1f2937'}
        strokeWidth={active ? 1.9 : 1.2}
      />

      <rect
        x={x + 14}
        y={y + 12}
        width="34"
        height="18"
        rx="5"
        fill="rgba(2, 6, 23, 0.72)"
        stroke="rgba(255,255,255,0.08)"
        strokeWidth="1"
      />
      <text
        x={x + 31}
        y={y + 25}
        textAnchor="middle"
        fill="#f8fafc"
        style={{
          fontSize: '10px',
          fontWeight: 800,
          fontFamily: 'monospace',
          letterSpacing: '0.08em',
        }}
      >
        {zone.zone_id}
      </text>

      <text
        x={x + 58}
        y={y + 23}
        className="fill-gray-100 text-[11px] font-semibold font-mono"
      >
        {truncateText(nameLine1, 18)}
      </text>
      {nameLine2 && (
        <text
          x={x + 58}
          y={y + 37}
          className="fill-gray-100 text-[10px] font-semibold font-mono"
        >
          {truncateText(nameLine2, 18)}
        </text>
      )}

      {/* Sensitivity stays in the side panel only */}
      <text
        x={x + 14}
        y={y + (nameLine2 ? 58 : 44)}
        className="fill-gray-500 text-[9px] font-mono uppercase tracking-wider"
      >
        {zone.sensitivity}
      </text>

      <line
        x1={separatorX}
        y1={y + 10}
        x2={separatorX}
        y2={y + panelHeight - 10}
        stroke="rgba(148,163,184,0.18)"
        strokeWidth="1"
      />

      <text
        x={classificationX}
        y={y + 24}
        textAnchor="end"
        fill={colors.stroke}
        className="text-[9px] font-mono font-bold uppercase tracking-wider"
      >
        {zone.classification}
      </text>

      <text
        x={scoreX}
        y={y + (nameLine2 ? 55 : 49)}
        textAnchor="end"
        className="fill-gray-100 text-[22px] font-mono font-bold"
      >
        {zone.current_score.toFixed(2)}
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

function layerPolygons(layout: LayerLayout): {
  top: string
  front: string
  right: string
  shadow: string
} {
  const { x, y, w, dx, dy, thickness } = layout

  return {
    top: points([
      [x, y],
      [x + w, y],
      [x + w + dx, y + dy],
      [x + dx, y + dy],
    ]),
    front: points([
      [x + dx, y + dy],
      [x + w + dx, y + dy],
      [x + w + dx, y + dy + thickness],
      [x + dx, y + dy + thickness],
    ]),
    right: points([
      [x + w, y],
      [x + w + dx, y + dy],
      [x + w + dx, y + dy + thickness],
      [x + w, y + thickness],
    ]),
    shadow: points([
      [x + dx + 12, y + dy + thickness + 8],
      [x + w + dx + 12, y + dy + thickness + 8],
      [x + w + dx + 30, y + dy + thickness + 24],
      [x + dx + 30, y + dy + thickness + 24],
    ]),
  }
}

function points(list: Array<[number, number]>): string {
  return list.map(([x, y]) => `${x},${y}`).join(' ')
}

function splitZoneName(name: string, maxLineLength = 14): [string, string?] {
  if (name.length <= maxLineLength) return [name]

  const words = name.split(' ')
  if (words.length === 1) return [name]

  let line1 = ''
  let line2 = ''

  for (const word of words) {
    const candidate = line1 ? `${line1} ${word}` : word
    if (candidate.length <= maxLineLength || line1.length === 0) {
      line1 = candidate
    } else {
      line2 = line2 ? `${line2} ${word}` : word
    }
  }

  return [line1, line2 || undefined]
}

function truncateText(text: string, max = 22): string {
  if (text.length <= max) return text
  return `${text.slice(0, max - 1)}…`
}

function svgColors(classification: Classification): {
  top: string
  front: string
  side: string
  stroke: string
} {
  switch (classification) {
    case 'CRITICAL':
      return {
        top: 'rgba(239, 68, 68, 0.62)',
        front: 'rgba(127, 29, 29, 0.92)',
        side: 'rgba(91, 20, 26, 0.96)',
        stroke: '#ef4444',
      }
    case 'SUSPECT':
      return {
        top: 'rgba(245, 158, 11, 0.52)',
        front: 'rgba(120, 53, 15, 0.92)',
        side: 'rgba(92, 41, 12, 0.96)',
        stroke: '#f59e0b',
      }
    case 'NORMAL':
    default:
      return {
        top: 'rgba(31, 41, 55, 0.9)',
        front: 'rgba(17, 24, 39, 0.96)',
        side: 'rgba(12, 17, 27, 0.98)',
        stroke: '#10b981',
      }
  }
}