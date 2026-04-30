import { useState } from 'react';
import { Incident, AGENTS, AgentId } from '../constants';
import { StatusPill, Icon, Button } from '../components/primitives';

type Filter = 'all' | 'active' | 'pr' | 'approval' | 'merged' | 'duplicate' | 'failed';
type SevFilter = 'any' | 'high' | 'medium' | 'low';

function FilterChip({ active, children, count, onClick }: {
  active: boolean; children: React.ReactNode; count?: number; onClick: () => void;
}) {
  return (
    <button onClick={onClick} style={{
      fontFamily: 'var(--mono)', fontSize: 11.5,
      padding: '4px 9px', borderRadius: 4,
      color: active ? 'var(--ink)' : 'var(--ink-2)',
      background: active ? 'var(--bg)' : 'transparent',
      border: active ? '1px solid var(--line-2)' : '1px solid transparent',
      boxShadow: active ? '0 1px 0 oklch(0.22 0.01 260 / 0.03)' : 'none',
      display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer',
    }}>
      {children}
      {count != null && <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{count}</span>}
    </button>
  );
}

function StatCard({ value, label, accent, small }: { value: string; label: string; accent?: string; small?: boolean }) {
  return (
    <div style={{ padding: '10px 12px', border: '1px solid var(--line)', borderRadius: 8, background: 'var(--bg-2)', minWidth: 0 }}>
      <div className="mono" style={{
        fontSize: small ? 18 : 24, color: accent ?? 'var(--ink)',
        lineHeight: 1, letterSpacing: '-0.02em', fontWeight: 500, whiteSpace: 'nowrap',
      }}>
        {value}
      </div>
      <div style={{ marginTop: 6 }}>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.06em' }}>{label}</span>
      </div>
    </div>
  );
}

function agentsForStatus(status: string): AgentId[] {
  if (status === 'duplicate' || status === 'failed') return ['handler'];
  if (status === 'analysing') return ['handler'];
  if (status === 'testing') return ['handler', 'qa'];
  return ['handler', 'qa', 'dev'];
}

function AgentChips({ status }: { status: string }) {
  const agents = agentsForStatus(status);
  return (
    <div style={{ display: 'flex', gap: 4 }}>
      {agents.map(a => (
        <span key={a} title={AGENTS[a].name} style={{
          width: 20, height: 20, borderRadius: 3,
          background: `color-mix(in oklch, ${AGENTS[a].color} 14%, transparent)`,
          border: `1px solid color-mix(in oklch, ${AGENTS[a].color} 35%, transparent)`,
          color: AGENTS[a].color,
          fontFamily: 'var(--mono)', fontSize: 10, fontWeight: 700,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }}>
          {AGENTS[a].short.slice(0, 2)}
        </span>
      ))}
    </div>
  );
}

const STATUS_AGENT_IDX: Record<string, number> = {
  analysing: 0, testing: 1, fixing: 2, pr: 2, approval: 3, merged: 4,
};

function MiniPipeline({ inc }: { inc: Incident }) {
  if (inc.status === 'duplicate') {
    return (
      <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>
        ↳ dup of <span style={{ color: 'var(--accent)' }}>{inc.duplicateOf ?? '—'}</span>
      </div>
    );
  }
  if (inc.status === 'failed') {
    return (
      <div className="mono" style={{ fontSize: 11, color: 'var(--crash)' }}>
        {inc.note ?? 'escalated'}
      </div>
    );
  }
  const agents: AgentId[] = ['handler', 'qa', 'dev', 'human'];
  const activeIdx = STATUS_AGENT_IDX[inc.status] ?? -1;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      {agents.map((a, i) => {
        const done = i < activeIdx;
        const active = i === activeIdx;
        const color = AGENTS[a].color;
        return (
          <span key={a} style={{
            flex: 1, height: 5, borderRadius: 3,
            background: (done || active) ? color : 'var(--line-2)',
            opacity: active ? 0.7 : 1,
          }} />
        );
      })}
    </div>
  );
}

function IncidentRow({ inc, onClick }: { inc: Incident; onClick: () => void }) {
  return (
    <div onClick={onClick} style={{
      display: 'grid',
      gridTemplateColumns: '150px 1fr 180px 140px 110px 120px',
      gap: 16, padding: '14px 16px',
      borderTop: '1px solid var(--line)',
      alignItems: 'center', cursor: 'pointer',
      transition: 'background 120ms',
    }}
      onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-2)')}
      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span className="mono" style={{ fontSize: 11.5, color: 'var(--accent)' }}>{inc.short}</span>
        <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>{inc.component}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
        <span className="mono" style={{ fontSize: 13, color: 'var(--ink)', fontWeight: 500 }}>{inc.error}</span>
        <span style={{ fontSize: 11.5, color: 'var(--ink-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {inc.message}
        </span>
      </div>
      <MiniPipeline inc={inc} />
      <AgentChips status={inc.status} />
      <StatusPill status={inc.status} />
      <div style={{ textAlign: 'right', display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span className="mono" style={{ fontSize: 11.5, color: 'var(--ink-2)' }}>{inc.createdAt}</span>
        {(inc.occurrences > 0 || inc.users > 0) && (
          <span style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>
            {inc.occurrences}× · {inc.users} user{inc.users !== 1 ? 's' : ''}
          </span>
        )}
      </div>
    </div>
  );
}

interface IncidentsPageProps {
  incidents: Incident[];
  loading: boolean;
  onOpen: (id: string) => void;
  onRefresh: () => void;
}

export function IncidentsPage({ incidents, loading, onOpen, onRefresh }: IncidentsPageProps) {
  const [filter, setFilter] = useState<Filter>('all');
  const [severity, setSeverity] = useState<SevFilter>('any');

  const counts: Record<string, number> = {
    all:       incidents.length,
    active:    incidents.filter(i => !['merged', 'duplicate', 'failed'].includes(i.status)).length,
    pr:        incidents.filter(i => i.status === 'pr').length,
    approval:  incidents.filter(i => i.status === 'approval').length,
    merged:    incidents.filter(i => i.status === 'merged').length,
    duplicate: incidents.filter(i => i.status === 'duplicate').length,
    failed:    incidents.filter(i => i.status === 'failed').length,
  };

  const prs = incidents.filter(i => ['pr', 'merged'].includes(i.status)).length;
  const needsReview = counts.approval;

  const filtered = incidents.filter(inc => {
    if (filter === 'active' && ['merged', 'duplicate', 'failed'].includes(inc.status)) return false;
    if (filter !== 'all' && filter !== 'active' && inc.status !== filter) return false;
    if (severity !== 'any' && inc.severity !== severity) return false;
    return true;
  });

  return (
    <div style={{ padding: '22px 28px 60px', maxWidth: 1400, margin: '0 auto' }}>

      {/* Hero block */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'minmax(0, 1.3fr) minmax(0, 1fr)',
        alignItems: 'end', gap: 32, marginBottom: 26,
      }}>
        <div style={{ minWidth: 0 }}>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>
            Incidents · last 7 days
          </div>
          {loading ? (
            <h1 style={{ margin: 0, fontFamily: 'var(--serif)', fontWeight: 400, fontSize: 'clamp(28px, 3.6vw, 46px)', lineHeight: 1.05, letterSpacing: '-0.02em', color: 'var(--ink-3)' }}>
              Loading…
            </h1>
          ) : incidents.length === 0 ? (
            <h1 style={{ margin: 0, fontFamily: 'var(--serif)', fontWeight: 400, fontSize: 'clamp(28px, 3.6vw, 46px)', lineHeight: 1.05, letterSpacing: '-0.02em' }}>
              No incidents yet.
              <span style={{ color: 'var(--ink-3)' }}> Send a crash to get started.</span>
            </h1>
          ) : (
            <h1 style={{ margin: 0, fontFamily: 'var(--serif)', fontWeight: 400, fontSize: 'clamp(28px, 3.6vw, 46px)', lineHeight: 1.05, letterSpacing: '-0.02em' }}>
              <span style={{ color: 'var(--ok)' }}>{incidents.length} crash{incidents.length !== 1 ? 'es' : ''}</span>
              <span style={{ color: 'var(--ink-3)' }}> became </span>
              <span style={{ color: 'var(--ok)' }}>{prs} pull request{prs !== 1 ? 's' : ''}</span>.
              {needsReview > 0 && (
                <><br /><span style={{ color: 'var(--ink-3)' }}>{needsReview} need{needsReview !== 1 ? '' : 's'} your review.</span></>
              )}
            </h1>
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 10, minWidth: 0 }}>
          <StatCard value={String(incidents.length)} label="incidents" />
          <StatCard value={String(prs)} label="PRs" accent="var(--ok)" />
          <StatCard value={String(counts.merged)} label="merged" accent="var(--ok)" />
          <StatCard value="—" label="median fix" small />
        </div>
      </div>

      {/* Filter bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '8px 10px', border: '1px solid var(--line)',
        borderRadius: 8, background: 'var(--bg-2)', marginBottom: 14,
      }}>
        <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginRight: 6 }}>filter</span>
        {(['all', 'active', 'pr', 'approval', 'merged', 'duplicate', 'failed'] as Filter[]).map(k => (
          <FilterChip key={k} active={filter === k} onClick={() => setFilter(k)} count={counts[k]}>
            {k}
          </FilterChip>
        ))}
        <span style={{ width: 1, height: 18, background: 'var(--line-2)', margin: '0 8px' }} />
        <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>severity</span>
        {(['any', 'high', 'medium', 'low'] as SevFilter[]).map(k => (
          <FilterChip key={k} active={severity === k} onClick={() => setSeverity(k)}>
            {k}
          </FilterChip>
        ))}
        <span style={{ flex: 1 }} />
        <Button variant="ghost" size="sm" onClick={onRefresh}><Icon.refresh size={11} /> refresh</Button>
        <Button variant="subtle" size="sm">newest ↓</Button>
      </div>

      {/* Table */}
      <div style={{ border: '1px solid var(--line)', borderRadius: 8, background: 'var(--bg)', overflow: 'hidden' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '150px 1fr 180px 140px 110px 120px',
          gap: 16, padding: '10px 16px',
          background: 'var(--bg-2)', borderBottom: '1px solid var(--line)',
          fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ink-3)',
          letterSpacing: '0.1em', textTransform: 'uppercase',
        }}>
          <span>Incident</span>
          <span>Error</span>
          <span>Pipeline</span>
          <span>Agents</span>
          <span>Status</span>
          <span style={{ textAlign: 'right' }}>Opened</span>
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
          filtered.map(inc => <IncidentRow key={inc.id} inc={inc} onClick={() => onOpen(inc.id)} />)
        )}
      </div>
    </div>
  );
}
