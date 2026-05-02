import { Link, useLocation } from 'react-router-dom'

export function Header() {
  const location = useLocation()
  const linkClass = (path: string) => {
    const active = location.pathname === path
    return `px-3 py-1.5 rounded-md text-sm font-mono uppercase tracking-wider transition-colors ${
      active ? 'bg-panel text-gray-100' : 'text-gray-400 hover:text-gray-200'
    }`
  }

  return (
    <header className="border-b border-border bg-ink/95 backdrop-blur sticky top-0 z-10">
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-critical animate-pulse" />
          <h1 className="text-base font-semibold tracking-wide">
            SOC <span className="text-gray-500 font-normal">— Converged IoT/AI Security</span>
          </h1>
        </div>
        <nav className="flex items-center gap-1">
          <Link to="/" className={linkClass('/')}>Dashboard</Link>
          <Link to="/alerts" className={linkClass('/alerts')}>Alerts</Link>
          <Link to="/users" className={linkClass('/users')}>Users</Link>
        </nav>
      </div>
    </header>
  )
}