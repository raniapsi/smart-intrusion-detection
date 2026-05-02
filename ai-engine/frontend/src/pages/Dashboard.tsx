import { useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../hooks/useApi'
import { useEventStream } from '../hooks/useEventStream'
import { AlertFeed } from '../components/AlertFeed'
import { BuildingMap } from '../components/BuildingMap'
import { LiveTicker } from '../components/LiveTicker'
import { ScoreCard } from '../components/ScoreCard'

export default function Dashboard() {
  // Score gets refreshed every 2s — cheap and gives a "live" feel.
  const score = useApi(api.scoreCurrent, { intervalMs: 2000 })
  // Alerts polled every 3s. Acknowledging will trigger a manual refetch.
  const alerts = useApi(api.alertsActive, { intervalMs: 3000 })

  const stream = useEventStream()
  const [selectedZone, setSelectedZone] = useState<string | null>(null)

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
          alerts={alerts.data ?? []}
          loading={alerts.loading}
          onAcknowledged={alerts.refetch}
          filterZone={selectedZone}
        />
        <LiveTicker events={stream.events} filterZone={selectedZone} />
      </div>
    </div>
  )
}