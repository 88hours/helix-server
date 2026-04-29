import { AGENTS, AgentId } from '../constants';
import { Badge, Button, Icon } from '../components/primitives';

interface AgentMeta {
  id: AgentId;
  role: string;
  tagline: string;
  desc: string;
  tools: string[];
  stats: Record<string, string>;
}

const AGENT_META: AgentMeta[] = [
  {
    id: 'handler',
    role: 'Crash Handler',
    tagline: 'First to see every crash.',
    desc: 'Receives webhooks from Sentry / Rollbar, dedupes against open incidents, scores severity and decides whether to spin up a fix or escalate.',
    tools: ['Sentry', 'Rollbar', 'GitHub', 'LLM'],
    stats: { handled: '—', dedupe: '—', median: '—' },
  },
  {
    id: 'qa',
    role: 'QA Agent',
    tagline: 'Writes the failing test first.',
    desc: 'Reproduces the crash in a unit or integration test before any code changes happen. The dev agent only runs once QA has a red test in hand.',
    tools: ['Git', 'Claude'],
    stats: { handled: '—', repro: '—', median: '—' },
  },
  {
    id: 'dev',
    role: 'Dev Agent',
    tagline: 'Makes the test pass.',
    desc: 'Iterates on a minimal patch until the QA test goes green and existing tests still pass. Caps out at the configured max-iterations and max-files budget.',
    tools: ['Git', 'GitHub', 'Claude'],
    stats: { handled: '—', merged: '—', median: '—' },
  },
  {
    id: 'human',
    role: 'Human reviewer',
    tagline: 'The last call.',
    desc: 'You. Approves PRs the agents have prepared, or takes over when the dev agent escalates because confidence is low or the patch is too broad.',
    tools: [],
    stats: { reviewed: '—', approved: '—', median: '—' },
  },
];

function AgentCard({ a }: { a: AgentMeta }) {
  const meta = AGENTS[a.id];
  const isHuman = a.id === 'human';
  return (
    <section style={{
      border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg)',
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 16px', borderBottom: '1px solid var(--line)',
        display: 'flex', alignItems: 'center', gap: 12,
        background: `linear-gradient(180deg, color-mix(in oklch, ${meta.color} 6%, var(--bg-2)), var(--bg-2))`,
      }}>
        <span style={{
          width: 36, height: 36, borderRadius: 6,
          background: `color-mix(in oklch, ${meta.color} 14%, transparent)`,
          border: `1px solid color-mix(in oklch, ${meta.color} 35%, transparent)`,
          color: meta.color,
          fontFamily: 'var(--mono)', fontSize: 18, fontWeight: 600,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}>
          {meta.symbol}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--ink)' }}>{a.role}</div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>agent.{a.id}</div>
        </div>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            width: 7, height: 7, borderRadius: '50%',
            background: isHuman ? 'var(--ink-3)' : 'var(--ok)',
            animation: isHuman ? 'none' : 'pulse-dot 1.8s ease-in-out infinite',
          }} />
          <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>
            {isHuman ? 'on call' : 'online'}
          </span>
        </span>
      </div>

      {/* Body */}
      <div style={{ padding: '14px 16px' }}>
        <p style={{ margin: 0, fontFamily: 'var(--serif)', fontSize: 18, lineHeight: 1.25, color: 'var(--ink)' }}>
          {a.tagline}
        </p>
        <p style={{ margin: '8px 0 0', fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.6 }}>
          {a.desc}
        </p>

        <div style={{ display: 'flex', gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
          {a.tools.length === 0
            ? <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>uses no tools — that's the point</span>
            : a.tools.map(t => <Badge key={t} tone="neutral">{t}</Badge>)
          }
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${Object.keys(a.stats).length}, 1fr)`,
          gap: 12, marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--line)',
        }}>
          {Object.entries(a.stats).map(([k, v]) => (
            <div key={k}>
              <div className="mono" style={{ fontSize: 16, color: 'var(--ink)', fontWeight: 500, letterSpacing: '-0.02em' }}>{v}</div>
              <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.06em', marginTop: 2 }}>{k}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function AgentsPage() {
  return (
    <div style={{ padding: '22px 28px 60px', maxWidth: 1400, margin: '0 auto' }}>

      {/* Hero header */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'minmax(0, 1.3fr) minmax(0, 1fr)',
        alignItems: 'end', gap: 32, marginBottom: 22,
      }}>
        <div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>
            Agents · 3 online · 1 human
          </div>
          <h1 style={{ margin: 0, fontFamily: 'var(--serif)', fontWeight: 400, fontSize: 'clamp(28px, 3.4vw, 42px)', lineHeight: 1.05, letterSpacing: '-0.02em' }}>
            Four roles, <span style={{ color: 'var(--ink-3)' }}>one</span> pipeline.
          </h1>
          <p style={{ margin: '10px 0 0', maxWidth: 540, fontSize: 13.5, color: 'var(--ink-2)', lineHeight: 1.6 }}>
            Helix splits the fix loop into specialists so each one can be tuned, rate-limited and audited
            independently.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Button variant="ghost" size="sm"><Icon.refresh size={11} /> refresh</Button>
          <Button variant="ghost" size="sm">view audit log</Button>
        </div>
      </div>

      {/* 2-col agent cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 14 }}>
        {AGENT_META.map(a => <AgentCard key={a.id} a={a} />)}
      </div>
    </div>
  );
}
