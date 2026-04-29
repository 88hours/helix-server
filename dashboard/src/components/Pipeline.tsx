import { AGENTS, AgentId } from '../constants';
import { AgentChip } from './primitives';

export interface PipelineStage {
  agent: AgentId;
  status: 'pending' | 'active' | 'done' | 'failed';
  duration?: string;
}

interface StageNodeProps {
  stage: PipelineStage;
  isActive: boolean;
}

function StageNode({ stage, isActive }: StageNodeProps) {
  const agent = AGENTS[stage.agent];
  const statusColor =
    stage.status === 'done'   ? 'var(--ok)'    :
    stage.status === 'failed' ? 'var(--crash)'  :
    isActive                  ? agent.color     : 'var(--ink-3)';
  const statusLabel =
    stage.status === 'active'  ? '● running' :
    stage.status === 'done'    ? '✓  done'   :
    stage.status === 'failed'  ? '✗  failed' : '○  pending';
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
      padding: '10px 14px', borderRadius: 6,
      border: `1px solid ${isActive ? `color-mix(in oklch, ${agent.color} 40%, transparent)` : 'var(--line-2)'}`,
      background: isActive ? `color-mix(in oklch, ${agent.color} 6%, var(--bg))` : 'var(--bg-2)',
      minWidth: 88, transition: 'all 200ms',
    }}>
      <AgentChip id={stage.agent} size="md" />
      <span className="mono" style={{ fontSize: 10, color: statusColor, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
        {statusLabel}
      </span>
      {stage.duration && (
        <span className="mono" style={{ fontSize: 9.5, color: 'var(--ink-3)' }}>{stage.duration}</span>
      )}
    </div>
  );
}

interface ConnectorProps { horizontal: boolean }

function Connector({ horizontal }: ConnectorProps) {
  return (
    <div style={{
      width: horizontal ? 24 : 2,
      height: horizontal ? 2 : 20,
      background: 'var(--line-2)',
      margin: horizontal ? '0 2px' : '2px auto',
      flexShrink: 0,
    }}/>
  );
}

interface PipelineProps {
  stages: PipelineStage[];
  layout?: 'horizontal' | 'vertical';
}

export function Pipeline({ stages, layout = 'horizontal' }: PipelineProps) {
  const horiz = layout === 'horizontal';
  return (
    <div style={{
      display: 'flex',
      flexDirection: horiz ? 'row' : 'column',
      alignItems: 'center',
    }}>
      {stages.map((stage, i) => (
        <div key={stage.agent} style={{ display: 'flex', alignItems: 'center', flexDirection: horiz ? 'row' : 'column' }}>
          <StageNode stage={stage} isActive={stage.status === 'active'} />
          {i < stages.length - 1 && <Connector horizontal={horiz} />}
        </div>
      ))}
    </div>
  );
}

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
      if (i < activeIdx)       stageStatus = 'done';
      else if (i === activeIdx) stageStatus = 'active';
      else                      stageStatus = 'pending';
    }
    return { agent, status: stageStatus };
  });
}
