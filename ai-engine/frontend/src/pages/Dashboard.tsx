import { useMemo, useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../hooks/useApi'
import { useEventStream } from '../hooks/useEventStream'
import { AlertFeed } from '../components/AlertFeed'
import { AlertFilterBar } from '../components/AlertFilterBar'
import { BuildingMap } from '../components/BuildingMap'
import { LiveTicker } from '../components/LiveTicker'
import { ScoreCard } from '../components/ScoreCard'
import { EMPTY_FILTER, filterAlerts, type AlertFilter } from '../lib/alertFilter'

export default function Dashboard() {
  // Score gets refreshed every 2s — cheap and gives a "live" feel.
  const score = useApi(api.scoreCurrent, { intervalMs: 2000 })
  // Alerts polled every 3s. Acknowledging will trigger a manual refetch.
  const alerts = useApi(api.alertsActive, { intervalMs: 3000 })

  const stream = useEventStream()
  const [selectedZone, setSelectedZone] = useState<string | null>(null)
  const [filter, setFilter] = useState<AlertFilter>(EMPTY_FILTER)

  // The full list as returned by the API; the filter bar uses this to
  // populate its event-type dropdown so it only shows types that exist.
  const allAlerts = alerts.data ?? []
  // Final list rendered by the feed: zone (from map click) + bar filters
  // combined with AND.
  const visibleAlerts = useMemo(
    () => filterAlerts(allAlerts, filter, selectedZone),
    [allAlerts, filter, selectedZone],
  )

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
      <ScoreCard
        data={score.data}
        loading={score.loading}
        wsConnected={stream.connected}
      />

      <BuildingMap
        data={score.data}
        selectedZone={selectedZone}
        onSelectZone={setSelectedZone}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 min-h-[420px]">
        <AlertFeed
          alerts={visibleAlerts}
          loading={alerts.loading}
          onAcknowledged={alerts.refetch}
          filterBar={
            <AlertFilterBar
              alerts={allAlerts}
              filter={filter}
              onChange={setFilter}
              zone={selectedZone}
              onZoneClear={() => setSelectedZone(null)}
              filteredCount={visibleAlerts.length}
              totalCount={allAlerts.length}
            />
          }
        />
        <LiveTicker events={stream.events} filterZone={selectedZone} />
      </div>
    </div>
  )
}