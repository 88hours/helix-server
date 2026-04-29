import { useState, useEffect, useRef } from 'react';
import { useIncident, useActivityStream, Incident, ApiIncidentDetail, AgentId } from '../constants';
import { Badge, StatusPill, Severity, AgentChip, Icon, Button } from '../components/primitives';
import { Pipeline, incidentToPipelineStages } from '../components/Pipeline';
import { ToolCallsList, PRDiff, ToolCall, DiffHunk } from '../components/ToolCalls';
import { ActivityRail, ActivityEvent } from '../components/ActivityRail';

interface CrashReportProps {
  data: Record<string, unknown>;
}

function CrashReport({ data }: CrashReportProps) {
  const [open, setOpen] = useState(true);
  const trace = Array.isArray(data.stack_trace) ? data.stack_trace as Array<{ file: string; line: number; fn: string; highlight?: boolean }> : [];
  return (
    <div style={{ border: '1px solid var(--line-2)', borderRadius: 6, overflow: 'hidden', marginBottom: 16 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 12px', background: 'var(--bg-2)', borderBottom: open ? '1px solid var(--line)' : 'none',
          border: 'none', cursor: 'pointer',
        }}
      >
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase', flex: 1, textAlign: 'left' }}>
          Crash Report
        </span>
        <Icon.chev size={10} dir={open ? 'down' : 'right'} />
      </button>
      {open && (
        <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {data.error_type != null && (
            <div>
              <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 3 }}>Error</span>
              <span style={{ fontWeight: 600, color: 'var(--crash)', fontFamily: 'var(--mono)', fontSize: 12 }}>{String(data.error_type)}</span>
              {data.error_message != null && <span style={{ color: 'var(--ink-2)', fontFamily: 'var(--mono)', fontSize: 11, marginLeft: 8 }}>{String(data.error_message)}</span>}
            </div>
          )}
          {trace.length > 0 && (
            <div>
              <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 4 }}>Stack Trace</span>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 11, lineHeight: 1.6 }}>
                {trace.map((f, i) => (
                  <div key={i} style={{
                    padding: '2px 6px', borderRadius: 3,
                    background: f.highlight ? 'oklch(0.95 0.04 25 / 0.5)' : 'transparent',
                    color: f.highlight ? 'var(--crash)' : 'var(--ink-2)',
                  }}>
                    <span style={{ color: 'var(--ink-3)' }}>at </span>
                    <span style={{ fontWeight: f.highlight ? 600 : 400 }}>{f.fn}</span>
                    <span style={{ color: 'var(--ink-3)' }}> ({f.file}:{f.line})</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {data.summary != null && (
            <div>
              <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 3 }}>Summary</span>
              <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.6 }}>{String(data.summary)}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function parseToolCallsFromDetail(detail: ApiIncidentDetail): ToolCall[] {
  const calls: ToolCall[] = [];
  const pr = detail.pr_result;
  if (!pr) return calls;

  const agentOrder: AgentId[] = ['handler', 'qa', 'dev'];
  agentOrder.forEach(agent => {
    const agentData = (pr as Record<string, unknown>)[agent] as Record<string, unknown> | undefined;
    if (!agentData) return;
    const toolCalls = agentData.tool_calls as Array<Record<string, unknown>> | undefined;
    if (!toolCalls) return;
    toolCalls.forEach((tc, i) => {
      calls.push({
        id: `${agent}-${i}`,
        agent,
        tool: String(tc.tool || 'LLM'),
        input: String(tc.input || ''),
        output: tc.output ? String(tc.output) : undefined,
        ts: String(tc.ts || ''),
        durationMs: tc.duration_ms as number | undefined,
      });
    });
  });
  return calls;
}

function parseDiffFromDetail(detail: ApiIncidentDetail): DiffHunk[] {
  const pr = detail.pr_result as Record<string, unknown> | null;
  if (!pr) return [];
  const devData = pr.dev as Record<string, unknown> | undefined;
  if (!devData) return [];
  const diff = devData.diff as Array<Record<string, unknown>> | string | undefined;
  if (!diff) return [];
  if (typeof diff === 'string') {
    return [{ file: 'patch', lines: diff.split('\n').map(line => ({
      type: (line.startsWith('+') ? '+' : line.startsWith('-') ? '-' : ' ') as '+' | '-' | ' ',
      text: line.slice(1),
    })) }];
  }
  return (diff as Array<Record<string, unknown>>).map(d => ({
    file: String(d.file || 'unknown'),
    lines: (d.lines as Array<Record<string, unknown>> || []).map(l => ({
      type: String(l.type || ' ') as '+' | '-' | ' ',
      text: String(l.text || ''),
    })),
  }));
}

interface IncidentDetailPageProps {
  incident: Incident | null;
  onBack: () => void;
  showActivityRail: boolean;
  pipelineLayout: 'horizontal' | 'vertical';
}

export function IncidentDetailPage({ incident, onBack, showActivityRail, pipelineLayout }: IncidentDetailPageProps) {
  const { data: detail } = useIncident(incident?.id ?? null);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [activeTab, setActiveTab] = useState<'trace' | 'diff'>('trace');
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
    if (detail) {
      setToolCalls(parseToolCallsFromDetail(detail));
    }
  }, [detail]);

  if (!incident) {
    return (
      <div style={{ padding: 32, color: 'var(--ink-3)', fontFamily: 'var(--mono)', fontSize: 12 }}>
        incident not found
      </div>
    );
  }

  const stages = incidentToPipelineStages(incident.status);
  const diff = detail ? parseDiffFromDetail(detail) : [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 44px)' }}>
      {/* Header bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 20px', borderBottom: '1px solid var(--line)',
        flexShrink: 0, background: 'var(--bg)',
      }}>
        <Button variant="ghost" size="sm" onClick={onBack}>
          <Icon.chev dir="left" size={10} /> back
        </Button>
        <span style={{ width: 1, height: 16, background: 'var(--line-2)' }}/>
        <Badge tone="neutral">{incident.short}</Badge>
        <span style={{ fontWeight: 500, fontSize: 13, color: 'var(--ink)', flex: 1 }}>
          {incident.error}
        </span>
        <Severity level={incident.severity} />
        <StatusPill status={incident.status} />
      </div>

      {/* Body */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', minHeight: 0 }}>
        {/* Left panel */}
        <div style={{ width: showActivityRail ? 380 : '50%', flexShrink: 0, overflowY: 'auto', padding: '16px 20px', borderRight: '1px solid var(--line)' }}>
          {/* Pipeline */}
          <div style={{ marginBottom: 20 }}>
            <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'block', marginBottom: 10 }}>Pipeline</span>
            <Pipeline stages={stages} layout={pipelineLayout} />
          </div>

          {/* Crash report */}
          {detail?.crash_report && <CrashReport data={detail.crash_report} />}

          {/* Meta */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {incident.summary && (
              <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.6 }}>{incident.summary}</p>
            )}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {incident.component && <AgentChip id="handler" />}
              <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>{incident.createdAt}</span>
            </div>
          </div>
        </div>

        {/* Right panel - tool calls / diff */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
          {/* Tabs */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 0, padding: '0 16px', borderBottom: '1px solid var(--line)', flexShrink: 0 }}>
            {(['trace', 'diff'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className="mono"
                style={{
                  fontSize: 11, letterSpacing: '0.04em', padding: '10px 12px', border: 'none',
                  borderBottom: `2px solid ${activeTab === tab ? 'var(--accent)' : 'transparent'}`,
                  background: 'none', cursor: 'pointer',
                  color: activeTab === tab ? 'var(--ink)' : 'var(--ink-3)',
                  marginBottom: -1,
                }}
              >
                {tab === 'trace' ? 'agent trace' : 'pr diff'}
              </button>
            ))}
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: 16, minHeight: 0 }}>
            {activeTab === 'trace' && <ToolCallsList calls={toolCalls} />}
            {activeTab === 'diff' && <PRDiff hunks={diff} prUrl={incident.prUrl} />}
          </div>
        </div>

        {/* Activity rail */}
        {showActivityRail && (
          <div style={{ width: 300, flexShrink: 0, borderLeft: '1px solid var(--line)', padding: 12, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <ActivityRail events={events} title="live stream" />
          </div>
        )}
      </div>
    </div>
  );
}
