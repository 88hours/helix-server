/**
 * API client for the Helix dashboard.
 *
 * All requests go to the same FastAPI origin (/api/*).  During local dev,
 * Vite proxies /api → http://localhost:8000, so no CORS issues.
 *
 * When Auth0 is configured, call setTokenProvider() once at app startup to
 * supply the function that returns the current access token.  All API calls
 * will then include an Authorization: Bearer header automatically.
 */

// Token provider injected by the Auth0-aware app shell.
let _getToken: (() => Promise<string | null>) | null = null

/** Register the function that returns the current Auth0 access token. */
export function setTokenProvider(fn: () => Promise<string | null>): void {
  _getToken = fn
}

async function _authHeaders(): Promise<Record<string, string>> {
  if (!_getToken) return {}
  try {
    const token = await _getToken()
    if (token) return { Authorization: `Bearer ${token}` }
  } catch {
    // Token fetch failed — send request without auth (server will reject if required)
  }
  return {}
}

export interface IncidentSummary {
  incident_id: string
  status: string
  error_type: string | null
  error_message: string | null
  severity: 'critical' | 'high' | 'medium' | null
  affected_component: string | null
  summary: string | null
  timestamp: string | null
}

export interface CrashReport {
  incident_id: string
  source_item_id: string
  source: string
  severity: string
  error_type: string
  error_message: string
  stack_trace: string
  affected_component: string
  affected_endpoint: string
  summary: string
  language: string
  timestamp: string
}

export interface TestCase {
  file_path: string
  test_name: string
  content: string
  format: string
}

export interface QAResult {
  incident_id: string
  ticket_id: string
  ticket_url: string
  ticket_action: string
  test_case: TestCase
  relevant_files: string[]
}

export interface PRResult {
  incident_id: string
  pr_url: string
  pr_number: number
  branch_name: string
  iterations_taken: number
  files_changed: string[]
  fix_summary: string
}

export interface IncidentDetail {
  incident_id: string
  status: string
  crash_report: CrashReport | null
  qa_result: QAResult | null
  pr_result: PRResult | null
}

export interface AgentProgressEvent {
  type: 'agent_start' | 'agent_step' | 'agent_done' | 'status_changed'
  agent: string
  message: string
  incident_id: string
  timestamp: string
}

export interface ToolCallEvent {
  type: 'tool_call'
  agent: string
  tool: 'llm' | 'github' | 'git' | 'claude_code'
  action: string
  status: 'success' | 'failed'
  detail: string
  incident_id: string
  timestamp: string
}

export type UIProgressEvent = AgentProgressEvent | ToolCallEvent

/** List all incidents, newest first. */
export async function fetchIncidents(): Promise<IncidentSummary[]> {
  const headers = await _authHeaders()
  const res = await fetch('/api/incidents', { headers })
  if (!res.ok) throw new Error(`Failed to fetch incidents: ${res.status}`)
  const data = await res.json()
  return data.incidents as IncidentSummary[]
}

/** Fetch the full state for a single incident. */
export async function fetchIncident(incidentId: string): Promise<IncidentDetail> {
  const headers = await _authHeaders()
  const res = await fetch(`/api/incidents/${incidentId}`, { headers })
  if (!res.ok) throw new Error(`Failed to fetch incident: ${res.status}`)
  return res.json() as Promise<IncidentDetail>
}

/**
 * Open an SSE connection to the incident stream.
 *
 * EventSource cannot send Authorization headers, so the token is passed as
 * an ?access_token= query parameter which the backend accepts as a fallback.
 *
 * Calls onSnapshot once with the current state snapshot, then calls
 * onProgress for each subsequent agent progress event.
 *
 * Returns a cleanup function that closes the EventSource.
 */
export async function subscribeToIncident(
  incidentId: string,
  onSnapshot: (detail: IncidentDetail) => void,
  onProgress: (event: UIProgressEvent) => void,
): Promise<() => void> {
  let url = `/api/stream/${incidentId}`

  if (_getToken) {
    try {
      const token = await _getToken()
      if (token) url += `?access_token=${encodeURIComponent(token)}`
    } catch {
      // proceed without token
    }
  }

  const es = new EventSource(url)

  es.addEventListener('snapshot', (e: MessageEvent) => {
    try {
      onSnapshot(JSON.parse(e.data) as IncidentDetail)
    } catch {
      // ignore malformed snapshot
    }
  })

  es.addEventListener('progress', (e: MessageEvent) => {
    try {
      onProgress(JSON.parse(e.data) as UIProgressEvent)
    } catch {
      // ignore malformed progress event
    }
  })

  return () => es.close()
}

// ---------------------------------------------------------------------------
// Repo configuration
// ---------------------------------------------------------------------------

export interface RepoConfig {
  repo: string
  base_branch: string
  language: string
  added_at: string
}

/** List the calling user's configured repos. */
export async function fetchRepos(): Promise<RepoConfig[]> {
  const headers = await _authHeaders()
  const res = await fetch('/api/repos', { headers })
  if (!res.ok) throw new Error(`Failed to fetch repos: ${res.status}`)
  const data = await res.json()
  return data.repos as RepoConfig[]
}

/** Add a repo to the calling user's configuration. */
export async function addRepo(repo: string, baseBranch = 'main', language = 'python'): Promise<RepoConfig> {
  const headers = { ...(await _authHeaders()), 'Content-Type': 'application/json' }
  const res = await fetch('/api/repos', {
    method: 'POST',
    headers,
    body: JSON.stringify({ repo, base_branch: baseBranch, language }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail ?? `Failed to add repo: ${res.status}`)
  }
  return res.json() as Promise<RepoConfig>
}

/** Remove a repo from the calling user's configuration. */
export async function removeRepo(repo: string): Promise<void> {
  const [owner, name] = repo.split('/')
  const headers = await _authHeaders()
  const res = await fetch(`/api/repos/${owner}/${name}`, { method: 'DELETE', headers })
  if (!res.ok) throw new Error(`Failed to remove repo: ${res.status}`)
}

// ---------------------------------------------------------------------------
// Auth / identity
// ---------------------------------------------------------------------------

export interface Me {
  sub: string | null
  name: string | null
  email: string | null
  picture: string | null
}

/** Return the calling user's identity from the API. */
export async function fetchMe(): Promise<Me> {
  const headers = await _authHeaders()
  const res = await fetch('/api/me', { headers })
  if (!res.ok) throw new Error(`Failed to fetch user: ${res.status}`)
  return res.json() as Promise<Me>
}
