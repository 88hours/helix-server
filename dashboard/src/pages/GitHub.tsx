/**
 * GitHub page — manage the GitHub App connection and repository access.
 *
 * Shows all repos the GitHub App installation can access, with:
 *   - Private / Public badge
 *   - Default branch
 *   - Which Helix project (if any) is monitoring that repo
 *
 * Also handles the post-installation redirect from GitHub — if
 * ?installation_id=... is in the URL it registers the installation and
 * clears the param before rendering.
 */

import { useEffect, useState } from 'react'
import {
  fetchGitHubInstallUrl,
  fetchGitHubRepos,
  fetchProjects,
  registerGitHubInstallation,
  type GitHubInstallation,
  type Project,
} from '../api'

export default function GitHub() {
  const [installation, setInstallation] = useState<GitHubInstallation | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [installUrl, setInstallUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [manualId, setManualId] = useState('')
  const [registering, setRegistering] = useState(false)
  const [registerError, setRegisterError] = useState<string | null>(null)

  const loadAll = async () => {
    const [instResult, projResult] = await Promise.allSettled([
      fetchGitHubRepos(),
      fetchProjects(),
    ])
    if (instResult.status === 'fulfilled') {
      setInstallation(instResult.value)
      setError(null)
    } else {
      const msg = (instResult.reason as Error).message
      if (msg === 'GitHub App not installed' || msg.includes('404')) {
        setInstallation(null)
      } else {
        setError(msg)
      }
    }
    if (projResult.status === 'fulfilled') {
      setProjects(projResult.value)
    }
  }

  useEffect(() => {
    fetchGitHubInstallUrl().then(setInstallUrl).catch(() => {})

    const params = new URLSearchParams(window.location.search)
    const iid = params.get('installation_id')

    const init = async () => {
      if (iid) {
        window.history.replaceState({}, '', window.location.pathname)
        try {
          await registerGitHubInstallation(iid)
        } catch {
          // already registered — safe to ignore
        }
      }
      await loadAll()
      setLoading(false)
    }
    init()
  }, [])

  const handleRefresh = async () => {
    setRefreshing(true)
    await loadAll()
    setRefreshing(false)
  }

  const handleManualRegister = async () => {
    if (!manualId.trim()) return
    setRegistering(true)
    setRegisterError(null)
    try {
      await registerGitHubInstallation(manualId.trim())
      setManualId('')
      await loadAll()
    } catch (err) {
      setRegisterError((err as Error).message)
    } finally {
      setRegistering(false)
    }
  }

  // Map repo full_name → projects monitoring it
  const repoProjectMap = new Map<string, Project[]>()
  for (const p of projects) {
    const list = repoProjectMap.get(p.repo) ?? []
    repoProjectMap.set(p.repo, [...list, p])
  }

  return (
    <div className="max-w-3xl mx-auto py-8 px-4">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">GitHub</h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage the GitHub App connection and repository access.
          </p>
        </div>
        {installation && (
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="text-sm text-gray-500 hover:text-gray-700 flex items-center gap-1.5 disabled:opacity-40"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        )}
      </div>

      {loading ? (
        <div className="text-sm text-gray-400 py-8 text-center">Loading…</div>
      ) : error ? (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
      ) : !installation ? (
        // ── Not connected ──────────────────────────────────────────────────
        <div className="space-y-6">
          <div className="rounded-xl border border-gray-200 bg-white p-6 space-y-4">
            <div className="flex items-center gap-3">
              <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-yellow-100 text-yellow-600 text-sm">!</span>
              <div>
                <p className="font-medium text-gray-900 text-sm">GitHub App not installed</p>
                <p className="text-xs text-gray-500 mt-0.5">Install the Helix GitHub App to allow Helix to clone repos and open pull requests.</p>
              </div>
            </div>
            <a
              href={installUrl ?? '#'}
              className="inline-flex items-center gap-2 px-4 py-2 bg-gray-900 hover:bg-gray-700 text-white text-sm rounded-lg font-medium"
            >
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
              </svg>
              Install GitHub App
            </a>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-6 space-y-3">
            <p className="text-sm font-medium text-gray-700">Already installed?</p>
            <p className="text-xs text-gray-500">
              Go to{' '}
              <a href="https://github.com/settings/installations" target="_blank" rel="noreferrer" className="text-blue-600 underline">
                github.com/settings/installations
              </a>
              {' '}→ click Configure → copy the numeric ID from the URL.
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                value={manualId}
                onChange={e => setManualId(e.target.value)}
                placeholder="Installation ID (e.g. 12345678)"
                className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
              />
              <button
                onClick={handleManualRegister}
                disabled={!manualId.trim() || registering}
                className="px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-sm rounded-lg font-medium"
              >
                {registering ? '…' : 'Connect'}
              </button>
            </div>
            {registerError && <p className="text-xs text-red-500">{registerError}</p>}
          </div>
        </div>
      ) : (
        // ── Connected ──────────────────────────────────────────────────────
        <div className="space-y-4">
          <div className="flex items-center justify-between rounded-xl border border-green-200 bg-green-50 px-4 py-3">
            <div className="flex items-center gap-2 text-sm text-green-800">
              <span className="text-green-500">✓</span>
              <span>GitHub App connected</span>
              <span className="text-green-600 text-xs font-mono">#{installation.installation_id}</span>
            </div>
            <a
              href="https://github.com/settings/installations"
              target="_blank"
              rel="noreferrer"
              className="text-xs text-green-700 hover:text-green-900 underline"
            >
              Manage on GitHub ↗
            </a>
          </div>

          {installation.repos.length === 0 ? (
            <div className="rounded-xl border border-gray-200 bg-white px-5 py-8 text-center text-sm text-gray-500">
              No repositories accessible.{' '}
              <a href="https://github.com/settings/installations" target="_blank" rel="noreferrer" className="text-blue-600 underline">
                Grant access to repos on GitHub
              </a>
              {' '}then click Refresh.
            </div>
          ) : (
            <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
              <table className="min-w-full divide-y divide-gray-100">
                <thead>
                  <tr className="bg-gray-50">
                    <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Repository</th>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Visibility</th>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Default branch</th>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Helix project</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {installation.repos.map(repo => {
                    const linked = repoProjectMap.get(repo.full_name) ?? []
                    return (
                      <tr key={repo.full_name} className="hover:bg-gray-50">
                        <td className="px-5 py-3">
                          <a
                            href={`https://github.com/${repo.full_name}`}
                            target="_blank"
                            rel="noreferrer"
                            className="text-sm font-medium text-blue-600 hover:underline"
                          >
                            {repo.full_name}
                          </a>
                          {repo.description && (
                            <p className="text-xs text-gray-400 mt-0.5 truncate max-w-xs">{repo.description}</p>
                          )}
                        </td>
                        <td className="px-5 py-3">
                          <span className={`inline-flex items-center text-xs px-2 py-0.5 rounded-full font-medium ${
                            repo.private
                              ? 'bg-gray-100 text-gray-600'
                              : 'bg-blue-50 text-blue-600'
                          }`}>
                            {repo.private ? '🔒 Private' : '🌐 Public'}
                          </span>
                        </td>
                        <td className="px-5 py-3">
                          <code className="text-xs bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded">
                            {repo.default_branch}
                          </code>
                        </td>
                        <td className="px-5 py-3">
                          {linked.length > 0 ? (
                            <div className="space-y-1">
                              {linked.map(p => (
                                <div key={p.project_id} className="flex items-center gap-1.5">
                                  <span className="text-xs text-green-600 font-medium">{p.name}</span>
                                  <code className="text-xs bg-gray-100 text-gray-500 px-1 py-0.5 rounded">
                                    {p.base_branch}
                                  </code>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <span className="text-xs text-gray-400">—</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
