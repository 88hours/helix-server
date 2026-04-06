/**
 * API client for the Helix dashboard.
 *
 * All requests go to the same FastAPI origin (/api/*).  During local dev,
 * Vite proxies /api → http://localhost:8000, so no CORS issues.
 */

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

export interface UIProgressEvent {
  type: 'agent_start' | 'agent_step' | 'agent_done' | 'status_changed'
  agent: string
  message: string
  incident_id: string
  timestamp: string
}

/** List all incidents, newest first. */
export async function fetchIncidents(): Promise<IncidentSummary[]> {
  const res = await fetch('/api/incidents')
  if (!res.ok) throw new Error(`Failed to fetch incidents: ${res.status}`)
  const data = await res.json()
  return data.incidents as IncidentSummary[]
}

/** Fetch the full state for a single incident. */
export async function fetchIncident(incidentId: string): Promise<IncidentDetail> {
  const res = await fetch(`/api/incidents/${incidentId}`)
  if (!res.ok) throw new Error(`Failed to fetch incident: ${res.status}`)
  return res.json() as Promise<IncidentDetail>
}

/**
 * Open an SSE connection to the incident stream.
 *
 * Calls onSnapshot once with the current state snapshot, then calls
 * onProgress for each subsequent agent progress event.
 *
 * Returns a cleanup function that closes the EventSource.
 */
export function subscribeToIncident(
  incidentId: string,
  onSnapshot: (detail: IncidentDetail) => void,
  onProgress: (event: UIProgressEvent) => void,
): () => void {
  const es = new EventSource(`/api/stream/${incidentId}`)

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
