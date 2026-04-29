import { useState, useEffect } from 'react';
import { authFetch } from './lib/authFetch';

// ---- Types ----

export type AgentId = 'handler' | 'qa' | 'dev' | 'human';

export interface Agent {
  id: AgentId;
  name: string;
  short: string;
  color: string;
  symbol: string;
}

export interface StackFrame {
  file: string;
  line: number;
  fn: string;
  highlight?: boolean;
}

export interface Incident {
  id: string;
  short: string;
  error: string;
  message: string;
  component: string;
  severity: string;
  status: string;
  createdAt: string;
  createdAtLong?: string;
  summary: string;
  occurrences: number;
  users: number;
  progress: number;
  project_id?: string;
  duplicateOf?: string;
  note?: string;
  source?: string;
  stackTrace?: StackFrame[];
  endpoint?: string;
  language?: string;
  pr?: string | null;
  prUrl?: string | null;
}

export interface ProjectSecret {
  set: boolean;
  preview?: string;
}

export interface Project {
  id: string;
  name: string;
  repo: string;
  branch: string;
  language: string;
  status: string;
  warning?: string;
  stats: { incidents7d: number; prs7d: number; merged7d: number; meanFix: string };
  activity: number[];
  webhooks: Record<string, string>;
  secrets: { anthropic: ProjectSecret; sentry: ProjectSecret; rollbar: ProjectSecret };
  notify: {
    slack: { enabled: boolean; channel?: string; events?: string[] };
    email: { enabled: boolean; to?: string };
  };
}

export interface ApiIncidentDetail {
  incident_id: string;
  status: string;
  crash_report?: Record<string, unknown>;
  pr_result?: Record<string, unknown>;
}

export interface Tweaks {
  theme: string;
  accent: string;
  density: string;
  pipeline: string;
  showActivityRail: boolean;
}

declare global {
  interface Window { __TWEAKS: Tweaks }
}

// ---- Constants ----

export const AGENTS: Record<AgentId, Agent> = {
  handler: { id:'handler', name:'Crash Handler', short:'handler', color:'var(--handler)', symbol:'◆' },
  qa:      { id:'qa',      name:'QA Agent',      short:'qa',      color:'var(--qa)',      symbol:'▲' },
  dev:     { id:'dev',     name:'Dev Agent',     short:'dev',     color:'var(--dev)',     symbol:'●' },
  human:   { id:'human',   name:'Human',         short:'human',   color:'var(--human)',   symbol:'◐' },
};

export const STATUSES: Record<string, { label: string; color: string }> = {
  crash:     { label:'Crash',      color:'var(--crash)' },
  analysing: { label:'Analysing',  color:'var(--warn)'  },
  testing:   { label:'Test Gen',   color:'var(--qa)'    },
  fixing:    { label:'Fixing',     color:'var(--dev)'   },
  pr:        { label:'PR Created', color:'var(--dev)'   },
  approval:  { label:'Approval',   color:'var(--human)' },
  merged:    { label:'Merged',     color:'var(--ok)'    },
  duplicate: { label:'Duplicate',  color:'var(--ink-3)' },
  failed:    { label:'Failed',     color:'var(--crash)' },
};

// ---- Helpers ----

export function statusToProgress(status: string): number {
  const map: Record<string, number> = {
    analysing: 0.15, testing: 0.3, fixing: 0.5, pr: 0.6, approval: 0.8, merged: 1,
  };
  return map[status] ?? 0;
}

export function fmtTimestamp(iso?: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day:'numeric', month:'short' }) + ' · ' +
         d.toLocaleTimeString('en-GB', { hour:'2-digit', minute:'2-digit' });
}

export function mapApiIncident(raw: Record<string, unknown>): Incident {
  return {
    id: raw.incident_id as string,
    short: (raw.incident_id as string).slice(0, 8),
    error: (raw.error_type as string) || '—',
    message: (raw.error_message as string) || '',
    component: (raw.affected_component as string) || '—',
    severity: (raw.severity as string) || 'medium',
    status: (raw.status as string) || 'unknown',
    createdAt: fmtTimestamp(raw.timestamp as string | undefined),
    summary: (raw.summary as string) || '',
    occurrences: 0,
    users: 0,
    progress: statusToProgress(raw.status as string),
    project_id: raw.project_id as string | undefined,
  };
}

export function mapApiProject(raw: Record<string, unknown>): Project {
  const base = window.location.origin;
  const id = raw.project_id as string;
  return {
    id,
    name: raw.name as string,
    repo: raw.repo as string,
    branch: (raw.base_branch as string) || 'main',
    language: (raw.language as string) || 'python',
    status: 'ready',
    stats: { incidents7d: 0, prs7d: 0, merged7d: 0, meanFix: '—' },
    activity: [],
    webhooks: {
      sentry:  `${base}/webhook/sentry/${id}`,
      rollbar: `${base}/webhook/rollbar/${id}`,
    },
    secrets: {
      anthropic: { set: raw.anthropic_api_key === '***' },
      sentry:    { set: raw.sentry_webhook_secret === '***', preview: raw.sentry_webhook_secret === '***' ? '••••••• (set)' : '' },
      rollbar:   { set: raw.rollbar_access_token === '***',  preview: raw.rollbar_access_token === '***' ? '••••••• (set)' : '' },
    },
    notify: {
      slack: { enabled: !!(raw.slack_approval_channel), channel: (raw.slack_approval_channel as string) || '' },
      email: { enabled: !!(raw.email_to), to: (raw.email_to as string) || '' },
    },
  };
}

// ---- Hooks ----

export function useIncidents(): { incidents: Incident[]; loading: boolean } {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    authFetch('/api/incidents')
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then((d: { incidents?: Record<string, unknown>[] }) => {
        setIncidents((d.incidents || []).map(mapApiIncident));
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);
  return { incidents, loading };
}

export function useIncident(id: string | null): { data: ApiIncidentDetail | null; loading: boolean } {
  const [data, setData] = useState<ApiIncidentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    if (!id) return;
    authFetch(`/api/incidents/${id}`)
      .then(r => r.ok ? r.json() : null)
      .then((d: ApiIncidentDetail | null) => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [id]);
  return { data, loading };
}

export function useActivityStream(
  id: string | null,
  onEvent: (type: string, data: Record<string, unknown>) => void,
): void {
  useEffect(() => {
    if (!id) return;
    const es = new EventSource(`/api/stream/${id}`);
    es.addEventListener('snapshot', e => { try { onEvent('snapshot', JSON.parse((e as MessageEvent).data)); } catch { /* ignore */ } });
    es.addEventListener('progress', e => { try { onEvent('progress', JSON.parse((e as MessageEvent).data)); } catch { /* ignore */ } });
    return () => es.close();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
}

export function useProjects(): {
  projects: Project[];
  loading: boolean;
  saveProjectSettings: (id: string, settings: Record<string, string>) => Promise<boolean>;
  deleteProject: (id: string) => Promise<boolean>;
  reload: () => void;
} {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = () => {
    authFetch('/api/projects')
      .then(r => r.ok ? r.json() : null)
      .then((d: { projects?: Record<string, unknown>[] } | null) => {
        if (d?.projects) setProjects(d.projects.map(mapApiProject));
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const saveProjectSettings = async (projectId: string, settings: Record<string, string>): Promise<boolean> => {
    const res = await authFetch(`/api/projects/${projectId}/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });
    if (res.ok) reload();
    return res.ok;
  };

  const deleteProject = async (projectId: string): Promise<boolean> => {
    const res = await authFetch(`/api/projects/${projectId}`, { method: 'DELETE' });
    if (res.ok) reload();
    return res.ok;
  };

  return { projects, loading, saveProjectSettings, deleteProject, reload };
}

export interface Settings {
  anthropic_api_key: string | null;
  openrouter_api_key: string | null;
  ollama_base_url: string | null;
}

export function useSettings(): { settings: Settings; saveSettings: (updates: Partial<Settings>) => Promise<boolean> } {
  const [settings, setSettings] = useState<Settings>({ anthropic_api_key: null, openrouter_api_key: null, ollama_base_url: null });
  useEffect(() => {
    authFetch('/api/settings')
      .then(r => r.ok ? r.json() : null)
      .then((d: Settings | null) => { if (d) setSettings(d); })
      .catch(() => { /* ignore */ });
  }, []);
  const saveSettings = async (updates: Partial<Settings>): Promise<boolean> => {
    const res = await authFetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    if (res.ok) { const d: Settings = await res.json(); setSettings(d); }
    return res.ok;
  };
  return { settings, saveSettings };
}
