import { AGENTS, AgentId } from '../constants';
import { AgentChip, Icon } from './primitives';

export interface PipelineStage {
  agent: AgentId;
  status: 'pending' | 'active' | 'done' | 'failed';
  label: string;
  detail?: string;
  ts?: string;
  dur?: string;
}

function LiveDot() {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <span style={{
        width: 7, height: 7, borderRadius: '50%', background: 'var(--ok)',
        animation: 'pulse-dot 1.6s ease-in-out infinite',
      }} />
      <span className="mono" style={{ fontSize: 10, color: 'var(--ok)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>live</span>
    </span>
  );
}

function PipelineHeader({ hasActive }: { hasActive: boolean }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '10px 14px', borderBottom: '1px solid var(--line)',
      background: 'var(--bg)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
          Pipeline
        </span>
        <span style={{ width: 3, height: 3, borderRadius: '50%', background: 'var(--ink-3)' }} />
        <span className="mono" style={{ fontSize: 11, color: 'var(--ink-2)' }}>
          crash → test → fix → pr → approval
        </span>
      </div>
      {hasActive && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <LiveDot />
        </div>
      )}
    </div>
  );
}

interface StageNodeProps {
  stage: PipelineStage;
  col: number;
}

function StageNode({ stage, col }: StageNodeProps) {
  const agent = AGENTS[stage.agent];
  const c = agent.color;
  const state = stage.status === 'done' ? 'done' : stage.status === 'active' ? 'active' : 'pending';

  return (
    <div style={{
      gridColumn: col, position: 'relative', display: 'flex', flexDirection: 'column',
      alignItems: 'flex-start', gap: 3, padding: '0 6px',
    }}>
      <div style={{
        width: 28, height: 28, borderRadius: 6,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        background: state === 'pending' ? 'var(--bg-2)' : `color-mix(in oklch, ${c} 14%, transparent)`,
        border: `1.5px solid ${state === 'pending' ? 'var(--line-2)' : c}`,
        color: state === 'pending' ? 'var(--ink-3)' : c,
        fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 700,
        boxShadow: state === 'active' ? `0 0 0 6px color-mix(in oklch, ${c} 12%, transparent)` : 'none',
        animation: state === 'active' ? 'pulse-dot 1.8s ease-in-out infinite' : 'none',
      }}>
        {state === 'done' ? <Icon.check size={13} /> : col - 1}
      </div>
      <div style={{ marginTop: 2 }}>
        <div className="mono" style={{ fontSize: 11, color: state === 'pending' ? 'var(--ink-3)' : 'var(--ink)', fontWeight: 600 }}>
          {stage.label}
        </div>
        {stage.detail && (
          <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 1 }}>
            {stage.detail}{stage.dur ? ` · ${stage.dur}` : ''}
          </div>
        )}
      </div>
    </div>
  );
}

const AGENTS_ORDER: AgentId[] = ['handler', 'qa', 'dev', 'human'];

interface FlowDivsProps {
  stages: PipelineStage[];
  cols: number;
}

function FlowDivs({ stages, cols }: FlowDivsProps) {
  const LANE_H = 64;
  const laneIndex = (id: AgentId) => AGENTS_ORDER.indexOf(id);

  return (
    <foreignObject x="0" y="0" width="100%" height={LANE_H * AGENTS_ORDER.length} style={{ overflow: 'visible' }}>
      <div style={{ position: 'relative', width: '100%', height: LANE_H * AGENTS_ORDER.length }}>
        {stages.slice(0, -1).map((s, i) => {
          const next = stages[i + 1];
          const y1 = laneIndex(s.agent) * LANE_H + 14;
          const y2 = laneIndex(next.agent) * LANE_H + 14;
          const isDone = s.status === 'done';
          const isActive = s.status === 'active';
          const color = isDone
            ? 'var(--ink-3)'
            : isActive
              ? AGENTS[next.agent].color
              : 'var(--line-2)';
          const dashed = s.status === 'pending';
          const leftPct = `calc(120px + ${i + 0.5} * ((100% - 120px) / ${cols}))`;
          const widthPct = `calc((100% - 120px) / ${cols})`;
          const top = Math.min(y1, y2);
          const h = Math.abs(y2 - y1);

          if (y1 === y2) {
            return (
              <div key={i} style={{
                position: 'absolute', left: leftPct, width: widthPct, top: y1,
                height: 0, borderTop: `1.5px ${dashed ? 'dashed' : 'solid'} ${color}`,
              }} />
            );
          }
          const midLeft = `calc(120px + ${i + 0.95} * ((100% - 120px) / ${cols}))`;
          return (
            <div key={i}>
              <div style={{
                position: 'absolute', left: leftPct, top: y1,
                width: `calc(0.45 * ((100% - 120px) / ${cols}))`, height: 0,
                borderTop: `1.5px ${dashed ? 'dashed' : 'solid'} ${color}`,
              }} />
              <div style={{
                position: 'absolute', left: midLeft, top, height: h, width: 0,
                borderLeft: `1.5px ${dashed ? 'dashed' : 'solid'} ${color}`,
              }} />
              <div style={{
                position: 'absolute', left: midLeft, top: y2,
                width: `calc(0.55 * ((100% - 120px) / ${cols}))`, height: 0,
                borderTop: `1.5px ${dashed ? 'dashed' : 'solid'} ${color}`,
              }} />
            </div>
          );
        })}
      </div>
    </foreignObject>
  );
}

function FlowConnectors({ stages }: { stages: PipelineStage[] }) {
  const LANE_H = 64;
  return (
    <svg
      aria-hidden
      style={{
        position: 'absolute', inset: 0, width: '100%',
        height: `${LANE_H * AGENTS_ORDER.length}px`, pointerEvents: 'none', overflow: 'visible',
      }}
    >
      <FlowDivs stages={stages} cols={stages.length} />
    </svg>
  );
}

function Lanes({ stages }: { stages: PipelineStage[] }) {
  const COLS = stages.length;

  return (
    <div style={{ position: 'relative' }}>
      {/* Column headers */}
      <div style={{
        display: 'grid', gridTemplateColumns: `120px repeat(${COLS}, 1fr)`,
        marginBottom: 10,
      }}>
        <div />
        {stages.map((s, i) => (
          <div key={i} style={{ padding: '0 6px' }}>
            <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.06em' }}>
              {String(i + 1).padStart(2, '0')}{s.ts ? ` · ${s.ts}` : ''}
            </div>
          </div>
        ))}
      </div>

      {AGENTS_ORDER.map(agentId => {
        const a = AGENTS[agentId];
        const laneStages = stages
          .map((s, i) => ({ ...s, i }))
          .filter(s => s.agent === agentId);

        return (
          <div key={agentId} style={{
            display: 'grid', gridTemplateColumns: `120px repeat(${COLS}, 1fr)`,
            alignItems: 'center', position: 'relative', height: 64,
          }}>
            <div style={{
              display: 'flex', flexDirection: 'column', gap: 2,
              borderRight: '1px dashed var(--line-2)',
              paddingRight: 10, height: '100%', justifyContent: 'center',
            }}>
              <AgentChip id={agentId} size="md" />
              <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>{a.name}</span>
            </div>

            {/* Lane track */}
            <div style={{
              gridColumn: `2 / span ${COLS}`, gridRow: 1,
              height: 1, background: 'var(--line)',
              alignSelf: 'center', marginLeft: 6, marginRight: 6,
            }} />

            {laneStages.map(s => (
              <StageNode key={s.i} stage={s} col={s.i + 2} />
            ))}
          </div>
        );
      })}

      <FlowConnectors stages={stages} />
    </div>
  );
}

function HorizontalRow({ stages }: { stages: PipelineStage[] }) {
  return (
    <div style={{ display: 'flex', alignItems: 'stretch', gap: 0, position: 'relative', padding: '6px 0' }}>
      {stages.map((s, i) => {
        const a = AGENTS[s.agent];
        const isActive = s.status === 'active';
        const isDone = s.status === 'done';
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{
              flex: 1, display: 'flex', flexDirection: 'column', gap: 8,
              padding: '12px 14px',
              border: `1px solid ${isActive ? a.color : 'var(--line)'}`,
              borderRadius: 6,
              background: isActive
                ? `color-mix(in oklch, ${a.color} 8%, var(--bg))`
                : isDone ? 'var(--bg)' : 'var(--bg-2)',
              opacity: isDone || isActive ? 1 : 0.7,
              minWidth: 120,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  width: 22, height: 22, borderRadius: 4,
                  background: `color-mix(in oklch, ${a.color} 14%, transparent)`,
                  border: `1px solid color-mix(in oklch, ${a.color} 35%, transparent)`,
                  color: a.color, fontFamily: 'var(--mono)', fontSize: 12, fontWeight: 600,
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                }}>{a.symbol}</span>
                <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{a.short}</span>
                <span style={{ flex: 1 }} />
                {isActive && <LiveDot />}
              </div>
              <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)' }}>{s.label}</div>
              {s.detail && (
                <div style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{s.detail}</div>
              )}
              {(s.ts || s.dur) && (
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 'auto' }}>
                  <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>{s.ts ?? '—'}</span>
                  <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>{s.dur ?? ''}</span>
                </div>
              )}
            </div>
            {i < stages.length - 1 && (
              <div style={{ width: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', color: isDone ? 'var(--ok)' : 'var(--ink-3)', flexShrink: 0 }}>
                →
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

interface PipelineProps {
  stages: PipelineStage[];
  layout?: 'horizontal' | 'swimlane';
}

export function Pipeline({ stages, layout = 'horizontal' }: PipelineProps) {
  const hasActive = stages.some(s => s.status === 'active');
  return (
    <section style={{
      background: 'var(--bg-2)', border: '1px solid var(--line)',
      borderRadius: 8, overflow: 'hidden',
    }}>
      <PipelineHeader hasActive={hasActive} />
      <div style={{ position: 'relative', padding: '18px 22px 22px' }}>
        {layout === 'swimlane'
          ? <Lanes stages={stages} />
          : <HorizontalRow stages={stages} />}
      </div>
    </section>
  );
}

const STAGE_LABELS: Record<AgentId, { label: string; detail: string }> = {
  handler: { label: 'Analyse crash',  detail: 'fingerprint + dedupe' },
  qa:      { label: 'Generate test',  detail: 'reproduces failure' },
  dev:     { label: 'Author fix',     detail: 'TDD iterate' },
  human:   { label: 'Approve',        detail: 'waiting' },
};

export function incidentToPipelineStages(status: string): PipelineStage[] {
  const order: AgentId[] = ['handler', 'qa', 'dev', 'human'];
  const activeMap: Record<string, AgentId> = {
    analysing: 'handler',
    testing:   'qa',
    fixing:    'dev',
    pr:        'dev',
    approval:  'human',
    merged:    'human',
  };
  const activeAgent = activeMap[status] ?? null;
  const activeIdx = activeAgent ? order.indexOf(activeAgent) : -1;

  return order.map((agent, i) => {
    let stageStatus: PipelineStage['status'];
    if (status === 'failed') {
      stageStatus = i <= activeIdx ? 'failed' : 'pending';
    } else if (status === 'merged' || status === 'pr') {
      stageStatus = i < order.length - 1 ? 'done' : status === 'merged' ? 'done' : 'pending';
    } else {
      if (i < activeIdx)        stageStatus = 'done';
      else if (i === activeIdx) stageStatus = 'active';
      else                      stageStatus = 'pending';
    }
    return { agent, status: stageStatus, ...STAGE_LABELS[agent] };
  });
}
