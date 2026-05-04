import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Link, useLocation } from 'react-router-dom';
export function Header() {
    const location = useLocation();
    const linkClass = (path) => {
        const active = location.pathname === path;
        return `px-3 py-1.5 rounded-md text-sm font-mono uppercase tracking-wider transition-colors ${active ? 'bg-panel text-gray-100' : 'text-gray-400 hover:text-gray-200'}`;
    };
    return (_jsx("header", { className: "border-b border-border bg-ink/95 backdrop-blur sticky top-0 z-10", children: _jsxs("div", { className: "max-w-7xl mx-auto px-4 py-3 flex items-center justify-between", children: [_jsxs("div", { className: "flex items-center gap-3", children: [_jsx("div", { className: "w-2 h-2 rounded-full bg-critical animate-pulse" }), _jsxs("h1", { className: "text-base font-semibold tracking-wide", children: ["SOC ", _jsx("span", { className: "text-gray-500 font-normal", children: "\u2014 Converged IoT/AI Security" })] })] }), _jsxs("nav", { className: "flex items-center gap-1", children: [_jsx(Link, { to: "/", className: linkClass('/'), children: "Dashboard" }), _jsx(Link, { to: "/alerts", className: linkClass('/alerts'), children: "Alerts" }), _jsx(Link, { to: "/users", className: linkClass('/users'), children: "Users" })] })] }) }));
}
