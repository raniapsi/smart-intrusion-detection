import { useEffect, useRef, useState } from 'react'
import type { WsEvent, WsHello, WsMessage } from '../api/types'

// WebSocket connection to /ws/events. Auto-reconnects on disconnect with
// a small backoff. Keeps a rolling buffer of the most recent events so
// the dashboard can show a live feed without re-fetching from the API.

const MAX_BUFFER = 200
const RECONNECT_INITIAL_MS = 1000
const RECONNECT_MAX_MS = 15000

export type LiveStreamState = {
  connected: boolean
  hello: WsHello | null
  events: WsEvent[]   // newest first
}

export function useEventStream(): LiveStreamState {
  const [connected, setConnected] = useState(false)
  const [hello, setHello] = useState<WsHello | null>(null)
  const [events, setEvents] = useState<WsEvent[]>([])

  const wsRef = useRef<WebSocket | null>(null)
  // Reconnect logic uses an exponential backoff, kept here in a ref so
  // re-renders don't reset it.
  const backoffRef = useRef<number>(RECONNECT_INITIAL_MS)
  const reconnectTimer = useRef<number | undefined>(undefined)
  const stopped = useRef(false)

  useEffect(() => {
    stopped.current = false

    const connect = () => {
      if (stopped.current) return
      // Build the WebSocket URL from the current page's origin so the same
      // code works under Vite dev (proxy) and in production.
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url = `${protocol}://${window.location.host}/ws/events`
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        backoffRef.current = RECONNECT_INITIAL_MS
      }

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data) as WsMessage
          if (msg.type === 'hello') {
            setHello(msg)
          } else if (msg.type === 'event') {
            setEvents((prev) => [msg, ...prev].slice(0, MAX_BUFFER))
          }
        } catch {
          // ignore malformed frames
        }
      }

      ws.onclose = () => {
        setConnected(false)
        wsRef.current = null
        if (stopped.current) return
        // Schedule a reconnect with backoff.
        const delay = backoffRef.current
        backoffRef.current = Math.min(delay * 2, RECONNECT_MAX_MS)
        reconnectTimer.current = window.setTimeout(connect, delay)
      }

      ws.onerror = () => {
        // The browser will follow with onclose; nothing else to do here.
      }
    }

    connect()

    return () => {
      stopped.current = true
      if (reconnectTimer.current !== undefined) {
        window.clearTimeout(reconnectTimer.current)
      }
      const ws = wsRef.current
      if (ws !== null) ws.close()
    }
  }, [])

  return { connected, hello, events }
}