// API response types — must stay in sync with backend/api_models.py.
// These are the SHAPES returned by the FastAPI endpoints; the dashboard
// consumes them directly.

export type Classification = 'NORMAL' | 'SUSPECT' | 'CRITICAL'

export type EventOut = {
  event_id: string
  timestamp: string // ISO 8601
  event_type: string
  source_layer: 'PHYSICAL' | 'CYBER'
  zone_id: string
  device_id: string
  user_id: string | null
  ai_score: number
  ai_classification: Classification
}

export type AlertOut = {
  alert_id: string
  created_at: string
  triggering_event_id: string
  building_id: string
  zone_id: string
  user_id: string | null
  classification: 'SUSPECT' | 'CRITICAL'
  score: number
  title: string
  description: string
  contributing_detectors: string[]
  suggested_action: string | null
  acknowledged: boolean
  acknowledged_by: string | null
  acknowledged_at: string | null
}

export type UserProfileOut = {
  user_id: string
  name: string
  badge_id: string
  typical_zones: string[]
  typical_arrival: string
  typical_departure: string
  n_events_total: number
  n_critical_events: number
  n_suspect_events: number
  last_seen: string | null
}

export type DeviceOut = {
  device_id: string
  type: string
  zone_id: string
  ip_address: string | null
}

export type ZoneScoreOut = {
  zone_id: string
  zone_name: string
  sensitivity: 'PUBLIC' | 'STANDARD' | 'RESTRICTED' | 'CRITICAL'
  current_score: number
  classification: Classification
}

export type CurrentScoreOut = {
  timestamp: string
  building_id: string
  zones: ZoneScoreOut[]
  n_active_alerts: number
}

// Push payload over WebSocket. The backend currently sends "hello" once
// then "event" frames for non-NORMAL events.
export type WsHello = {
  type: 'hello'
  n_active_alerts: number
  n_zones: number
  n_events: number
}

export type WsEvent = {
  type: 'event'
  event_id: string
  timestamp: string
  event_type: string
  zone_id: string
  device_id: string
  user_id: string | null
  ai_score: number
  ai_classification: Classification
}

export type WsMessage = WsHello | WsEvent