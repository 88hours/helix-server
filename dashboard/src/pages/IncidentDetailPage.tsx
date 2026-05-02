import { useState, useRef } from 'react';
import { useIncident, useActivityStream, useAuditEvents, Incident, ApiIncidentDetail } from '../constants';
import { StatusPill, Severity, Icon, Button, Field } from '../components/primitives';
import { Pipeline, incidentToPipelineStages } from '../components/Pipeline';
import { ActivityRail, ActivityEvent } from '../components/ActivityRail';
import { AuditTrail } from '../components/AuditTrail';

function TestCaseCard({ qa }: { qa: NonNullable<ApiIncidentDetail['qa_result']> }) {
  const tc = qa.test_case;
  if (!tc) return null;
  return (
    <section style={{ border: '1px solid var(--line)', borderRadius: 8, background: 'var(--bg)', overflow: 'hidden' }}>
      <div style={{
        padding: '10px 14px', borderBottom: '1px solid var(--line)',
        background: 'var(--bg-2)', display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
          QA · Test case
        </span>
        <span style={{ color: 'var(--ink-3)' }}>·</span>
        <span className="mono" style={{ fontSize: 11, color: 'var(--qa)' }}>{tc.file_path}</span>
        {qa.ticket_url && (
          <>
            <span style={{ flex: 1 }} />
            <a href={qa.ticket_url} target="_blank" rel="noopener noreferrer"
              className="mono" style={{ fontSize: 10.5, color: 'var(--accent)', textDecoration: 'none' }}>
              <Icon.github size={10} /> {qa.ticket_id}
            </a>
          </>
        )}
      </div>
      <div style={{ padding: '10px 14px 4px' }}>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          {tc.test_name}
        </span>
      </div>
      <pre style={{
        margin: 0, padding: '10px 18px 16px',
        fontFamily: 'var(--mono)', fontSize: 12, lineHeight: 1.6,
        color: 'var(--ink-2)', overflowX: 'auto', whiteSpace: 'pre',
      }}>{tc.content}</pre>
    </section>
  );
}

function CrashReport({ data, incident }: { data: Record<string, unknown>; incident: Incident }) {
  const [stackOpen, setStackOpen] = useState(false);
  const trace = Array.isArray(data.stack_trace)
    ? data.stack_trace as Array<{ file: string; line: number; fn: string; highlight?: boolean }>
    : [];

  return (
    <section style={{ border: '1px solid var(--line)', borderRadius: 8, background: 'var(--bg)', overflow: 'hidden' }}>
      <div style={{
        padding: '10px 14px', borderBottom: '1px solid var(--line)',
        background: 'var(--bg-2)', display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
          Crash report
        </span>
        {data.source != null && (
          <>
            <span style={{ color: 'var(--ink-3)' }}>·</span>
            <span className="mono" style={{ fontSize: 11, color: 'var(--ink-2)' }}>{String(data.source)}</span>
          </>
        )}
      </div>

      <div style={{ padding: '16px 18px', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        <Field label="Error type" value={String(data.error_type ?? incident.error)} mono />
        <Field label="Component" value={String(data.affected_component ?? incident.component)} />
        <Field label="Endpoint" value={String(data.endpoint ?? '—')} mono />
        <Field label="Language" value={String(data.language ?? '—')} mono />
        <Field label="Source" value={String(data.source ?? '—')} />
        <Field label="Detected" value={incident.createdAt} />
        <Field label="Occurrences" value={`${incident.occurrences ?? 0}× · ${incident.users ?? 0} users`} />
        <Field label="Dedupe hash" value={incident.short} mono />
      </div>

      {data.summary != null && (
        <div style={{ padding: '0 18px 16px' }}>
          <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6 }}>
            Summary
          </div>
          <p style={{ margin: 0, fontSize: 13.5, color: 'var(--ink-2)', lineHeight: 1.6, maxWidth: 800 }}>
            {String(data.summary)}
          </p>
        </div>
      )}

      {trace.length > 0 && (
        <div style={{ borderTop: '1px solid var(--line)' }}>
          <button
            onClick={() => setStackOpen(o => !o)}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '10px 18px', width: '100%', textAlign: 'left',
              fontFamily: 'var(--mono)', fontSize: 11.5, color: 'var(--ink-2)',
              background: 'none', border: 'none', cursor: 'pointer',
            }}
          >
            <Icon.chev size={11} dir={stackOpen ? 'down' : 'right'} />
            Stack trace
            <span style={{ color: 'var(--ink-3)' }}>{trace.length} frames</span>
          </button>
          {stackOpen && (
            <div style={{ padding: '6px 18px 16px', fontFamily: 'var(--mono)', fontSize: 12 }}>
              {trace.map((f, i) => (
                <div key={i} style={{
                  padding: '4px 8px',
                  background: f.highlight ? 'oklch(0.97 0.04 25)' : 'transparent',
                  borderLeft: f.highlight ? '2px solid var(--crash)' : '2px solid transparent',
                  color: f.highlight ? 'var(--crash)' : 'var(--ink-2)',
                }}>
                  <span>{f.file}:{f.line}</span>
                  <span style={{ color: 'var(--ink-3)' }}> in </span>
                  <span>{f.fn}()</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function PRResultCard({ pr }: { pr: NonNullable<ApiIncidentDetail['pr_result']> }) {
  return (
    <section style={{ border: '1px solid var(--line)', borderRadius: 8, background: 'var(--bg)', overflow: 'hidden' }}>
      <div style={{
        padding: '10px 14px', borderBottom: '1px solid var(--line)',
        background: 'var(--bg-2)', display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
          Dev · Pull request
        </span>
        <span style={{ color: 'var(--ink-3)' }}>·</span>
        <span className="mono" style={{ fontSize: 11, color: 'var(--dev)' }}>{pr.branch_name}</span>
        <span style={{ flex: 1 }} />
        <a href={pr.pr_url} target="_blank" rel="noopener noreferrer"
          className="mono" style={{ fontSize: 10.5, color: 'var(--accent)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
          <Icon.github size={10} /> PR #{pr.pr_number}
        </a>
      </div>
      <div style={{ padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {pr.fix_summary && (
          <p style={{ margin: 0, fontSize: 13.5, color: 'var(--ink-2)', lineHeight: 1.6 }}>{pr.fix_summary}</p>
        )}
        <div style={{ display: 'flex', gap: 20 }}>
          <div>
            <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 3 }}>Iterations</div>
            <div className="mono" style={{ fontSize: 13, color: 'var(--ink)' }}>{pr.iterations_taken}</div>
          </div>
          <div>
            <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 3 }}>Files changed</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {pr.files_changed.length > 0
                ? pr.files_changed.map(f => (
                    <span key={f} className="mono" style={{ fontSize: 12, color: 'var(--ink-2)' }}>{f}</span>
                  ))
                : <span className="mono" style={{ fontSize: 12, color: 'var(--ink-3)' }}>—</span>
              }
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}


interface IncidentDetailPageProps {
  incident: Incident | null;
  onBack: () => void;
  onRefresh?: () => void;
  showActivityRail: boolean;
  pipelineLayout: 'horizontal' | 'swimlane';
}

export function IncidentDetailPage({ incident, onBack, onRefresh, showActivityRail, pipelineLayout }: IncidentDetailPageProps) {
  const { data: detail, reload: reloadDetail } = useIncident(incident?.id ?? null);

  const handleRefresh = () => { reloadDetail(); onRefresh?.(); };
  const { events: auditEvents } = useAuditEvents(incident?.id ?? null);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const evIdRef = useRef(0);

  useActivityStream(incident?.id ?? null, (type, data) => {
    if (type === 'snapshot') {
      const past = (data.events as Record<string, unknown>[] | undefined) ?? [];
      const hydrated: ActivityEvent[] = past.map(e => ({
        id: String(evIdRef.current++),
        ts: e.timestamp ? new Date(e.timestamp as string).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—',
        type: 'status' as const,
        message: (e.message as string) ?? (e.type === 'tool_call' ? `${e.agent} › ${e.tool} › ${e.action} [${e.status}]${e.detail ? ` — ${e.detail}` : ''}` : JSON.stringify(e).slice(0, 200)),
      }));
      setEvents(hydrated);
    } else {
      const ev: ActivityEvent = {
        id: String(evIdRef.current++),
        ts: new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        type: 'status',
        message: (data.message as string) ?? (data.type === 'tool_call' ? `${data.agent} › ${data.tool} › ${data.action} [${data.status}]${data.detail ? ` — ${data.detail}` : ''}` : JSON.stringify(data).slice(0, 200)),
      };
      setEvents(prev => [...prev.slice(-499), ev]);
    }
  });

  if (!incident) {
    return (
      <div style={{ padding: 32, color: 'var(--ink-3)', fontFamily: 'var(--mono)', fontSize: 12 }}>
        incident not found
      </div>
    );
  }

  const stages = incidentToPipelineStages(incident.status);

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: showActivityRail ? 'minmax(0, 1fr) 420px' : '1fr',
      gap: 16,
      padding: '16px 22px 40px',
      maxWidth: 1600, margin: '0 auto',
    }}>

      {/* Main column */}
      <div style={{ minWidth: 0 }}>
        {/* Breadcrumb */}
        <div style={{ marginBottom: 16 }}>
          <button
            onClick={onBack}
            className="mono"
            style={{
              fontSize: 11, color: 'var(--ink-3)', padding: '3px 6px',
              border: '1px solid var(--line-2)', borderRadius: 4, background: 'var(--bg-2)',
              cursor: 'pointer',
            }}
          >
            ← all incidents
          </button>

          {/* Title row */}
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 20, marginTop: 14 }}>
            <div style={{ minWidth: 0 }}>
              <div className="mono" style={{ fontSize: 12, color: 'var(--accent)', letterSpacing: '0.01em', marginBottom: 4 }}>
                {incident.id}
              </div>
              <h1 style={{ margin: 0, fontFamily: 'var(--serif)', fontSize: 42, fontWeight: 400, letterSpacing: '-0.02em', lineHeight: 1.05 }}>
                <span style={{ color: 'var(--crash)' }}>{incident.error}</span>
                <span style={{ color: 'var(--ink-3)' }}> in </span>
                <span className="mono" style={{ fontSize: 30, color: 'var(--ink)' }}>{incident.component}</span>
              </h1>
              {incident.message && (
                <p style={{ margin: '8px 0 0', fontSize: 14, color: 'var(--ink-2)' }}>
                  <span className="mono" style={{ fontSize: 13 }}>{incident.message}</span>
                </p>
              )}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexShrink: 0 }}>
              <Severity level={incident.severity} />
              <StatusPill status={incident.status} />
              <span style={{ width: 1, height: 18, background: 'var(--line-2)', margin: '0 4px' }} />
              <Button variant="ghost" size="sm" onClick={handleRefresh}><Icon.refresh size={11} /> refresh</Button>
              {incident.status === 'approval' && detail?.pr_result?.pr_url && (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => window.open(detail.pr_result!.pr_url, '_blank', 'noopener,noreferrer')}
                >
                  <Icon.check size={11} /> approve PR
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* Pipeline */}
        <div style={{ marginBottom: 16 }}>
          <Pipeline stages={stages} layout={pipelineLayout} />
        </div>

        {/* Content stacked */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {detail?.qa_result && <TestCaseCard qa={detail.qa_result} />}
          {detail?.pr_result && <PRResultCard pr={detail.pr_result} />}
          {detail?.crash_report && (
            <CrashReport data={detail.crash_report} incident={incident} />
          )}
          <AuditTrail events={auditEvents} />
        </div>
      </div>

      {/* Activity rail */}
      {showActivityRail && (
        <div style={{ minWidth: 0 }}>
          <ActivityRail events={events} title="live stream" />
        </div>
      )}
    </div>
  );
}
