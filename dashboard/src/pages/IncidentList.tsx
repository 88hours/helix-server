/**
 * Incident list page — shows all known incidents, newest first.
 *
 * Polls /api/incidents every 10 seconds so new incidents appear
 * without a manual refresh.
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchIncidents, IncidentSummary } from '../api'
import { StatusBadge } from '../components/StatusBadge'
import { SeverityBadge } from '../components/SeverityBadge'

function formatTimestamp(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export function IncidentList() {
  const [incidents, setIncidents] = useState<IncidentSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    try {
      const data = await fetchIncidents()
      setIncidents(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load incidents')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, 10_000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div>
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Incidents</h1>
          <p className="mt-1 text-sm text-gray-500">
            All incidents processed by Helix — newest first
          </p>
        </div>
        <button
          onClick={load}
          className="text-sm text-gray-500 hover:text-gray-700 flex items-center gap-1.5"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
          </svg>
          Refresh
        </button>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="text-center py-16 text-gray-400">Loading incidents…</div>
      )}

      {/* Error state */}
      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && incidents.length === 0 && (
        <div className="text-center py-16">
          <p className="text-gray-400 text-sm">No incidents yet.</p>
          <p className="text-gray-400 text-xs mt-1">
            Send a Sentry or Rollbar webhook to <span className="font-mono">/webhook/sentry</span> to trigger the pipeline.
          </p>
        </div>
      )}

      {/* Table */}
      {incidents.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="min-w-full divide-y divide-gray-100">
            <thead>
              <tr className="bg-gray-50">
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Incident
                </th>
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Error
                </th>
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Severity
                </th>
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Status
                </th>
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Time
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {incidents.map((inc) => (
                <tr key={inc.incident_id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-5 py-4">
                    <Link
                      to={`/incidents/${inc.incident_id}`}
                      className="font-mono text-xs text-blue-600 hover:text-blue-800 hover:underline"
                    >
                      {inc.incident_id.slice(0, 8)}…
                    </Link>
                    {inc.affected_component && (
                      <p className="text-xs text-gray-500 mt-0.5">{inc.affected_component}</p>
                    )}
                  </td>
                  <td className="px-5 py-4 max-w-xs">
                    <p className="text-sm font-medium text-gray-800 truncate">
                      {inc.error_type ?? '—'}
                    </p>
                    <p className="text-xs text-gray-500 truncate mt-0.5">
                      {inc.error_message ?? ''}
                    </p>
                  </td>
                  <td className="px-5 py-4">
                    <SeverityBadge severity={inc.severity} />
                  </td>
                  <td className="px-5 py-4">
                    <StatusBadge status={inc.status} />
                  </td>
                  <td className="px-5 py-4 text-xs text-gray-500 whitespace-nowrap">
                    {formatTimestamp(inc.timestamp)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
