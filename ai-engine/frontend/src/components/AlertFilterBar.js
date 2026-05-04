import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { EMPTY_FILTER, distinctEventTypes, filterIsActive, } from '../lib/alertFilter';
export function AlertFilterBar({ alerts, filter, onChange, zone = null, onZoneClear, filteredCount, totalCount, }) {
    const eventTypes = distinctEventTypes(alerts);
    const isFiltering = filterIsActive(filter, zone);
    const setClassification = (c) => {
        onChange({
            ...filter,
            classification: filter.classification === c ? null : c,
        });
    };
    const setEventType = (t) => {
        onChange({ ...filter, eventType: t === 'ALL' ? null : t });
    };
    const reset = () => {
        onChange(EMPTY_FILTER);
        if (zone !== null && onZoneClear)
            onZoneClear();
    };
    return (_jsxs("div", { className: "flex flex-wrap items-center gap-2 px-4 py-2 border-b border-border bg-black/20", children: [_jsxs("div", { className: "flex items-center gap-1", children: [_jsx(FilterToggle, { label: "CRITICAL", active: filter.classification === 'CRITICAL', accent: "critical", onClick: () => setClassification('CRITICAL') }), _jsx(FilterToggle, { label: "SUSPECT", active: filter.classification === 'SUSPECT', accent: "suspect", onClick: () => setClassification('SUSPECT') })] }), _jsx("span", { className: "text-border", children: "\u00B7" }), _jsxs("div", { className: "flex items-center gap-1.5", children: [_jsx("label", { className: "text-[10px] uppercase tracking-wider font-mono text-gray-500", children: "Type" }), _jsxs("select", { value: filter.eventType ?? 'ALL', onChange: (e) => setEventType(e.target.value), className: "bg-panel border border-border rounded px-2 py-1 text-xs font-mono text-gray-200", children: [_jsx("option", { value: "ALL", children: "all" }), eventTypes.map((t) => (_jsx("option", { value: t, children: t }, t)))] })] }), zone !== null && (_jsxs(_Fragment, { children: [_jsx("span", { className: "text-border", children: "\u00B7" }), _jsxs("button", { onClick: onZoneClear, className: "inline-flex items-center gap-1 text-[11px] font-mono uppercase tracking-wider px-2 py-1 rounded bg-suspect-soft text-suspect border border-suspect/40 hover:bg-suspect/20", title: "Clear zone filter", children: ["zone ", zone, _jsx("span", { "aria-hidden": "true", children: "\u00D7" })] })] })), _jsx("div", { className: "flex-1" }), isFiltering && (_jsx("button", { onClick: reset, className: "text-[10px] uppercase tracking-wider font-mono text-gray-400 hover:text-gray-100 px-2 py-1 rounded border border-border bg-black/30", children: "reset" })), _jsxs("span", { className: "text-xs font-mono text-gray-500", children: [filteredCount, " / ", totalCount] })] }));
}
function FilterToggle({ label, active, accent, onClick, }) {
    // When active, use the accent color background; otherwise neutral.
    const accentBg = accent === 'critical'
        ? active
            ? 'bg-critical text-white border-critical'
            : 'border-critical/40 text-critical hover:bg-critical-soft'
        : active
            ? 'bg-suspect text-black border-suspect'
            : 'border-suspect/40 text-suspect hover:bg-suspect-soft';
    return (_jsx("button", { onClick: onClick, className: `text-[10px] font-mono uppercase tracking-wider px-2 py-1 rounded border transition ${accentBg}`, children: label }));
}
