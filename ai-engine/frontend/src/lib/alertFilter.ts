import type { AlertOut } from '../api/types'

// State of the filter bar. `null` / empty means "no constraint".
export type AlertFilter = {
  // null = both classifications shown
  classification: 'CRITICAL' | 'SUSPECT' | null
  // null = all event types shown
  eventType: string | null
}

export const EMPTY_FILTER: AlertFilter = {
  classification: null,
  eventType: null,
}

// We don't have the event type directly on AlertOut — alerts hold a title
// and a triggering_event_id. To filter by event_type we read it from the
// alert title's prefix, which we control in alert_builder.py:
//   - "Door D-... forced in zone Z..." → DOOR_FORCED
//   - "Badge access in zone Z..."     → BADGE_ACCESS
//   - "Network anomaly from <device>" → NETWORK_FLOW or NETWORK_ANOMALY
//   - "Motion event in zone Z..."     → MOTION_DETECTED
//   - "Camera event in zone Z..."     → CAMERA_EVENT
//
// Mapping titles to types is brittle but keeps the API surface small.
// A cleaner path is to add an `event_type` field on AlertOut server-side
// (one-line change in api_models.py + alerts route) which we may do later.
const TITLE_TO_TYPE: Array<[RegExp, string]> = [
  [/^Door .* forced/i,         'DOOR_FORCED'],
  [/^Door event/i,             'DOOR_EVENT'],
  [/^Badge access/i,           'BADGE_ACCESS'],
  [/^Network anomaly/i,        'NETWORK_ANOMALY'],
  [/^Motion event/i,           'MOTION_DETECTED'],
  [/^Camera event/i,           'CAMERA_EVENT'],
  [/^Device status/i,          'DEVICE_STATUS'],
]

export function inferEventType(alert: AlertOut): string {
  for (const [re, type] of TITLE_TO_TYPE) {
    if (re.test(alert.title)) return type
  }
  return 'OTHER'
}

// Build the set of event types present in a list of alerts. Used by the
// filter bar to populate the dropdown — we only show types that are
// actually represented, to avoid empty-result combinations.
export function distinctEventTypes(alerts: AlertOut[]): string[] {
  const set = new Set<string>()
  for (const a of alerts) set.add(inferEventType(a))
  return Array.from(set).sort()
}

// Filter alerts according to the AlertFilter and an optional zone (zone
// already comes from the building-map click and is intersected with the
// other filters via AND). Pass `null` for zone to ignore it.
export function filterAlerts(
  alerts: AlertOut[],
  filter: AlertFilter,
  zone: string | null,
): AlertOut[] {
  return alerts.filter((a) => {
    if (zone !== null && a.zone_id !== zone) return false
    if (filter.classification !== null && a.classification !== filter.classification) return false
    if (filter.eventType !== null && inferEventType(a) !== filter.eventType) return false
    return true
  })
}

export function filterIsActive(filter: AlertFilter, zone: string | null): boolean {
  return (
    filter.classification !== null ||
    filter.eventType !== null ||
    zone !== null
  )
}