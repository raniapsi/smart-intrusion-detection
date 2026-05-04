import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo, useState } from 'react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { useEventStream } from '../hooks/useEventStream';
import { AlertFeed } from '../components/AlertFeed';
import { AlertFilterBar } from '../components/AlertFilterBar';
import { BuildingMap } from '../components/BuildingMap';
import { LiveTicker } from '../components/LiveTicker';
import { ScoreCard } from '../components/ScoreCard';
import { EMPTY_FILTER, filterAlerts } from '../lib/alertFilter';
export default function Dashboard() {
    // Score gets refreshed every 2s — cheap and gives a "live" feel.
    const score = useApi(api.scoreCurrent, { intervalMs: 2000 });
    // Alerts polled every 3s. Acknowledging will trigger a manual refetch.
    const alerts = useApi(api.alertsActive, { intervalMs: 3000 });
    const stream = useEventStream();
    const [selectedZone, setSelectedZone] = useState(null);
    const [filter, setFilter] = useState(EMPTY_FILTER);
    // The full list as returned by the API; the filter bar uses this to
    // populate its event-type dropdown so it only shows types that exist.
    const allAlerts = alerts.data ?? [];
    // Final list rendered by the feed: zone (from map click) + bar filters
    // combined with AND.
    const visibleAlerts = useMemo(() => filterAlerts(allAlerts, filter, selectedZone), [allAlerts, filter, selectedZone]);
    return (_jsxs("div", { className: "max-w-7xl mx-auto px-4 py-6 space-y-6", children: [_jsx(ScoreCard, { data: score.data, loading: score.loading, wsConnected: stream.connected }), _jsx(BuildingMap, { data: score.data, selectedZone: selectedZone, onSelectZone: setSelectedZone }), _jsxs("div", { className: "grid grid-cols-1 lg:grid-cols-2 gap-6 min-h-[420px]", children: [_jsx(AlertFeed, { alerts: visibleAlerts, loading: alerts.loading, onAcknowledged: alerts.refetch, filterBar: _jsx(AlertFilterBar, { alerts: allAlerts, filter: filter, onChange: setFilter, zone: selectedZone, onZoneClear: () => setSelectedZone(null), filteredCount: visibleAlerts.length, totalCount: allAlerts.length }) }), _jsx(LiveTicker, { events: stream.events, filterZone: selectedZone })] })] }));
}
