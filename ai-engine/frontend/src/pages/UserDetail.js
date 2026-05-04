import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { ClassificationBadge } from '../components/ClassificationBadge';
import { formatDateTime } from '../lib/format';
export default function UserDetail() {
    const users = useApi(api.users);
    const [selected, setSelected] = useState(null);
    useEffect(() => {
        // Default to the first user once the list loads.
        if (selected === null && users.data && users.data.length > 0) {
            setSelected(users.data[0]);
        }
    }, [users.data, selected]);
    return (_jsxs("div", { className: "max-w-7xl mx-auto px-4 py-6 space-y-4", children: [_jsx("h1", { className: "text-lg font-semibold tracking-wide", children: "User detail" }), _jsxs("div", { className: "flex items-center gap-3", children: [_jsx("label", { className: "text-xs uppercase tracking-wider text-gray-500 font-mono", children: "User" }), _jsxs("select", { value: selected ?? '', onChange: (e) => setSelected(e.target.value || null), className: "bg-panel border border-border rounded px-3 py-1.5 text-sm font-mono", children: [_jsx("option", { value: "", children: "\u2014" }), users.data?.map((u) => (_jsx("option", { value: u, children: u }, u)))] })] }), selected && _jsx(UserBlock, { userId: selected })] }));
}
function UserBlock({ userId }) {
    const profile = useApi(() => api.userProfile(userId), { deps: [userId] });
    const events = useApi(() => api.events({ user_id: userId, limit: 200 }), { deps: [userId] });
    return (_jsxs("div", { className: "grid grid-cols-1 lg:grid-cols-3 gap-6", children: [_jsx("div", { className: "lg:col-span-1", children: _jsxs("div", { className: "bg-panel border border-border rounded-lg p-4 space-y-2", children: [profile.loading && (_jsx("p", { className: "text-sm text-gray-500 font-mono", children: "Loading\u2026" })), profile.data && (_jsxs(_Fragment, { children: [_jsx("h2", { className: "text-base font-semibold", children: profile.data.name }), _jsx(KV, { k: "user_id", v: profile.data.user_id }), _jsx(KV, { k: "badge_id", v: profile.data.badge_id }), _jsx(KV, { k: "typical zones", v: profile.data.typical_zones.join(', ') }), _jsx(KV, { k: "typical hours", v: `${profile.data.typical_arrival.slice(0, 5)} – ${profile.data.typical_departure.slice(0, 5)}` }), _jsx(KV, { k: "events total", v: profile.data.n_events_total }), _jsx(KV, { k: "critical events", v: profile.data.n_critical_events, accent: "critical" }), _jsx(KV, { k: "suspect events", v: profile.data.n_suspect_events, accent: "suspect" }), _jsx(KV, { k: "last seen", v: profile.data.last_seen
                                        ? formatDateTime(profile.data.last_seen)
                                        : '—' })] }))] }) }), _jsx("div", { className: "lg:col-span-2", children: _jsxs("div", { className: "bg-panel border border-border rounded-lg overflow-hidden", children: [_jsx("div", { className: "px-4 py-3 border-b border-border", children: _jsx("h3", { className: "text-sm font-semibold uppercase tracking-wider text-gray-300", children: "Recent events" }) }), _jsx("div", { className: "max-h-[600px] overflow-y-auto", children: _jsxs("table", { className: "w-full text-sm", children: [_jsx("thead", { className: "bg-black/40 text-[10px] uppercase tracking-wider text-gray-500 font-mono sticky top-0", children: _jsxs("tr", { children: [_jsx("th", { className: "text-left px-3 py-2", children: "When" }), _jsx("th", { className: "text-left px-3 py-2", children: "Class." }), _jsx("th", { className: "text-left px-3 py-2", children: "Zone" }), _jsx("th", { className: "text-left px-3 py-2", children: "Type" })] }) }), _jsxs("tbody", { className: "divide-y divide-border", children: [events.loading && (_jsx("tr", { children: _jsx("td", { colSpan: 4, className: "px-3 py-3 text-gray-500 font-mono", children: "Loading\u2026" }) })), (events.data ?? []).map((e) => (_jsxs("tr", { className: "hover:bg-black/30", children: [_jsx("td", { className: "px-3 py-1.5 text-[11px] font-mono text-gray-400 whitespace-nowrap", children: formatDateTime(e.timestamp) }), _jsx("td", { className: "px-3 py-1.5", children: _jsx(ClassificationBadge, { classification: e.ai_classification, score: e.ai_score, size: "sm" }) }), _jsx("td", { className: "px-3 py-1.5 font-mono text-xs", children: e.zone_id }), _jsx("td", { className: "px-3 py-1.5 text-xs", children: e.event_type })] }, e.event_id)))] })] }) })] }) })] }));
}
function KV({ k, v, accent, }) {
    const accentClass = accent === 'critical'
        ? 'text-critical'
        : accent === 'suspect'
            ? 'text-suspect'
            : 'text-gray-100';
    return (_jsxs("div", { className: "flex justify-between items-baseline border-b border-border/60 last:border-0 py-1", children: [_jsx("span", { className: "text-[10px] uppercase tracking-wider text-gray-500 font-mono", children: k }), _jsx("span", { className: `text-sm font-mono ${accentClass}`, children: v })] }));
}
