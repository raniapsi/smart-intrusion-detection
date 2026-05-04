// Thin typed wrapper around fetch. We rely on Vite's dev-server proxy
// (/api → :8000) so URLs are always relative; production deployments
// can serve frontend + backend from the same origin.
class ApiError extends Error {
    status;
    url;
    constructor(status, url, message) {
        super(message);
        this.status = status;
        this.url = url;
        this.name = 'ApiError';
    }
}
async function request(path, init) {
    const response = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...init,
    });
    if (!response.ok) {
        const text = await response.text().catch(() => '');
        throw new ApiError(response.status, path, `${response.status} ${response.statusText}: ${text}`);
    }
    return (await response.json());
}
function qs(params) {
    const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '');
    if (entries.length === 0)
        return '';
    const usp = new URLSearchParams();
    for (const [k, v] of entries)
        usp.set(k, String(v));
    return `?${usp.toString()}`;
}
export const api = {
    events: (q = {}) => request(`/api/events${qs(q)}`),
    alertsActive: () => request('/api/alerts/active'),
    alertsAll: () => request('/api/alerts'),
    acknowledgeAlert: (alertId, by) => request(`/api/alert/${alertId}/acknowledge`, { method: 'POST', body: JSON.stringify({ by }) }),
    users: () => request('/api/users'),
    userProfile: (userId) => request(`/api/users/${encodeURIComponent(userId)}/profile`),
    devices: () => request('/api/devices'),
    scoreCurrent: () => request('/api/score/current'),
};
