/**
 * Settings page — account-level LLM key configuration.
 *
 * Keys stored here apply to all projects. The resolution order in agents is:
 *   1. Per-project override (set in project settings)
 *   2. User-level key (set here)
 *   3. Global env var fallback (ANTHROPIC_API_KEY / OPENROUTER_API_KEY)
 */

import { useEffect, useState } from 'react'
import { fetchUserSettings, updateUserSettings, type UserSettings } from '../api'

// ---------------------------------------------------------------------------
// Tiny UI primitives (local copies — keeps the page self-contained)
// ---------------------------------------------------------------------------

function Label({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <div className="mb-1">
      <label className="block text-sm font-medium text-gray-300">{children}</label>
      {hint && <p className="text-xs text-gray-500 mt-0.5">{hint}</p>}
    </div>
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

// ---------------------------------------------------------------------------
// Settings form state
// ---------------------------------------------------------------------------

interface FormState {
  anthropic_api_key: string
  openrouter_api_key: string
  ollama_base_url: string
}

function toFormState(s: UserSettings): FormState {
  return {
    anthropic_api_key: s.anthropic_api_key ?? '',
    openrouter_api_key: s.openrouter_api_key ?? '',
    ollama_base_url: s.ollama_base_url ?? '',
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Settings() {
  const [form, setForm] = useState<FormState>({
    anthropic_api_key: '',
    openrouter_api_key: '',
    ollama_base_url: '',
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveOk, setSaveOk] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchUserSettings()
      .then(s => setForm(toFormState(s)))
      .catch(err => setError(err instanceof Error ? err.message : 'Failed to load settings'))
      .finally(() => setLoading(false))
  }, [])

  const set = (k: keyof FormState, v: string) => setForm(s => ({ ...s, [k]: v }))

  const save = async () => {
    setSaving(true)
    setSaveOk(false)
    setError(null)
    try {
      const updated = await updateUserSettings({
        anthropic_api_key: form.anthropic_api_key || null,
        openrouter_api_key: form.openrouter_api_key || null,
        ollama_base_url: form.ollama_base_url || null,
      })
      setForm(toFormState(updated))
      setSaveOk(true)
      setTimeout(() => setSaveOk(false), 2500)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-xl mx-auto py-8 px-4">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-sm text-gray-400 mt-1">
          Account-level LLM keys. These apply to all your projects unless overridden per-project.
        </p>
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : (
        <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 space-y-6">

          {/* Anthropic */}
          <div>
            <h2 className="text-sm font-semibold text-white mb-3">Anthropic</h2>
            <div>
              <Label
                hint="Required for the Dev Agent TDD loop. Falls back to the ANTHROPIC_API_KEY env var if not set."
              >
                API key
              </Label>
              <SecretInput
                value={form.anthropic_api_key}
                onChange={v => set('anthropic_api_key', v)}
                placeholder="sk-ant-..."
              />
            </div>
          </div>

          <hr className="border-gray-700" />

          {/* OpenRouter */}
          <div>
            <h2 className="text-sm font-semibold text-white mb-3">OpenRouter</h2>
            <p className="text-xs text-gray-500 mb-3">
              Use open-weight models (Qwen, Mistral, DeepSeek, GLM) for Crash Handler and QA agents.
              Get a key at <span className="text-gray-400">openrouter.ai</span>.
            </p>
            <div>
              <Label hint="Falls back to the OPENROUTER_API_KEY env var if not set.">
                API key
              </Label>
              <SecretInput
                value={form.openrouter_api_key}
                onChange={v => set('openrouter_api_key', v)}
                placeholder="sk-or-v1-..."
              />
            </div>
          </div>

          <hr className="border-gray-700" />

          {/* Ollama */}
          <div>
            <h2 className="text-sm font-semibold text-white mb-3">Ollama <span className="text-xs font-normal text-gray-500">(self-hosted)</span></h2>
            <p className="text-xs text-gray-500 mb-3">
              Point Crash Handler and QA at your own Ollama instance. Requires a GPU server —
              CPU inference is too slow for the pipeline. Not used by the Dev Agent.
            </p>
            <div>
              <Label hint="The base URL of your Ollama instance, e.g. http://my-server:11434/v1">
                Base URL
              </Label>
              <TextInput
                value={form.ollama_base_url}
                onChange={v => set('ollama_base_url', v)}
                placeholder="http://my-server:11434/v1"
              />
            </div>
          </div>

          <hr className="border-gray-700" />

          {error && (
            <p className="text-sm text-red-400 bg-red-900/20 border border-red-800 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            onClick={save}
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
