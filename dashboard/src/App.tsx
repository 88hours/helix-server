/**
 * Root application component.
 *
 * Routes:
 *   /app/incidents              → IncidentList
 *   /app/incidents/:incidentId  → IncidentDetail
 *   /app/projects               → Projects (project + repo configuration)
 *
 * When VITE_AUTH0_DOMAIN is set, renders TokenProviderBridge (registers the
 * Auth0 token-getter with the API client) and NavUserChip (avatar + sign-out).
 * All routes are wrapped in AuthGuard which redirects unauthenticated users.
 *
 * When VITE_AUTH0_DOMAIN is not set (demo mode), no auth components are
 * mounted and all routes are accessible without login.
 */

import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthGuard } from './components/AuthGuard'
import { NavUserChip } from './components/NavUserChip'
import { TokenProviderBridge } from './components/TokenProviderBridge'
import { IncidentDetail } from './pages/IncidentDetail'
import { IncidentList } from './pages/IncidentList'
import Projects from './pages/Projects'

const authEnabled = Boolean(import.meta.env.VITE_AUTH0_DOMAIN)

// ---------------------------------------------------------------------------
// Nav link — highlights the active section
// ---------------------------------------------------------------------------

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  const location = useLocation()
  const active = location.pathname.startsWith(to)
  return (
    <Link
      to={to}
      className={`text-sm transition-colors ${active ? 'text-gray-900 font-medium' : 'text-gray-400 hover:text-gray-600'}`}
    >
      {children}
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Shell layout
// ---------------------------------------------------------------------------

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between h-14">
          <div className="flex items-center gap-4">
            <span className="text-lg font-bold tracking-tight text-gray-900">helix</span>
            <span className="text-gray-200">|</span>
            <NavLink to="/incidents">Incidents</NavLink>
            <NavLink to="/projects">Projects</NavLink>
          </div>
          {authEnabled && <NavUserChip />}
        </div>
      </nav>
      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  return (
    <BrowserRouter basename="/app">
      {/* Register Auth0 token-getter with the API client when auth is active. */}
      {authEnabled && <TokenProviderBridge />}

      <AuthGuard>
        <Shell>
          <Routes>
            <Route path="/" element={<Navigate to="/incidents" replace />} />
            <Route path="/incidents" element={<IncidentList />} />
            <Route path="/incidents/:incidentId" element={<IncidentDetail />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="*" element={<Navigate to="/incidents" replace />} />
          </Routes>
        </Shell>
      </AuthGuard>
    </BrowserRouter>
  )
}
