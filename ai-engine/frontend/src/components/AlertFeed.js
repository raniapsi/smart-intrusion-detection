import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
import { useState } from 'react';
import { api } from '../api/client';
import { formatDateTime } from '../lib/format';
import { ClassificationBadge } from './ClassificationBadge';
export function AlertFeed({ alerts, loading, onAcknowledged, filterBar, filterLabel = null, }) {
    return (_jsxs("div", { className: "bg-panel border border-border rounded-lg flex flex-col h-full", children: [_jsxs("div", { className: "flex items-center justify-between px-4 py-3 border-b border-border", children: [_jsxs("h2", { className: "text-sm font-semibold uppercase tracking-wider text-gray-300", children: ["Active alerts", filterLabel && (_jsxs("span", { className: "text-suspect normal-case font-mono text-xs", children: [' · ', filterLabel] }))] }), _jsxs("span", { className: "text-xs font-mono text-gray-500", children: [alerts.length, " ", alerts.length === 1 ? 'alert' : 'alerts'] })] }), filterBar, _jsxs("div", { className: "flex-1 overflow-y-auto divide-y divide-border", children: [loading && (_jsx("div", { className: "p-4 text-sm text-gray-500 font-mono", children: "Loading\u2026" })), !loading && alerts.length === 0 && (_jsx("div", { className: "p-4 text-sm text-gray-500 font-mono", children: "No alerts to show." })), alerts.map((alert) => (_jsx(AlertRow, { alert: alert, onAcknowledged: onAcknowledged }, alert.alert_id)))] })] }));
}
function AlertRow({ alert, onAcknowledged, }) {
    const [busy, setBusy] = useState(false);
    const handleAck = async () => {
        setBusy(true);
        try {
            await api.acknowledgeAlert(alert.alert_id, 'soc-operator');
            onAcknowledged();
        }
        catch (e) {
            // The user will see that nothing happened; we don't surface the
            // error in the UI for this POC.
            console.error('ack failed', e);
        }
        finally {
            setBusy(false);
        }
    };
    return (_jsx("div", { className: "px-4 py-3 hover:bg-black/30 transition-colors", children: _jsxs("div", { className: "flex items-start justify-between gap-3", children: [_jsxs("div", { className: "flex-1 min-w-0", children: [_jsxs("div", { className: "flex items-center gap-2 mb-1", children: [_jsx(ClassificationBadge, { classification: alert.classification, score: alert.score, size: "sm" }), _jsx("span", { className: "text-xs font-mono text-gray-400", children: alert.zone_id }), alert.user_id && (_jsxs("span", { className: "text-xs font-mono text-gray-500", children: ["\u00B7 ", alert.user_id] }))] }), _jsx("p", { className: "text-sm text-gray-100 leading-snug", children: alert.title }), _jsx("p", { className: "text-xs text-gray-500 mt-1 line-clamp-2", children: alert.description }), alert.suggested_action && (_jsxs("p", { className: "text-[11px] font-mono text-suspect mt-1", children: ["\u21B3 ", alert.suggested_action] })), alert.contributing_detectors.length > 0 && (_jsx("p", { className: "text-[10px] font-mono text-gray-600 mt-1", children: alert.contributing_detectors.join(' · ') }))] }), _jsxs("div", { className: "flex flex-col items-end gap-2 shrink-0", children: [_jsx("span", { className: "text-[10px] font-mono text-gray-500", children: formatDateTime(alert.created_at) }), _jsx("button", { onClick: handleAck, disabled: busy, className: "text-[11px] font-mono uppercase tracking-wide px-2 py-1 rounded border border-border bg-black/30 hover:bg-black/50 transition disabled:opacity-50", children: busy ? 'Acking…' : 'Acknowledge' })] })] }) }));
}
