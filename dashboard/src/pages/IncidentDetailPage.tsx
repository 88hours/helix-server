import { useState, useEffect, useRef } from 'react';
import { useIncident, useActivityStream, Incident, ApiIncidentDetail, AgentId } from '../constants';
import { StatusPill, Severity, Icon, Button, Field } from '../components/primitives';
import { Pipeline, incidentToPipelineStages } from '../components/Pipeline';
import { ToolCallsList, PRDiff, ToolCall, DiffHunk } from '../components/ToolCalls';
import { ActivityRail, ActivityEvent } from '../components/ActivityRail';

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

function parseToolCalls(detail: ApiIncidentDetail): ToolCall[] {
  const calls: ToolCall[] = [];
  const pr = detail.pr_result;
  if (!pr) return calls;
  const agentOrder: AgentId[] = ['handler', 'qa', 'dev'];
  agentOrder.forEach(agent => {
    const agentData = (pr as Record<string, unknown>)[agent] as Record<string, unknown> | undefined;
    const toolCalls = agentData?.tool_calls as Array<Record<string, unknown>> | undefined;
    if (!toolCalls) return;
    toolCalls.forEach((tc, i) => {
      calls.push({
        id: `${agent}-${i}`, agent,
        tool: String(tc.tool ?? 'LLM'),
        input: String(tc.input ?? ''),
        output: tc.output ? String(tc.output) : undefined,
        ts: String(tc.ts ?? ''),
        durationMs: tc.duration_ms as number | undefined,
      });
    });
  });
  return calls;
}

function parseDiff(detail: ApiIncidentDetail): DiffHunk[] {
  const pr = detail.pr_result as Record<string, unknown> | null;
  const devData = pr?.dev as Record<string, unknown> | undefined;
  const diff = devData?.diff as Array<Record<string, unknown>> | string | undefined;
  if (!diff) return [];
  if (typeof diff === 'string') {
    return [{ file: 'patch', lines: diff.split('\n').map(line => ({
      type: (line.startsWith('+') ? '+' : line.startsWith('-') ? '-' : ' ') as '+' | '-' | ' ',
      text: line.slice(1),
    })) }];
  }
  return (diff as Array<Record<string, unknown>>).map(d => ({
    file: String(d.file ?? 'unknown'),
    lines: (d.lines as Array<Record<string, unknown>> ?? []).map(l => ({
      type: String(l.type ?? ' ') as '+' | '-' | ' ',
      text: String(l.text ?? ''),
    })),
  }));
}

interface IncidentDetailPageProps {
  incident: Incident | null;
  onBack: () => void;
  showActivityRail: boolean;
  pipelineLayout: 'horizontal' | 'vertical';
}

export function IncidentDetailPage({ incident, onBack, showActivityRail }: IncidentDetailPageProps) {
  const { data: detail } = useIncident(incident?.id ?? null);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const evIdRef = useRef(0);

  useActivityStream(incident?.id ?? null, (type, data) => {
    const ev: ActivityEvent = {
      id: String(evIdRef.current++),
      ts: new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      type: type === 'progress' ? 'status' : 'log',
      message: JSON.stringify(data).slice(0, 200),
    };
    setEvents(prev => [...prev.slice(-499), ev]);
  });

  useEffect(() => {
    if (detail) setToolCalls(parseToolCalls(detail));
  }, [detail]);

  if (!incident) {
    return (
      <div style={{ padding: 32, color: 'var(--ink-3)', fontFamily: 'var(--mono)', fontSize: 12 }}>
        incident not found
      </div>
    );
  }

  const stages = incidentToPipelineStages(incident.status);
  const diff = detail ? parseDiff(detail) : [];

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
              <Button variant="ghost" size="sm"><Icon.refresh size={11} /> rerun</Button>
              {incident.status === 'approval' && (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => incident.prUrl ? window.open(incident.prUrl, '_blank', 'noopener,noreferrer') : undefined}
                >
                  <Icon.check size={11} /> approve PR
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* Pipeline */}
        <div style={{ marginBottom: 16 }}>
          <Pipeline stages={stages} layout="horizontal" />
        </div>

        {/* Content stacked */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <ToolCallsList calls={toolCalls} />
          <PRDiff hunks={diff} prUrl={incident.prUrl} />
          {detail?.crash_report && (
            <CrashReport data={detail.crash_report} incident={incident} />
          )}
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
