import { Route, Routes } from 'react-router-dom'
import { Header } from './components/Header'
import AlertsPage from './pages/AlertsPage'
import Dashboard from './pages/Dashboard'
import UserDetail from './pages/UserDetail'

export default function App() {
  return (
    <div className="min-h-screen bg-ink text-gray-100">
      <Header />
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/users" element={<UserDetail />} />
          <Route
            path="*"
            element={
              <div className="max-w-7xl mx-auto px-4 py-12 text-center text-gray-500 font-mono">
                Page not found.
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  )
}