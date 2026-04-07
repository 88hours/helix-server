/**
 * Projects page.
 *
 * A project is a GitHub repository plus the per-project credentials Helix
 * needs to run the pipeline against it (API keys, tokens, notification config).
 *
 * The page has two panels:
 *   - Left / top: project list with a "New project" form
 *   - Right / inline: settings panel that expands when the user clicks a project
 *
 * Secret values are returned from the API as '***' when already set.
 * The form shows a placeholder "Already set" for those fields and only sends
 * a new value when the user actually types something.  Sending '***' back
 * instructs the API to leave the existing value unchanged.
 */

import { useEffect, useRef, useState } from 'react'
import { Project, ProjectSettings, createProject, deleteProject, fetchProjects, updateProjectSettings } from '../api'

const LANGUAGES = ['python', 'javascript', 'typescript', 'ruby', 'java', 'kotlin', 'go']

const MASK = '***'

// ---------------------------------------------------------------------------
// Settings field definitions
// ---------------------------------------------------------------------------

interface FieldDef {
  key: keyof ProjectSettings
  label: string
  placeholder: string
  secret: boolean
  required: boolean
  group: 'core' | 'slack' | 'email'
}

const FIELDS: FieldDef[] = [
  // Core — required
  { key: 'anthropic_api_key',      label: 'Anthropic API key',          placeholder: 'sk-ant-…',        secret: true,  required: true,  group: 'core' },
  { key: 'github_token',           label: 'GitHub token',               placeholder: 'ghp_…',           secret: true,  required: true,  group: 'core' },
  { key: 'redis_url',              label: 'Redis URL',                  placeholder: 'redis://…',       secret: true,  required: true,  group: 'core' },
  { key: 'sentry_webhook_secret',  label: 'Sentry webhook secret',      placeholder: 'HMAC secret',     secret: true,  required: false, group: 'core' },
  { key: 'rollbar_access_token',   label: 'Rollbar access token',       placeholder: 'project token',   secret: true,  required: false, group: 'core' },
  // Slack — optional
  { key: 'slack_bot_token',        label: 'Slack bot token',            placeholder: 'xoxb-…',          secret: true,  required: false, group: 'slack' },
  { key: 'slack_signing_secret',   label: 'Slack signing secret',       placeholder: 'signing secret',  secret: true,  required: false, group: 'slack' },
  { key: 'slack_approval_channel', label: 'Slack approval channel',     placeholder: '#helix-approvals', secret: false, required: false, group: 'slack' },
  // Email — optional
  { key: 'sendgrid_api_key',       label: 'SendGrid API key',           placeholder: 'SG.…',            secret: true,  required: false, group: 'email' },
  { key: 'smtp_host',              label: 'SMTP host',                  placeholder: 'smtp.example.com', secret: false, required: false, group: 'email' },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Count how many settings fields are configured (non-null, non-empty after
 * the API masks them as '***').  Non-secret fields are checked directly.
 */
function countConfigured(settings: ProjectSettings): number {
  return FIELDS.filter(({ key, secret }) => {
    const v = settings[key]
    if (!v) return false
    return secret ? v === MASK : v.length > 0
  }).length
}

function settingsComplete(settings: ProjectSettings): boolean {
  const requiredKeys: (keyof ProjectSettings)[] = ['anthropic_api_key', 'github_token', 'redis_url']
  const hasSentryOrRollbar =
    (settings.sentry_webhook_secret && settings.sentry_webhook_secret !== '') ||
    (settings.rollbar_access_token && settings.rollbar_access_token !== '')
  return requiredKeys.every((k) => Boolean(settings[k])) && Boolean(hasSentryOrRollbar)
}

// ---------------------------------------------------------------------------
// New-project form
// ---------------------------------------------------------------------------

interface NewProjectFormProps {
  onCreate: (project: Project) => void
}

function NewProjectForm({ onCreate }: NewProjectFormProps) {
  const [open, setOpen] = useState(false)
  const [repoInput, setRepoInput] = useState('')
  const [branchInput, setBranchInput] = useState('main')
  const [languageInput, setLanguageInput] = useState('python')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const project = await createProject(repoInput.trim(), branchInput || 'main', languageInput || 'python')
      onCreate(project)
      setRepoInput('')
      setBranchInput('main')
      setLanguageInput('python')
      setOpen(false)
    } catch (err) {
      setError(String(err))
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
        </svg>
        New project
      </button>
    )
  }

  return (
    <div className="bg-white border border-indigo-200 rounded-xl overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100 bg-indigo-50 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-indigo-900">New project</h3>
        <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      <form onSubmit={handleSubmit} className="px-5 py-5 space-y-4">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">
            Repository URL or slug <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={repoInput}
            onChange={(e) => setRepoInput(e.target.value)}
            placeholder="https://github.com/owner/repo  or  owner/repo"
            required
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 font-mono placeholder:text-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Base branch</label>
            <input
              type="text"
              value={branchInput}
              onChange={(e) => setBranchInput(e.target.value)}
              placeholder="main"
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 font-mono placeholder:text-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Language</label>
            <select
              value={languageInput}
              onChange={(e) => setLanguageInput(e.target.value)}
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            >
              {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
        </div>
        {error && <p className="text-xs text-red-500">{error}</p>}
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={saving || !repoInput.trim()}
            className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 rounded-lg transition-colors"
          >
            {saving ? 'Creating…' : 'Create project'}
          </button>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700 transition-colors"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Settings form
// ---------------------------------------------------------------------------

interface SettingsGroup {
  title: string
  description: string
  fields: FieldDef[]
}

const GROUPS: SettingsGroup[] = [
  {
    title: 'Core credentials',
    description: 'Required for the agent pipeline to run. Provide at least one of Sentry or Rollbar.',
    fields: FIELDS.filter((f) => f.group === 'core'),
  },
  {
    title: 'Slack notifications',
    description: 'Optional. Helix posts PR approval messages and escalation alerts to Slack.',
    fields: FIELDS.filter((f) => f.group === 'slack'),
  },
  {
    title: 'Email notifications',
    description: 'Optional. Use SendGrid or a plain SMTP server.',
    fields: FIELDS.filter((f) => f.group === 'email'),
  },
]

interface SettingsFormProps {
  project: Project
  onSave: (updated: Project) => void
  onClose: () => void
}

function SettingsForm({ project, onSave, onClose }: SettingsFormProps) {
  // Local form state — each field starts empty (user must type to change a secret)
  const initial: Record<string, string> = {}
  FIELDS.forEach(({ key }) => {
    const v = project.settings[key]
    // Non-secret fields (channel, smtp_host) start pre-filled; secrets start empty
    initial[key] = v && v !== MASK ? v : ''
  })
  const [values, setValues] = useState<Record<string, string>>(initial)
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  function set(key: string, value: string) {
    setValues((prev) => ({ ...prev, [key]: value }))
    setSaved(false)
  }

  function toggleShow(key: string) {
    setShowSecrets((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      // Build patch: empty string → null (clear); non-empty secret → new value.
      // If a secret field is still empty and was previously set (MASK), send MASK
      // so the backend leaves it alone.
      const patch: Partial<ProjectSettings> = {}
      FIELDS.forEach(({ key, secret }) => {
        const typed = values[key]
        const wasSet = project.settings[key] === MASK
        if (typed) {
          // User typed something — update
          (patch as Record<string, string | null>)[key] = typed
        } else if (secret && wasSet) {
          // Secret was already set, user didn't change it — keep
          (patch as Record<string, string | null>)[key] = MASK
        } else {
          // Empty and not previously set — clear / leave null
          (patch as Record<string, string | null>)[key] = null
        }
      })
      const updated = await updateProjectSettings(project.repo, patch)
      onSave(updated)
      setSaved(true)
    } catch (err) {
      setError(String(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSave} className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">Settings</h3>
          <p className="text-xs text-gray-400 font-mono mt-0.5">{project.repo}</p>
        </div>
        <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="divide-y divide-gray-100">
        {GROUPS.map((group) => (
          <div key={group.title} className="px-5 py-5 space-y-4">
            <div>
              <h4 className="text-xs font-semibold text-gray-700 uppercase tracking-wide">{group.title}</h4>
              <p className="text-xs text-gray-400 mt-0.5">{group.description}</p>
            </div>
            <div className="space-y-3">
              {group.fields.map(({ key, label, placeholder, secret, required }) => {
                const wasSet = project.settings[key] === MASK
                const isShown = showSecrets[key]
                return (
                  <div key={key}>
                    <label className="block text-xs font-medium text-gray-500 mb-1">
                      {label}
                      {required && <span className="text-red-400 ml-1">*</span>}
                    </label>
                    <div className="relative">
                      <input
                        type={secret && !isShown ? 'password' : 'text'}
                        value={values[key]}
                        onChange={(e) => set(key, e.target.value)}
                        placeholder={wasSet ? 'Already set — type to replace' : placeholder}
                        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 font-mono placeholder:text-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent pr-10"
                      />
                      {secret && (
                        <button
                          type="button"
                          tabIndex={-1}
                          onClick={() => toggleShow(key)}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500"
                        >
                          {isShown ? (
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88" />
                            </svg>
                          ) : (
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z" />
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                            </svg>
                          )}
                        </button>
                      )}
                    </div>
                    {wasSet && !values[key] && (
                      <p className="text-xs text-emerald-600 mt-1 flex items-center gap-1">
                        <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clipRule="evenodd" />
                        </svg>
                        Set
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="px-5 py-4 border-t border-gray-100 bg-gray-50 flex items-center gap-3">
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 rounded-lg transition-colors"
        >
          {saving ? 'Saving…' : 'Save settings'}
        </button>
        {saved && (
          <span className="text-xs text-emerald-600 flex items-center gap-1">
            <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clipRule="evenodd" />
            </svg>
            Settings saved
          </span>
        )}
        {error && <p className="text-xs text-red-500">{error}</p>}
      </div>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Project card
// ---------------------------------------------------------------------------

interface ProjectCardProps {
  project: Project
  active: boolean
  onSelect: () => void
  onDelete: () => void
  deleting: boolean
}

function ProjectCard({ project, active, onSelect, onDelete, deleting }: ProjectCardProps) {
  const configured = countConfigured(project.settings)
  const complete = settingsComplete(project.settings)

  return (
    <div
      className={`bg-white border rounded-xl px-5 py-4 transition-all cursor-pointer ${
        active ? 'border-indigo-300 ring-2 ring-indigo-100' : 'border-gray-200 hover:border-gray-300'
      }`}
      onClick={onSelect}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4 text-gray-400 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 2C6.477 2 2 6.477 2 12c0 4.418 2.865 8.166 6.839 9.489.5.092.682-.217.682-.482 0-.237-.009-.868-.013-1.703-2.782.603-3.369-1.342-3.369-1.342-.454-1.154-1.11-1.461-1.11-1.461-.908-.62.069-.608.069-.608 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.269 2.75 1.025A9.578 9.578 0 0 1 12 6.836a9.59 9.59 0 0 1 2.504.337c1.909-1.294 2.747-1.025 2.747-1.025.546 1.377.202 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.743 0 .267.18.578.688.48C19.138 20.163 22 16.418 22 12c0-5.523-4.477-10-10-10Z" />
            </svg>
            <span className="text-sm font-medium text-gray-900 font-mono">{project.repo}</span>
          </div>
          <div className="flex items-center gap-3 mt-1 ml-6">
            <span className="text-xs text-gray-400">
              branch: <span className="font-mono text-gray-600">{project.base_branch}</span>
            </span>
            <span className="text-xs text-gray-400">
              lang: <span className="text-gray-600">{project.language}</span>
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          {complete ? (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full">
              <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clipRule="evenodd" />
              </svg>
              Ready
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full">
              {configured}/{FIELDS.length} set
            </span>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); onDelete() }}
            disabled={deleting}
            className="text-xs text-red-400 hover:text-red-600 disabled:opacity-40 transition-colors"
          >
            {deleting ? '…' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="text-center py-16 border-2 border-dashed border-gray-200 rounded-xl">
      <svg className="mx-auto w-10 h-10 text-gray-300 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M14.25 9.75 16.5 12l-2.25 2.25m-4.5 0L7.5 12l2.25-2.25M6 20.25h12A2.25 2.25 0 0 0 20.25 18V6A2.25 2.25 0 0 0 18 3.75H6A2.25 2.25 0 0 0 3.75 6v12A2.25 2.25 0 0 0 6 20.25Z" />
      </svg>
      <p className="text-sm text-gray-500 font-medium">No projects yet</p>
      <p className="text-xs text-gray-400 mt-1">Create a project to connect a GitHub repo and configure your credentials.</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function Projects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeRepo, setActiveRepo] = useState<string | null>(null)
  const [deletingRepo, setDeletingRepo] = useState<string | null>(null)
  const settingsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchProjects()
      .then(setProjects)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  // Scroll the settings panel into view when it opens
  useEffect(() => {
    if (activeRepo && settingsRef.current) {
      settingsRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [activeRepo])

  function handleCreated(project: Project) {
    setProjects((prev) => [...prev, project])
    setActiveRepo(project.repo)
  }

  function handleSettingsSaved(updated: Project) {
    setProjects((prev) => prev.map((p) => (p.repo === updated.repo ? updated : p)))
  }

  async function handleDelete(repo: string) {
    setDeletingRepo(repo)
    try {
      await deleteProject(repo)
      setProjects((prev) => prev.filter((p) => p.repo !== repo))
      if (activeRepo === repo) setActiveRepo(null)
    } catch {
      // silently ignore — card stays visible
    } finally {
      setDeletingRepo(null)
    }
  }

  const activeProject = projects.find((p) => p.repo === activeRepo) ?? null

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Projects</h1>
          <p className="mt-1 text-sm text-gray-500">
            Each project connects a GitHub repo to Helix. Configure credentials so the agents can clone the repo, open issues, and create PRs.
          </p>
        </div>
        <div className="flex-shrink-0">
          <NewProjectForm onCreate={handleCreated} />
        </div>
      </div>

      {/* Project list */}
      {loading ? (
        <div className="py-12 text-sm text-gray-400 text-center">Loading…</div>
      ) : error ? (
        <div className="py-12 text-sm text-red-500 text-center">{error}</div>
      ) : projects.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-3">
          {projects.map((project) => (
            <ProjectCard
              key={project.repo}
              project={project}
              active={activeRepo === project.repo}
              onSelect={() => setActiveRepo(activeRepo === project.repo ? null : project.repo)}
              onDelete={() => handleDelete(project.repo)}
              deleting={deletingRepo === project.repo}
            />
          ))}
        </div>
      )}

      {/* Settings panel — shown below the list when a project is selected */}
      {activeProject && (
        <div ref={settingsRef}>
          <SettingsForm
            key={activeProject.repo}
            project={activeProject}
            onSave={handleSettingsSaved}
            onClose={() => setActiveRepo(null)}
          />
        </div>
      )}
    </div>
  )
}
