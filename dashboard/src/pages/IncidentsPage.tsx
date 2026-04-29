import { useState } from 'react';
import { Incident, AGENTS, AgentId } from '../constants';
import { Badge, StatusPill, Severity, Icon, Spark } from '../components/primitives';

type Filter = 'all' | 'review' | 'fixed' | 'failed';

interface FilterChipProps {
  label: string;
  active: boolean;
  count?: number;
  onClick: () => void;
}

function FilterChip({ label, active, count, onClick }: FilterChipProps) {
  return (
    <button onClick={onClick} className="mono" style={{
      fontSize: 10.5, letterSpacing: '0.04em',
      padding: '4px 8px', borderRadius: 4,
      background: active ? 'var(--ink)' : 'var(--bg-2)',
      border: `1px solid ${active ? 'var(--ink)' : 'var(--line-2)'}`,
      color: active ? 'var(--bg)' : 'var(--ink-2)',
      cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5,
    }}>
      {label}
      {count !== undefined && (
        <span style={{ opacity: 0.7, fontSize: 10 }}>{count}</span>
      )}
    </button>
  );
}

interface StatProps {
  label: string;
  value: string | number;
  color?: string;
  spark?: number[];
}

function Stat({ label, value, color, spark }: StatProps) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 4,
      padding: '12px 16px',
      background: 'var(--bg-2)',
      border: '1px solid var(--line)',
      borderRadius: 6,
      flex: 1,
    }}>
      <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
        {label}
      </span>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, justifyContent: 'space-between' }}>
        <span style={{ fontSize: 22, fontWeight: 600, color: color ?? 'var(--ink)', letterSpacing: '-0.02em', lineHeight: 1 }}>
          {value}
        </span>
        {spark && spark.length > 0 && <Spark points={spark} color={color ?? 'var(--ink-3)'} />}
      </div>
    </div>
  );
}

function agentsForStatus(status: string): AgentId[] {
  if (['analysing'].includes(status)) return ['handler'];
  if (['testing'].includes(status)) return ['handler', 'qa'];
  if (['fixing', 'pr'].includes(status)) return ['handler', 'qa', 'dev'];
  if (['approval', 'merged'].includes(status)) return ['handler', 'qa', 'dev', 'human'];
  return [];
}

interface MiniPipelineProps {
  status: string;
}

function MiniPipeline({ status }: MiniPipelineProps) {
  const agents = agentsForStatus(status);
  const allAgents: AgentId[] = ['handler', 'qa', 'dev', 'human'];
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
      {allAgents.map((id, i) => {
        const done = agents.includes(id);
        const color = AGENTS[id].color;
        return (
          <div key={id} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            <div style={{
              width: 8, height: 8, borderRadius: 2,
              background: done ? color : 'var(--bg-3)',
              border: `1px solid ${done ? color : 'var(--line-2)'}`,
            }}/>
            {i < allAgents.length - 1 && (
              <div style={{ width: 6, height: 1, background: done ? 'var(--line-2)' : 'var(--line)' }}/>
            )}
          </div>
        );
      })}
    </div>
  );
}

interface IncidentRowProps {
  inc: Incident;
  onClick: () => void;
}

function IncidentRow({ inc, onClick }: IncidentRowProps) {
  return (
    <div
      onClick={onClick}
      style={{
        display: 'grid',
        gridTemplateColumns: '20px 1fr 120px 110px 110px 90px',
        alignItems: 'center', gap: 12,
        padding: '9px 16px',
        borderBottom: '1px solid var(--line)',
        cursor: 'pointer',
        transition: 'background 100ms',
      }}
      onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-2)')}
      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
    >
      <Severity level={inc.severity} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 500, fontSize: 12.5, color: 'var(--ink)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {inc.error}
        </div>
        <div className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {inc.message || inc.component}
        </div>
      </div>
      <MiniPipeline status={inc.status} />
      <StatusPill status={inc.status} />
      <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>{inc.createdAt}</span>
      <Badge tone="neutral">{inc.short}</Badge>
    </div>
  );
}

interface IncidentsPageProps {
  incidents: Incident[];
  loading: boolean;
  onOpen: (id: string) => void;
}

export function IncidentsPage({ incidents, loading, onOpen }: IncidentsPageProps) {
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');

  const needsReview = incidents.filter(i => i.status === 'approval').length;
  const autoFixed   = incidents.filter(i => ['pr', 'merged'].includes(i.status)).length;
  const failed      = incidents.filter(i => i.status === 'failed').length;

  const filtered = incidents.filter(inc => {
    if (filter === 'review' && inc.status !== 'approval') return false;
    if (filter === 'fixed'  && !['pr', 'merged'].includes(inc.status)) return false;
    if (filter === 'failed' && inc.status !== 'failed') return false;
    if (search && !inc.error.toLowerCase().includes(search.toLowerCase()) &&
        !inc.message.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div style={{ padding: '20px 24px', maxWidth: 1100, margin: '0 auto' }}>
      {/* Stats row */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <Stat label="Total"         value={incidents.length} />
        <Stat label="Auto-fixed"    value={autoFixed}   color="var(--ok)" />
        <Stat label="Needs review"  value={needsReview} color="var(--warn)" />
        <Stat label="Failed"        value={failed}      color="var(--crash)" />
      </div>

      {/* Filters + search */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <FilterChip label="all"          active={filter === 'all'}    count={incidents.length} onClick={() => setFilter('all')} />
        <FilterChip label="needs review" active={filter === 'review'} count={needsReview}      onClick={() => setFilter('review')} />
        <FilterChip label="auto-fixed"   active={filter === 'fixed'}  count={autoFixed}        onClick={() => setFilter('fixed')} />
        <FilterChip label="failed"       active={filter === 'failed'} count={failed}           onClick={() => setFilter('failed')} />
        <div style={{ flex: 1 }}/>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', border: '1px solid var(--line-2)', borderRadius: 4, background: 'var(--bg-2)' }}>
          <Icon.search size={11} />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="search errors…"
            style={{
              font: 'inherit', fontFamily: 'var(--mono)', fontSize: 11,
              background: 'none', border: 'none', outline: 'none',
              color: 'var(--ink)', width: 160,
            }}
          />
        </div>
      </div>

      {/* Table */}
      <div style={{ border: '1px solid var(--line)', borderRadius: 6, overflow: 'hidden' }}>
        {/* Table header */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '20px 1fr 120px 110px 110px 90px',
          gap: 12, padding: '7px 16px',
          background: 'var(--bg-2)', borderBottom: '1px solid var(--line)',
        }}>
          {['', 'error', 'pipeline', 'status', 'time', 'id'].map(h => (
            <span key={h} className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              {h}
            </span>
          ))}
        </div>

        {loading ? (
          <div style={{ padding: '40px 16px', textAlign: 'center', color: 'var(--ink-3)' }} className="mono">
            loading…
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: '40px 16px', textAlign: 'center', color: 'var(--ink-3)' }} className="mono">
            {incidents.length === 0 ? 'no incidents yet — send a crash to get started' : 'no matches'}
          </div>
        ) : (
          filtered.map(inc => (
            <IncidentRow key={inc.id} inc={inc} onClick={() => onOpen(inc.id)} />
          ))
        )}
      </div>
    </div>
  );
}

