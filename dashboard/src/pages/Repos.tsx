/**
 * Repo configuration page.
 *
 * Lets users add and remove GitHub repositories that Helix will monitor,
 * comment on (GitHub Issues), and open PRs against when it fixes a crash.
 *
 * Each repo has:
 *   - repo       "owner/name" — the GitHub repository
 *   - base_branch  branch PRs are opened against (default: main)
 *   - language   primary language used to choose the test framework
 */

import { useEffect, useState } from 'react'
import { RepoConfig, addRepo, fetchRepos, removeRepo } from '../api'

const LANGUAGES = ['python', 'javascript', 'typescript', 'ruby', 'java', 'kotlin', 'go']

function EmptyState() {
  return (
    <div className="text-center py-16 border-2 border-dashed border-gray-200 rounded-xl">
      <svg className="mx-auto w-10 h-10 text-gray-300 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M14.25 9.75 16.5 12l-2.25 2.25m-4.5 0L7.5 12l2.25-2.25M6 20.25h12A2.25 2.25 0 0 0 20.25 18V6A2.25 2.25 0 0 0 18 3.75H6A2.25 2.25 0 0 0 3.75 6v12A2.25 2.25 0 0 0 6 20.25Z" />
      </svg>
      <p className="text-sm text-gray-500">No repos configured yet.</p>
      <p className="text-xs text-gray-400 mt-1">Add a repo below to let Helix start watching it.</p>
    </div>
  )
}

interface RepoRowProps {
  repo: RepoConfig
  onRemove: (repo: string) => void
  removing: boolean
}

function RepoRow({ repo, onRemove, removing }: RepoRowProps) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-gray-400 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 2C6.477 2 2 6.477 2 12c0 4.418 2.865 8.166 6.839 9.489.5.092.682-.217.682-.482 0-.237-.009-.868-.013-1.703-2.782.603-3.369-1.342-3.369-1.342-.454-1.154-1.11-1.461-1.11-1.461-.908-.62.069-.608.069-.608 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.269 2.75 1.025A9.578 9.578 0 0 1 12 6.836a9.59 9.59 0 0 1 2.504.337c1.909-1.294 2.747-1.025 2.747-1.025.546 1.377.202 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.743 0 .267.18.578.688.48C19.138 20.163 22 16.418 22 12c0-5.523-4.477-10-10-10Z" />
          </svg>
          <span className="text-sm font-medium text-gray-900 font-mono">{repo.repo}</span>
        </div>
        <div className="flex items-center gap-3 mt-1 ml-6">
          <span className="text-xs text-gray-400">branch: <span className="font-mono text-gray-600">{repo.base_branch}</span></span>
          <span className="text-xs text-gray-400">language: <span className="text-gray-600">{repo.language}</span></span>
        </div>
      </div>
      <button
        onClick={() => onRemove(repo.repo)}
        disabled={removing}
        className="flex-shrink-0 text-xs text-red-500 hover:text-red-700 disabled:opacity-40 transition-colors"
      >
        Remove
      </button>
    </div>
  )
}

export function Repos() {
  const [repos, setRepos] = useState<RepoConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Add form state
  const [repoInput, setRepoInput] = useState('')
  const [branchInput, setBranchInput] = useState('main')
  const [languageInput, setLanguageInput] = useState('python')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)

  const [removingRepo, setRemovingRepo] = useState<string | null>(null)

  useEffect(() => {
    fetchRepos()
      .then(setRepos)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = repoInput.trim()
    if (!trimmed) return

    setAdding(true)
    setAddError(null)
    try {
      const added = await addRepo(trimmed, branchInput || 'main', languageInput || 'python')
      setRepos((prev) => [...prev, added])
      setRepoInput('')
    } catch (e) {
      setAddError(String(e))
    } finally {
      setAdding(false)
    }
  }

  async function handleRemove(repo: string) {
    setRemovingRepo(repo)
    try {
      await removeRepo(repo)
      setRepos((prev) => prev.filter((r) => r.repo !== repo))
    } catch {
      // silently ignore — row stays visible
    } finally {
      setRemovingRepo(null)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Repositories</h1>
        <p className="mt-1 text-sm text-gray-500">
          Helix watches these repos — when a crash arrives, it creates a GitHub Issue, writes a failing test, and opens a PR with a fix.
        </p>
      </div>

      {/* Repo list */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 bg-gray-50">
          <h2 className="text-sm font-semibold text-gray-700">Configured repos</h2>
        </div>

        {loading ? (
          <div className="px-5 py-8 text-sm text-gray-400 text-center">Loading…</div>
        ) : error ? (
          <div className="px-5 py-8 text-sm text-red-500 text-center">{error}</div>
        ) : repos.length === 0 ? (
          <div className="px-5 py-8">
            <EmptyState />
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {repos.map((r) => (
              <RepoRow
                key={r.repo}
                repo={r}
                onRemove={handleRemove}
                removing={removingRepo === r.repo}
              />
            ))}
          </div>
        )}
      </div>

      {/* Add repo form */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 bg-gray-50">
          <h2 className="text-sm font-semibold text-gray-700">Add a repo</h2>
        </div>
        <form onSubmit={handleAdd} className="px-5 py-5 space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="sm:col-span-1">
              <label className="block text-xs font-medium text-gray-500 mb-1">Repository <span className="text-red-400">*</span></label>
              <input
                type="text"
                value={repoInput}
                onChange={(e) => setRepoInput(e.target.value)}
                placeholder="owner/name"
                required
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 font-mono placeholder:text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Base branch</label>
              <input
                type="text"
                value={branchInput}
                onChange={(e) => setBranchInput(e.target.value)}
                placeholder="main"
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 font-mono placeholder:text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Language</label>
              <select
                value={languageInput}
                onChange={(e) => setLanguageInput(e.target.value)}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                {LANGUAGES.map((l) => (
                  <option key={l} value={l}>{l}</option>
                ))}
              </select>
            </div>
          </div>

          {addError && (
            <p className="text-xs text-red-500">{addError}</p>
          )}

          <button
            type="submit"
            disabled={adding || !repoInput.trim()}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-700 disabled:opacity-40 transition-colors"
          >
            {adding ? 'Adding…' : 'Add repo'}
          </button>
        </form>
      </div>
    </div>
  )
}
