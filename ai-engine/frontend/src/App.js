import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Route, Routes } from 'react-router-dom';
import { Header } from './components/Header';
import AlertsPage from './pages/AlertsPage';
import Dashboard from './pages/Dashboard';
import UserDetail from './pages/UserDetail';
export default function App() {
    return (_jsxs("div", { className: "min-h-screen bg-ink text-gray-100", children: [_jsx(Header, {}), _jsx("main", { children: _jsxs(Routes, { children: [_jsx(Route, { path: "/", element: _jsx(Dashboard, {}) }), _jsx(Route, { path: "/alerts", element: _jsx(AlertsPage, {}) }), _jsx(Route, { path: "/users", element: _jsx(UserDetail, {}) }), _jsx(Route, { path: "*", element: _jsx("div", { className: "max-w-7xl mx-auto px-4 py-12 text-center text-gray-500 font-mono", children: "Page not found." }) })] }) })] }));
}
