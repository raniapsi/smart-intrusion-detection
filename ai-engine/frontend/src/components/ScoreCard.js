import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export function ScoreCard({ data, loading, wsConnected }) {
    const nCritical = data?.zones.filter((z) => z.classification === 'CRITICAL').length ?? 0;
    const nSuspect = data?.zones.filter((z) => z.classification === 'SUSPECT').length ?? 0;
    const maxScore = data
        ? data.zones.reduce((m, z) => Math.max(m, z.current_score), 0)
        : 0;
    return (_jsxs("div", { className: "grid grid-cols-2 md:grid-cols-4 gap-3", children: [_jsx(Stat, { label: "Active alerts", value: data?.n_active_alerts ?? '—', loading: loading, accent: data && data.n_active_alerts > 0 ? 'critical' : 'normal' }), _jsx(Stat, { label: "Critical zones", value: nCritical, loading: loading, accent: nCritical > 0 ? 'critical' : 'normal' }), _jsx(Stat, { label: "Suspect zones", value: nSuspect, loading: loading, accent: nSuspect > 0 ? 'suspect' : 'normal' }), _jsx(Stat, { label: "Max zone score", value: loading ? '—' : maxScore.toFixed(2), loading: loading, accent: maxScore >= 0.7 ? 'critical' : maxScore >= 0.3 ? 'suspect' : 'normal' }), _jsxs("div", { className: "col-span-full text-[11px] font-mono text-gray-500 flex items-center gap-2", children: [_jsx("span", { className: `inline-block w-2 h-2 rounded-full ${wsConnected ? 'bg-normal' : 'bg-critical'}` }), "Live stream ", wsConnected ? 'connected' : 'disconnected'] })] }));
}
function Stat({ label, value, loading, accent, }) {
    const accentClass = accent === 'critical'
        ? 'text-critical'
        : accent === 'suspect'
            ? 'text-suspect'
            : 'text-normal';
    return (_jsxs("div", { className: "bg-panel border border-border rounded-lg p-3", children: [_jsx("div", { className: "text-[10px] uppercase tracking-wider text-gray-500 font-mono", children: label }), _jsx("div", { className: `mt-1 text-2xl font-mono font-bold ${accentClass}`, children: loading ? '…' : value })] }));
}
