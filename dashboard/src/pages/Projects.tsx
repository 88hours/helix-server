/**
 * Projects page — list projects and launch the onboarding wizard.
 *
 * The 5-step wizard keeps all state in React memory until the final step,
 * then creates the project with a single API call. Abandoned wizards create
 * no records in the database.
 *
 * Steps:
 *   1 — Identity: project name, base branch, language
 *   2 — GitHub: install GitHub App → pick repo from dropdown
 *   3 — Alert Source: Sentry / Rollbar / both + webhook secrets
 *   4 — Optional Settings: Anthropic key, Slack, email (skippable)
 *   5 — Review & Create: summary + single POST, then show webhook URLs
 */

import { useEffect, useState } from 'react'
import {
  createProject,
  deleteProject,
  fetchGitHubInstallUrl,
  fetchGitHubRepos,
  fetchProjects,
  fetchWebhookUrls,
  registerGitHubInstallation,
  updateProjectSettings,
  type CreateProjectPayload,
  type GitHubRepo,
  type Project,
  type ProjectSettings,
} from '../api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface WizardState {
  name: string
  base_branch: string
  language: string
  github_installation_id: string | null
  repo: string
  alert_sources: string[]
  sentry_webhook_secret: string
  rollbar_access_token: string
  anthropic_api_key: string
  slack_bot_token: string
  slack_signing_secret: string
  slack_approval_channel: string
  sendgrid_api_key: string
  smtp_host: string
  email_from: string
  email_to: string
}

const EMPTY_WIZARD: WizardState = {
  name: '',
  base_branch: 'main',
  language: 'python',
  github_installation_id: null,
  repo: '',
  alert_sources: ['sentry'],
  sentry_webhook_secret: '',
  rollbar_access_token: '',
  anthropic_api_key: '',
  slack_bot_token: '',
  slack_signing_secret: '',
  slack_approval_channel: '',
  sendgrid_api_key: '',
  smtp_host: '',
  email_from: '',
  email_to: '',
}

// ---------------------------------------------------------------------------
// Tiny UI primitives
// ---------------------------------------------------------------------------

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-sm font-medium text-gray-300 mb-1">{children}</label>
}

function TextInput({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-400"
    />
  )
}

function SecretInput({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  const [show, setShow] = useState(false)
  const isSet = value === '***'
  return (
    <div className="relative">
      <input
        type={show ? 'text' : 'password'}
        value={isSet ? '' : value}
        onChange={e => onChange(e.target.value)}
        placeholder={isSet ? 'Already set — type to replace' : placeholder}
        className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 pr-14 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-400"
      />
      {isSet && (
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-green-400 pointer-events-none">
          ✓ set
        </span>
      )}
      <button
        type="button"
        onClick={() => setShow(s => !s)}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-200 text-xs"
      >
        {show ? 'hide' : 'show'}
      </button>
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      className="shrink-0 text-xs px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-gray-300"
    >
      {copied ? '✓' : 'Copy'}
    </button>
  )
}

function StepBar({ step, total }: { step: number; total: number }) {
  return (
    <div className="flex items-center gap-1.5 mb-6">
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          className={`h-1.5 flex-1 rounded-full transition-colors duration-200 ${
            i < step ? 'bg-indigo-500' : i === step ? 'bg-indigo-400' : 'bg-gray-700'
          }`}
        />
      ))}
      <span className="text-xs text-gray-500 shrink-0 ml-1">
        {step + 1} / {total}
      </span>
    </div>
  )
}

function NavButtons({
  onBack,
  onNext,
  nextLabel = 'Next',
  nextDisabled = false,
  backDisabled = false,
}: {
  onBack?: () => void
  onNext: () => void
  nextLabel?: string
  nextDisabled?: boolean
  backDisabled?: boolean
}) {
  return (
    <div className="flex justify-between pt-4">
      {onBack ? (
        <button
          onClick={onBack}
          disabled={backDisabled}
          className="px-4 py-2 text-gray-400 hover:text-white text-sm disabled:opacity-40"
        >
          Back
        </button>
      ) : <div />}
      <button
        onClick={onNext}
        disabled={nextDisabled}
        className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded-lg font-medium"
      >
        {nextLabel}
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 1 — Identity
// ---------------------------------------------------------------------------

function Step1({
  state,
  set,
  onNext,
}: {
  state: WizardState
  set: (k: keyof WizardState, v: string) => void
  onNext: () => void
}) {
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-white">Project identity</h3>

      <div>
        <Label>Project name</Label>
        <TextInput value={state.name} onChange={v => set('name', v)} placeholder="e.g. My Backend" />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label>Base branch</Label>
          <TextInput value={state.base_branch} onChange={v => set('base_branch', v)} placeholder="main" />
        </div>
        <div>
          <Label>Primary language</Label>
          <select
            value={state.language}
            onChange={e => set('language', e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-400"
          >
            {['python', 'javascript', 'typescript', 'ruby', 'java', 'kotlin', 'go'].map(l => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
        </div>
      </div>

      <NavButtons onNext={onNext} nextDisabled={!state.name.trim()} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 2 — GitHub App
// ---------------------------------------------------------------------------

function Step2({
  state,
  set,
  onNext,
  onBack,
}: {
  state: WizardState
  set: (k: keyof WizardState, v: string | null) => void
  onNext: () => void
  onBack: () => void
}) {
  const [installUrl, setInstallUrl] = useState<string | null>(null)
  const [repos, setRepos] = useState<GitHubRepo[]>([])
  const [checking, setChecking] = useState(true)
  const [notInstalled, setNotInstalled] = useState(false)
  const [repoError, setRepoError] = useState<string | null>(null)
  const [manualId, setManualId] = useState('')
  const [registering, setRegistering] = useState(false)
  const [registerError, setRegisterError] = useState<string | null>(null)

  const loadRepos = () => {
    return fetchGitHubRepos()
      .then(data => {
        if (!state.github_installation_id) set('github_installation_id', data.installation_id)
        setRepos(data.repos)
        if (data.repos.length === 1 && !state.repo) set('repo', data.repos[0].full_name)
        setNotInstalled(false)
      })
      .catch(err => {
        const msg = (err as Error).message
        if (msg === 'GitHub App not installed' || msg.includes('500')) {
          setNotInstalled(true)
        } else {
          setRepoError(msg)
        }
      })
  }

  useEffect(() => {
    fetchGitHubInstallUrl().then(setInstallUrl).catch(() => {})
    loadRepos().finally(() => setChecking(false))
  }, [])

  const handleManualRegister = async () => {
    if (!manualId.trim()) return
    setRegistering(true)
    setRegisterError(null)
    try {
      await registerGitHubInstallation(manualId.trim())
      set('github_installation_id', manualId.trim())
      setNotInstalled(false)
      setManualId('')
      await loadRepos()
    } catch (err) {
      setRegisterError((err as Error).message)
    } finally {
      setRegistering(false)
    }
  }

  const connected = !!state.github_installation_id && !notInstalled

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-white">Connect GitHub</h3>
      <p className="text-sm text-gray-400">
        Helix uses a GitHub App to clone repos and open pull requests — no personal access token needed.
      </p>

      {checking ? (
        <p className="text-sm text-gray-400">Checking GitHub connection…</p>
      ) : !connected ? (
        <div className="space-y-3">
          <a
            href={installUrl ?? '#'}
            className="inline-flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded-lg font-medium"
          >
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
            </svg>
            Install GitHub App
          </a>

          <div className="text-xs text-gray-500">
            Already installed?{' '}
            Go to{' '}
            <a href="https://github.com/settings/installations" target="_blank" rel="noreferrer" className="text-indigo-400 underline">
              github.com/settings/installations
            </a>
            , click Configure, and paste the ID from the URL below.
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={manualId}
              onChange={e => setManualId(e.target.value)}
              placeholder="Installation ID (from URL)"
              className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-400"
            />
            <button
              onClick={handleManualRegister}
              disabled={!manualId.trim() || registering}
              className="px-3 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-sm rounded-lg font-medium"
            >
              {registering ? '…' : 'Connect'}
            </button>
          </div>
          {registerError && <p className="text-xs text-red-400">{registerError}</p>}
        </div>
      ) : (
        <div className="flex items-center gap-2 text-sm text-green-400">
          <span>✓</span>
          <span>GitHub App connected</span>
          <a href={installUrl ?? '#'} className="text-gray-400 hover:text-gray-200 underline text-xs ml-2">
            Change installation
          </a>
        </div>
      )}

      {connected && (
        <div>
          <Label>Select repository</Label>
          {repoError && <p className="text-sm text-red-400">{repoError}</p>}
          {repos.length > 0 && (
            <select
              value={state.repo}
              onChange={e => set('repo', e.target.value)}
              className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-400"
            >
              <option value="">— choose a repository —</option>
              {repos.map(r => (
                <option key={r.full_name} value={r.full_name}>
                  {r.full_name}{r.private ? ' 🔒' : ''}
                </option>
              ))}
            </select>
          )}
          {repos.length === 0 && !repoError && (
            <p className="text-sm text-gray-400">
              No repositories found.{' '}
              <a href={installUrl ?? '#'} className="underline text-indigo-400">Configure the GitHub App</a>
              {' '}to grant access to repos.
            </p>
          )}
        </div>
      )}

      <NavButtons
        onBack={onBack}
        onNext={onNext}
        nextDisabled={checking || !connected || !state.repo}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 3 — Alert source
// ---------------------------------------------------------------------------

function Step3({
  state,
  set,
  onNext,
  onBack,
}: {
  state: WizardState
  set: (k: keyof WizardState, v: string | string[]) => void
  onNext: () => void
  onBack: () => void
}) {
  const toggle = (src: string) => {
    const cur = state.alert_sources
    set('alert_sources', cur.includes(src) ? cur.filter(s => s !== src) : [...cur, src])
  }

  const hasSentry = state.alert_sources.includes('sentry')
  const hasRollbar = state.alert_sources.includes('rollbar')

  const canProceed =
    state.alert_sources.length > 0 &&
    (!hasSentry || state.sentry_webhook_secret.trim()) &&
    (!hasRollbar || state.rollbar_access_token.trim())

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-white">Alert source</h3>
      <p className="text-sm text-gray-400">Choose which platforms should send crashes to Helix.</p>

      <div className="space-y-4">
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={hasSentry}
            onChange={() => toggle('sentry')}
            className="mt-0.5 h-4 w-4 rounded border-gray-600 text-indigo-500 bg-gray-700"
          />
          <div className="flex-1">
            <span className="text-sm font-medium text-white">Sentry</span>
            {hasSentry && (
              <div className="mt-2">
                <Label>Client Secret (from Sentry Developer Settings)</Label>
                <SecretInput
                  value={state.sentry_webhook_secret}
                  onChange={v => set('sentry_webhook_secret', v)}
                  placeholder="Sentry client secret"
                />
              </div>
            )}
          </div>
        </label>

        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={hasRollbar}
            onChange={() => toggle('rollbar')}
            className="mt-0.5 h-4 w-4 rounded border-gray-600 text-indigo-500 bg-gray-700"
          />
          <div className="flex-1">
            <span className="text-sm font-medium text-white">Rollbar</span>
            {hasRollbar && (
              <div className="mt-2">
                <Label>Project access token</Label>
                <SecretInput
                  value={state.rollbar_access_token}
                  onChange={v => set('rollbar_access_token', v)}
                  placeholder="Rollbar project access token"
                />
              </div>
            )}
          </div>
        </label>
      </div>

      <NavButtons onBack={onBack} onNext={onNext} nextDisabled={!canProceed} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 4 — Optional settings
// ---------------------------------------------------------------------------

function Accordion({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-white hover:bg-gray-700/40"
      >
        <span>{title}</span>
        <span className="text-gray-400 text-xs">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="px-4 pb-4 border-t border-gray-700 space-y-3 pt-3">{children}</div>}
    </div>
  )
}

function Step4({
  state,
  set,
  onNext,
  onBack,
}: {
  state: WizardState
  set: (k: keyof WizardState, v: string) => void
  onNext: () => void
  onBack: () => void
}) {
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-white">Optional settings</h3>
      <p className="text-sm text-gray-400">All of these can be added or changed later. Click Review to skip.</p>

      <div>
        <Label>Anthropic API key</Label>
        <SecretInput
          value={state.anthropic_api_key}
          onChange={v => set('anthropic_api_key', v)}
          placeholder="sk-ant-..."
        />
        <p className="text-xs text-gray-500 mt-1">
          Falls back to the global <code className="text-gray-400">ANTHROPIC_API_KEY</code> env var if not set here.
        </p>
      </div>

      <Accordion title="Slack notifications">
        <div>
          <Label>Bot token</Label>
          <SecretInput value={state.slack_bot_token} onChange={v => set('slack_bot_token', v)} placeholder="xoxb-..." />
        </div>
        <div>
          <Label>Signing secret</Label>
          <SecretInput value={state.slack_signing_secret} onChange={v => set('slack_signing_secret', v)} placeholder="Slack signing secret" />
        </div>
        <div>
          <Label>Approval channel</Label>
          <TextInput value={state.slack_approval_channel} onChange={v => set('slack_approval_channel', v)} placeholder="#helix-approvals" />
        </div>
      </Accordion>

      <Accordion title="Email notifications">
        <div>
          <Label>SendGrid API key</Label>
          <SecretInput value={state.sendgrid_api_key} onChange={v => set('sendgrid_api_key', v)} placeholder="SG...." />
        </div>
        <div>
          <Label>SMTP host (if no SendGrid)</Label>
          <TextInput value={state.smtp_host} onChange={v => set('smtp_host', v)} placeholder="smtp.example.com" />
        </div>
        <div>
          <Label>From address</Label>
          <TextInput value={state.email_from} onChange={v => set('email_from', v)} placeholder="helix@example.com" />
        </div>
        <div>
          <Label>To address</Label>
          <TextInput value={state.email_to} onChange={v => set('email_to', v)} placeholder="team@example.com" />
        </div>
      </Accordion>

      <NavButtons onBack={onBack} onNext={onNext} nextLabel="Review" />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 5 — Review & create
// ---------------------------------------------------------------------------

function Step5({
  state,
  onBack,
  onSubmit,
  creating,
  error,
  createdProject,
}: {
  state: WizardState
  onBack: () => void
  onSubmit: () => void
  creating: boolean
  error: string | null
  createdProject: Project | null
}) {
  // Success view — show webhook URLs
  if (createdProject?.webhook_urls) {
    const urls = createdProject.webhook_urls
    return (
      <div className="space-y-5">
        <div className="flex items-center gap-2">
          <span className="text-green-400 text-xl">✓</span>
          <h3 className="text-lg font-semibold text-white">Project created!</h3>
        </div>
        <p className="text-sm text-gray-400">
          Add the webhook URL(s) below to your alert platform. Helix will start processing crashes immediately.
        </p>

        {state.alert_sources.includes('sentry') && (
          <div>
            <Label>Sentry webhook URL</Label>
            <div className="flex items-center gap-2 mt-1">
              <code className="flex-1 min-w-0 text-xs bg-gray-800 border border-gray-600 rounded px-3 py-2 text-indigo-300 truncate">
                {urls.sentry}
              </code>
              <CopyButton text={urls.sentry} />
            </div>
            <p className="text-xs text-gray-500 mt-1">Sentry → Settings → Integrations → WebHooks → Internal Integration</p>
          </div>
        )}

        {state.alert_sources.includes('rollbar') && (
          <div>
            <Label>Rollbar webhook URL</Label>
            <div className="flex items-center gap-2 mt-1">
              <code className="flex-1 min-w-0 text-xs bg-gray-800 border border-gray-600 rounded px-3 py-2 text-indigo-300 truncate">
                {urls.rollbar}
              </code>
              <CopyButton text={urls.rollbar} />
            </div>
            <p className="text-xs text-gray-500 mt-1">Rollbar → Settings → Notifications → Webhook</p>
          </div>
        )}
      </div>
    )
  }

  // Review view
  const rows: [string, string][] = [
    ['Name', state.name],
    ['Repository', state.repo],
    ['Branch', state.base_branch],
    ['Language', state.language],
    ['Alert sources', state.alert_sources.join(', ')],
    ['Anthropic key', state.anthropic_api_key ? '••••••••' : '(env var fallback)'],
    ...(state.slack_approval_channel ? [['Slack channel', state.slack_approval_channel] as [string, string]] : []),
    ...(state.email_from ? [['Email from', state.email_from] as [string, string]] : []),
  ]

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-white">Review & create</h3>

      <div className="bg-gray-800/50 rounded-lg p-4 space-y-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between text-sm">
            <span className="text-gray-400">{label}</span>
            <span className="text-white">{value}</span>
          </div>
        ))}
      </div>

      {error && (
        <div className="text-sm text-red-400 bg-red-900/20 border border-red-800 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          disabled={creating}
          className="px-4 py-2 text-gray-400 hover:text-white text-sm disabled:opacity-40"
        >
          Back
        </button>
        <button
          onClick={onSubmit}
          disabled={creating}
          className="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-40 text-white text-sm rounded-lg font-medium"
        >
          {creating ? 'Creating…' : 'Create project'}
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Wizard container
// ---------------------------------------------------------------------------

function ProjectWizard({ onProjectCreated }: { onProjectCreated: (p: Project) => void }) {
  const [step, setStep] = useState(0)
  const [state, setState] = useState<WizardState>(() => {
    // Pre-fill installation_id if we were redirected from GitHub
    const params = new URLSearchParams(window.location.search)
    const iid = params.get('installation_id')
    if (iid) {
      window.history.replaceState({}, '', window.location.pathname)
      return { ...EMPTY_WIZARD, github_installation_id: iid }
    }
    return { ...EMPTY_WIZARD }
  })
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [createdProject, setCreatedProject] = useState<Project | null>(null)

  const set = (k: keyof WizardState, v: string | string[] | null) =>
    setState(s => ({ ...s, [k]: v ?? '' }))

  const submit = async () => {
    setCreating(true)
    setError(null)
    const payload: CreateProjectPayload = {
      name: state.name,
      repo: state.repo,
      base_branch: state.base_branch,
      language: state.language,
      github_installation_id: state.github_installation_id,
      anthropic_api_key: state.anthropic_api_key || null,
      sentry_webhook_secret: state.sentry_webhook_secret || null,
      rollbar_access_token: state.rollbar_access_token || null,
      slack_bot_token: state.slack_bot_token || null,
      slack_signing_secret: state.slack_signing_secret || null,
      slack_approval_channel: state.slack_approval_channel || null,
      sendgrid_api_key: state.sendgrid_api_key || null,
      smtp_host: state.smtp_host || null,
      email_from: state.email_from || null,
      email_to: state.email_to || null,
      alert_sources: state.alert_sources,
    }
    try {
      const project = await createProject(payload)
      setCreatedProject(project)
      onProjectCreated(project)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 max-w-lg w-full">
      <StepBar step={step} total={5} />

      {step === 0 && <Step1 state={state} set={(k, v) => set(k, v as string)} onNext={() => setStep(1)} />}
      {step === 1 && (
        <Step2
          state={state}
          set={(k, v) => set(k, v as string | null)}
          onNext={() => setStep(2)}
          onBack={() => setStep(0)}
        />
      )}
      {step === 2 && (
        <Step3
          state={state}
          set={(k, v) => set(k, v as string | string[])}
          onNext={() => setStep(3)}
          onBack={() => setStep(1)}
        />
      )}
      {step === 3 && (
        <Step4
          state={state}
          set={(k, v) => set(k, v as string)}
          onNext={() => setStep(4)}
          onBack={() => setStep(2)}
        />
      )}
      {step === 4 && (
        <Step5
          state={state}
          onBack={() => setStep(3)}
          onSubmit={submit}
          creating={creating}
          error={error}
          createdProject={createdProject}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Project card
// ---------------------------------------------------------------------------

function ProjectCard({
  project,
  onDelete,
  onUpdated,
}: {
  project: Project
  onDelete: (id: string) => void
  onUpdated: (p: Project) => void
}) {
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)

  // Webhook URLs — fetched lazily when expanded
  const [showWebhooks, setShowWebhooks] = useState(false)
  const [webhooks, setWebhooks] = useState<{ sentry: string; rollbar: string } | null>(null)
  const [webhooksLoading, setWebhooksLoading] = useState(false)

  // Settings edit panel
  const [showEdit, setShowEdit] = useState(false)
  const [editState, setEditState] = useState<Partial<ProjectSettings>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveOk, setSaveOk] = useState(false)

  // A project is Ready when the GitHub App is installed — the key integration
  // that can't fall back to env vars. Anthropic key and webhook secrets fall
  // back to global env var config, so their absence isn't blocking.
  const hasRequired = !!project.github_installation_id

  const doDelete = async () => {
    setDeleting(true)
    try {
      await deleteProject(project.project_id)
      onDelete(project.project_id)
    } catch {
      setDeleting(false)
      setConfirming(false)
    }
  }

  const loadWebhooks = () => {
    setWebhooksLoading(true)
    fetchWebhookUrls(project.project_id)
      .then(setWebhooks)
      .catch(() => {})
      .finally(() => setWebhooksLoading(false))
  }

  const toggleWebhooks = () => {
    const next = !showWebhooks
    setShowWebhooks(next)
    if (next && !webhooks) loadWebhooks()
  }

  const openEdit = () => {
    setEditState({
      anthropic_api_key: project.anthropic_api_key ?? '',
      sentry_webhook_secret: project.sentry_webhook_secret ?? '',
      rollbar_access_token: project.rollbar_access_token ?? '',
      slack_bot_token: project.slack_bot_token ?? '',
      slack_signing_secret: project.slack_signing_secret ?? '',
      slack_approval_channel: project.slack_approval_channel ?? '',
      sendgrid_api_key: project.sendgrid_api_key ?? '',
      smtp_host: project.smtp_host ?? '',
      email_from: project.email_from ?? '',
      email_to: project.email_to ?? '',
    })
    setSaveError(null)
    setSaveOk(false)
    setShowEdit(true)
  }

  const setEdit = (k: keyof ProjectSettings, v: string) =>
    setEditState(s => ({ ...s, [k]: v }))

  const saveEdit = async () => {
    setSaving(true)
    setSaveError(null)
    setSaveOk(false)
    try {
      const updated = await updateProjectSettings(project.project_id, editState)
      onUpdated(updated)
      setSaveOk(true)
      setTimeout(() => {
        setShowEdit(false)
        setSaveOk(false)
      }, 800)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const alertSources: string[] = project.alert_sources
    ? (typeof project.alert_sources === 'string'
        ? (project.alert_sources as string).replace(/[{}"]/g, '').split(',').filter(Boolean)
        : project.alert_sources)
    : []

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-5">
      {/* Header row */}
      <div className="flex items-start justify-between mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-0.5 flex-wrap">
            <span className="font-semibold text-white">{project.name}</span>
            <span
              className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${
                hasRequired
                  ? 'bg-green-900/40 text-green-400'
                  : 'bg-yellow-900/40 text-yellow-400'
              }`}
            >
              {hasRequired ? 'Ready' : 'Incomplete'}
            </span>
          </div>
          <div className="text-sm text-gray-400 truncate">{project.repo}</div>
        </div>

        <div className="flex items-center gap-2 shrink-0 ml-4">
          {!showEdit && (
            <button
              onClick={openEdit}
              className="text-xs text-gray-500 hover:text-gray-300"
              title="Edit optional settings"
            >
              Settings
            </button>
          )}
          {confirming ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400">Delete?</span>
              <button
                onClick={doDelete}
                disabled={deleting}
                className="text-xs px-2 py-1 bg-red-800 hover:bg-red-700 text-white rounded disabled:opacity-50"
              >
                Yes
              </button>
              <button
                onClick={() => setConfirming(false)}
                className="text-xs px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white rounded"
              >
                No
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirming(true)}
              className="text-xs text-gray-500 hover:text-red-400"
            >
              Delete
            </button>
          )}
        </div>
      </div>

      {/* Tags row */}
      <div className="flex flex-wrap gap-2 text-xs text-gray-400 mb-3">
        <span className="bg-gray-800 px-2 py-0.5 rounded">{project.language}</span>
        <span className="bg-gray-800 px-2 py-0.5 rounded">branch: {project.base_branch}</span>
        {project.github_installation_id && (
          <span className="bg-gray-800 px-2 py-0.5 rounded text-green-400">GitHub App ✓</span>
        )}
      </div>

      {/* Webhook URLs toggle */}
      <button
        type="button"
        onClick={toggleWebhooks}
        className="text-xs text-indigo-400 hover:text-indigo-300 mb-1"
      >
        {showWebhooks ? '▲ Hide webhook URLs' : '▼ Show webhook URLs'}
      </button>

      {showWebhooks && (
        <div className="mt-2 space-y-2">
          {webhooksLoading && <p className="text-xs text-gray-500">Loading…</p>}
          {webhooks && (
            <>
              {(alertSources.includes('sentry') || alertSources.length === 0) && (
                <div>
                  <p className="text-xs text-gray-500 mb-1">Sentry webhook URL</p>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 min-w-0 text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-indigo-300 truncate">
                      {webhooks.sentry}
                    </code>
                    <CopyButton text={webhooks.sentry} />
                  </div>
                </div>
              )}
              {alertSources.includes('rollbar') && (
                <div>
                  <p className="text-xs text-gray-500 mb-1">Rollbar webhook URL</p>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 min-w-0 text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-indigo-300 truncate">
                      {webhooks.rollbar}
                    </code>
                    <CopyButton text={webhooks.rollbar} />
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Optional settings edit panel */}
      {showEdit && (
        <div className="mt-4 border-t border-gray-700 pt-4 space-y-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-medium text-gray-300">Optional settings</span>
            <button
              onClick={() => setShowEdit(false)}
              className="text-xs text-gray-500 hover:text-gray-300"
            >
              ✕ Close
            </button>
          </div>

          <div>
            <Label>Anthropic API key</Label>
            <SecretInput
              value={(editState.anthropic_api_key as string) ?? ''}
              onChange={v => setEdit('anthropic_api_key', v)}
              placeholder="sk-ant-… (falls back to env var)"
            />
          </div>

          <div>
            <Label>Sentry webhook secret</Label>
            <SecretInput
              value={(editState.sentry_webhook_secret as string) ?? ''}
              onChange={v => setEdit('sentry_webhook_secret', v)}
              placeholder="Sentry client secret"
            />
          </div>

          <div>
            <Label>Rollbar access token</Label>
            <SecretInput
              value={(editState.rollbar_access_token as string) ?? ''}
              onChange={v => setEdit('rollbar_access_token', v)}
              placeholder="Rollbar project access token"
            />
          </div>

          <Accordion title="Slack notifications">
            <div>
              <Label>Bot token</Label>
              <SecretInput
                value={(editState.slack_bot_token as string) ?? ''}
                onChange={v => setEdit('slack_bot_token', v)}
                placeholder="xoxb-..."
              />
            </div>
            <div>
              <Label>Signing secret</Label>
              <SecretInput
                value={(editState.slack_signing_secret as string) ?? ''}
                onChange={v => setEdit('slack_signing_secret', v)}
                placeholder="Slack signing secret"
              />
            </div>
            <div>
              <Label>Approval channel</Label>
              <TextInput
                value={(editState.slack_approval_channel as string) ?? ''}
                onChange={v => setEdit('slack_approval_channel', v)}
                placeholder="#helix-approvals"
              />
            </div>
          </Accordion>

          <Accordion title="Email notifications">
            <div>
              <Label>SendGrid API key</Label>
              <SecretInput
                value={(editState.sendgrid_api_key as string) ?? ''}
                onChange={v => setEdit('sendgrid_api_key', v)}
                placeholder="SG...."
              />
            </div>
            <div>
              <Label>SMTP host</Label>
              <TextInput
                value={(editState.smtp_host as string) ?? ''}
                onChange={v => setEdit('smtp_host', v)}
                placeholder="smtp.example.com"
              />
            </div>
            <div>
              <Label>From address</Label>
              <TextInput
                value={(editState.email_from as string) ?? ''}
                onChange={v => setEdit('email_from', v)}
                placeholder="helix@example.com"
              />
            </div>
            <div>
              <Label>To address</Label>
              <TextInput
                value={(editState.email_to as string) ?? ''}
                onChange={v => setEdit('email_to', v)}
                placeholder="team@example.com"
              />
            </div>
          </Accordion>

          {saveError && (
            <p className="text-xs text-red-400">{saveError}</p>
          )}

          <button
            onClick={saveEdit}
            disabled={saving}
            className="w-full px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-sm rounded-lg font-medium"
          >
            {saving ? 'Saving…' : saveOk ? '✓ Saved' : 'Save settings'}
          </button>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Projects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [showWizard, setShowWizard] = useState(() => {
    // Auto-open wizard if redirected back from GitHub App install
    return !!new URLSearchParams(window.location.search).get('installation_id')
  })
  // Set to true once the wizard successfully creates a project — changes
  // the Cancel button to a Done button so the user can read the webhook URLs
  // before closing.
  const [wizardDone, setWizardDone] = useState(false)

  const load = () => {
    fetchProjects()
      .then(setProjects)
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const closeWizard = () => {
    setShowWizard(false)
    setWizardDone(false)
  }

  return (
    <div className="max-w-3xl mx-auto py-8 px-4">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Projects</h1>
          <p className="text-sm text-gray-400 mt-1">
            Each project monitors one GitHub repo and has its own webhook URL.
          </p>
        </div>
        {!showWizard && (
          <button
            onClick={() => setShowWizard(true)}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg font-medium"
          >
            + New project
          </button>
        )}
      </div>

      {showWizard && (
        <div className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-gray-300">New project</span>
            <button
              onClick={closeWizard}
              className={`text-sm ${
                wizardDone
                  ? 'text-green-400 hover:text-green-300 font-medium'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              {wizardDone ? '✓ Done' : '✕ Cancel'}
            </button>
          </div>
          <ProjectWizard
            onProjectCreated={() => {
              load()
              setWizardDone(true)
            }}
          />
        </div>
      )}

      {loading ? (
        <div className="text-sm text-gray-400">Loading…</div>
      ) : projects.length === 0 && !showWizard ? (
        <div className="text-center py-16 text-gray-500">
          <div className="text-4xl mb-3">⚡</div>
          <div className="font-medium text-gray-400 mb-1">No projects yet</div>
          <p className="text-sm mb-4">Create a project to start monitoring a GitHub repository.</p>
          <button
            onClick={() => setShowWizard(true)}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg font-medium"
          >
            Create your first project
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {projects.map(p => (
            <ProjectCard
              key={p.project_id}
              project={p}
              onDelete={id => setProjects(ps => ps.filter(p => p.project_id !== id))}
              onUpdated={updated =>
                setProjects(ps => ps.map(p => p.project_id === updated.project_id ? updated : p))
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}
