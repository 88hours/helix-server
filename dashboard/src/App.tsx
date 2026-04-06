/**
 * Root application component.
 *
 * Sets up React Router with two routes:
 *   /app/           → IncidentList
 *   /app/incidents/:incidentId → IncidentDetail
 *
 * The shell layout includes a top nav bar that links back to the landing page.
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { IncidentList } from './pages/IncidentList'
import { IncidentDetail } from './pages/IncidentDetail'

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Nav bar */}
      <nav className="bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between h-14">
          <div className="flex items-center gap-3">
            {/* Helix wordmark */}
            <span className="text-lg font-bold tracking-tight text-gray-900">helix</span>
            <span className="text-gray-300">|</span>
            <span className="text-sm text-gray-500">Dashboard</span>
          </div>
          <a
            href="/"
            className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
          >
            ← Docs
          </a>
        </div>
      </nav>

      {/* Page content */}
      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter basename="/app">
      <Shell>
        <Routes>
          <Route path="/" element={<IncidentList />} />
          <Route path="/incidents/:incidentId" element={<IncidentDetail />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  )
}
