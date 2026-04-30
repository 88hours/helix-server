import { useState } from 'react';
import { Icon, Button } from './primitives';

export interface AuditEvent {
  id: number;
  incident_id: string | null;
  project_id: string | null;
  event_type: string;
  source: string;
  action: string;
  status: string;
  details: Record<string, unknown> | null;
  ts: string;
}

// Map (event_type, source, action) → display action string + tag/tone
function toDisplayAction(ev: AuditEvent): string {
  if (ev.event_type === 'webhook')      return 'incident.received';
  if (ev.event_type === 'slack_action') return ev.action === 'pr_approved' ? 'pr.approved' : 'pr.rejected';
  if (ev.event_type === 'github_op')    return ev.action === 'pr_created' ? 'pr.opened' : 'pr.merged';
  if (ev.event_type === 'agent_event') {
    const m: Record<string, string> = {
      crash_analysed:        'incident.classified',
      test_case_generated:   'test.generated',
      pr_created:            'pr.opened',
    };
    return m[ev.action] ?? ev.action;
  }
  return `${ev.event_type}.${ev.action}`;
}

function toActorKind(ev: AuditEvent): 'system' | 'agent' | 'user' {
  if (ev.event_type === 'slack_action') return 'user';
  if (ev.event_type === 'agent_event')  return 'agent';
  return 'system';
}

function toActorName(ev: AuditEvent): string {
  const names: Record<string, string> = {
    rollbar:  'rollbar.webhook',
    sentry:   'sentry.webhook',
    slack:    'helix.slack',
    github:   'helix.github',
    handler:  'Crash Handler',
    qa:       'QA Agent',
    dev:      'Dev Agent',
    human:    'Human',
  };
  return names[ev.source] ?? ev.source;
}

const KIND_COLOR: Record<string, string> = {
  agent:  'oklch(0.62 0.16 295)',
  user:   'oklch(0.55 0.13 230)',
  system: 'oklch(0.55 0.01 260)',
};

const ACTION_TONES: Record<string, { tag: string; tone: string }> = {
  'incident.received':   { tag: 'ingest',   tone: 'oklch(0.68 0.17 50)'  },
  'incident.classified': { tag: 'classify', tone: 'oklch(0.62 0.06 260)' },
  'pipeline.started':    { tag: 'pipeline', tone: 'oklch(0.55 0.13 230)' },
  'test.generated':      { tag: 'write',    tone: 'oklch(0.62 0.16 155)' },
  'pr.opened':           { tag: 'github',   tone: 'oklch(0.45 0.04 260)' },
  'pr.merged':           { tag: 'github',   tone: 'oklch(0.45 0.04 260)' },
  'pr.approved':         { tag: 'review',   tone: 'oklch(0.55 0.13 230)' },
  'pr.rejected':         { tag: 'review',   tone: 'oklch(0.6 0.2 25)'    },
};

interface AuditTrailProps {
  events: AuditEvent[];
}

export function AuditTrail({ events }: AuditTrailProps) {
  const [filter, setFilter] = useState<'all' | 'agent' | 'user' | 'system'>('all');
  const [query, setQuery] = useState('');
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  const enriched = events.map(ev => ({
    ev,
    action:    toDisplayAction(ev),
    actorKind: toActorKind(ev),
    actorName: toActorName(ev),
  }));

  const counts = {
    all:    enriched.length,
    agent:  enriched.filter(e => e.actorKind === 'agent').length,
    user:   enriched.filter(e => e.actorKind === 'user').length,
    system: enriched.filter(e => e.actorKind === 'system').length,
  };

  const filtered = enriched.filter(({ ev, action, actorKind, actorName }) => {
    if (filter !== 'all' && actorKind !== filter) return false;
    if (!query) return true;
    const blob = (action + ' ' + actorName + ' ' + JSON.stringify(ev.details ?? {})).toLowerCase();
    return blob.includes(query.toLowerCase());
  });

  return (
    <section style={{
      background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
        background: 'var(--bg)', borderBottom: '1px solid var(--line)',
      }}>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-3)' }}>
          Audit Trail
        </span>
        <span style={{ width: 3, height: 3, borderRadius: '50%', background: 'var(--ink-3)' }} />
        <span className="mono" style={{ fontSize: 11, color: 'var(--ink-2)' }}>
          immutable · {events.length} events
        </span>
        <span style={{ flex: 1 }} />
        <Button variant="ghost" size="sm">export CSV</Button>
      </div>

      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px',
        background: 'var(--bg-2)', borderBottom: '1px solid var(--line)',
      }}>
        <div style={{ display: 'inline-flex', padding: 3, borderRadius: 5, background: 'var(--bg)', border: '1px solid var(--line-2)' }}>
          {(['all', 'agent', 'user', 'system'] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)} style={{
              fontFamily: 'var(--mono)', fontSize: 11.5,
              padding: '4px 10px', borderRadius: 3,
              color: filter === f ? 'var(--ink)' : 'var(--ink-3)',
              background: filter === f ? 'var(--bg-3)' : 'transparent',
              border: filter === f ? '1px solid var(--line-2)' : '1px solid transparent',
            }}>
              {f} <span style={{ color: 'var(--ink-3)' }}>{counts[f]}</span>
            </button>
          ))}
        </div>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '4px 10px', border: '1px solid var(--line-2)', borderRadius: 5,
          background: 'var(--bg)', flex: 1,
        }}>
          <Icon.search size={12} />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="filter by action, actor, details…"
            className="mono"
            style={{ flex: 1, background: 'transparent', border: 0, outline: 'none', fontSize: 11.5, color: 'var(--ink)' }}
          />
          {query && (
            <button onClick={() => setQuery('')} className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>clear</button>
          )}
        </div>
      </div>

      {/* Timeline */}
      <div style={{ padding: '6px 14px' }}>
        {filtered.length === 0 && (
          <div className="mono" style={{ padding: '24px 8px', color: 'var(--ink-3)', fontSize: 12, textAlign: 'center' }}>
            no events match
          </div>
        )}
        {filtered.map(({ ev, action, actorKind, actorName }, i) => {
          const isOpen = openIdx === i;
          const tone = ACTION_TONES[action] ?? { tag: 'event', tone: 'var(--ink-3)' };
          const kindColor = KIND_COLOR[actorKind];
          const time = new Date(ev.ts).toISOString().slice(11, 23) + 'Z';
          const meta = ev.details ?? {};

          return (
            <div key={ev.id} style={{
              display: 'grid', gridTemplateColumns: '110px 24px 1fr',
              alignItems: 'flex-start', padding: '10px 0',
              borderBottom: i < filtered.length - 1 ? '1px dashed var(--line)' : 'none',
            }}>
              {/* Timestamp */}
              <div className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', paddingTop: 2 }}>
                {time}
              </div>

              {/* Actor dot */}
              <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 4 }}>
                <span style={{
                  width: 9, height: 9, borderRadius: '50%',
                  background: kindColor,
                  boxShadow: `0 0 0 3px color-mix(in oklch, ${kindColor} 18%, transparent)`,
                }} />
              </div>

              {/* Body */}
              <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                  <span className="mono" style={{
                    fontSize: 10, letterSpacing: '0.06em', textTransform: 'uppercase',
                    padding: '1px 6px', borderRadius: 3,
                    color: tone.tone,
                    background: `color-mix(in oklch, ${tone.tone} 10%, transparent)`,
                    border: `1px solid color-mix(in oklch, ${tone.tone} 28%, transparent)`,
                  }}>{tone.tag}</span>

                  <span className="mono" style={{ fontSize: 12, color: 'var(--ink)' }}>{action}</span>
                  <span className="mono" style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>by</span>
                  <span className="mono" style={{ fontSize: 11.5, color: kindColor }}>{actorName}</span>

                  <span style={{ flex: 1 }} />

                  <button onClick={() => setOpenIdx(isOpen ? null : i)} className="mono" style={{
                    fontSize: 10.5, color: 'var(--ink-3)',
                    padding: '2px 6px', border: '1px solid var(--line-2)', borderRadius: 3,
                    background: 'var(--bg-2)',
                  }}>
                    {isOpen ? 'hide' : 'details'}
                  </button>
                </div>

                <div className="mono" style={{ fontSize: 11.5, color: 'var(--ink-2)', marginTop: 3 }}>
                  → {ev.incident_id ?? '—'}
                </div>

                {isOpen && Object.keys(meta).length > 0 && (
                  <div style={{
                    marginTop: 8, padding: 10,
                    border: '1px solid var(--line-2)', borderRadius: 5,
                    background: 'var(--bg)',
                  }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <tbody>
                        {Object.entries(meta).map(([k, v]) => (
                          <tr key={k}>
                            <td className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', padding: '3px 10px 3px 0', verticalAlign: 'top', width: 130 }}>{k}</td>
                            <td className="mono" style={{ fontSize: 11.5, color: 'var(--ink)', padding: '3px 0', wordBreak: 'break-all' }}>{String(v)}</td>
                          </tr>
                        ))}
                        <tr>
                          <td className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', padding: '3px 10px 3px 0' }}>status</td>
                          <td className="mono" style={{ fontSize: 11.5, color: ev.status === 'ok' ? 'var(--ok)' : 'var(--crash)', padding: '3px 0' }}>{ev.status}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div style={{
        padding: '10px 14px', borderTop: '1px solid var(--line)',
        display: 'flex', alignItems: 'center', gap: 10,
        background: 'var(--bg)',
      }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--ok)' }} />
        <span className="mono" style={{ fontSize: 11, color: 'var(--ink-2)' }}>
          append-only · all events persisted to Postgres
        </span>
        <span style={{ flex: 1 }} />
        <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>retention: 7 years</span>
      </div>
    </section>
  );
}
