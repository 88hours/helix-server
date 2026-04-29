import { AGENTS, AgentId } from '../constants';
import { AgentChip, Badge } from '../components/primitives';

interface AgentCapability {
  label: string;
  desc: string;
}

const AGENT_DETAILS: Record<AgentId, { capabilities: AgentCapability[]; defaultModel: string; trigger: string }> = {
  handler: {
    trigger: 'Incoming webhook (Sentry / Rollbar / custom)',
    defaultModel: 'claude-sonnet-4-6',
    capabilities: [
      { label: 'Crash analysis',     desc: 'Parses stack traces, extracts root cause, assesses severity.' },
      { label: 'Deduplication',      desc: 'Detects if the crash is a known issue and skips duplicate work.' },
      { label: 'Context enrichment', desc: 'Fetches recent commits, related issues, and affected component info.' },
      { label: 'Routing',            desc: 'Publishes crash_analysed event to trigger the QA Agent.' },
    ],
  },
  qa: {
    trigger: 'crash_analysed event from Crash Handler',
    defaultModel: 'claude-sonnet-4-6',
    capabilities: [
      { label: 'Test generation', desc: 'Writes a failing test that reproduces the crash.' },
      { label: 'Hypothesis',      desc: 'Proposes the likely fix strategy based on the crash context.' },
      { label: 'Coverage check',  desc: 'Verifies the new test actually fails on main before handoff.' },
    ],
  },
  dev: {
    trigger: 'test_case_generated event from QA Agent',
    defaultModel: 'claude-code (CLI)',
    capabilities: [
      { label: 'Fix implementation', desc: 'Writes the minimum code change to make the failing test pass.' },
      { label: 'Regression check',   desc: 'Runs the full test suite to confirm no regressions.' },
      { label: 'Retry logic',        desc: 'Retries up to 3 times; escalates to human on repeated failure.' },
      { label: 'PR creation',        desc: 'Opens a GitHub PR with fix, test, and plain-English description.' },
    ],
  },
  human: {
    trigger: 'pr_created event from Dev Agent',
    defaultModel: 'n/a',
    capabilities: [
      { label: 'Slack notification', desc: 'Approval request sent to the configured Slack channel.' },
      { label: 'PR review',          desc: 'Human approves or requests changes directly on GitHub.' },
      { label: 'Email fallback',     desc: 'Email notification if Slack is not configured.' },
    ],
  },
};

interface AgentDetailCardProps {
  id: AgentId;
}

function AgentDetailCard({ id }: AgentDetailCardProps) {
  const agent = AGENTS[id];
  const details = AGENT_DETAILS[id];
  return (
    <div style={{
      border: `1px solid color-mix(in oklch, ${agent.color} 25%, var(--line-2))`,
      borderRadius: 8, overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 16px',
        background: `color-mix(in oklch, ${agent.color} 6%, var(--bg-2))`,
        borderBottom: '1px solid var(--line)',
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <AgentChip id={id} size="md" />
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--ink)' }}>{agent.name}</div>
          <div className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', marginTop: 2 }}>
            {details.trigger}
          </div>
        </div>
        <Badge tone="neutral">{details.defaultModel}</Badge>
      </div>

      {/* Capabilities */}
      <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {details.capabilities.map(c => (
          <div key={c.label} style={{ display: 'flex', gap: 10 }}>
            <div style={{
              width: 6, height: 6, borderRadius: '50%',
              background: agent.color, flexShrink: 0, marginTop: 6,
            }}/>
            <div>
              <div style={{ fontWeight: 500, fontSize: 12.5, color: 'var(--ink)', marginBottom: 1 }}>{c.label}</div>
              <div style={{ fontSize: 12, color: 'var(--ink-3)', lineHeight: 1.5 }}>{c.desc}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AgentsPage() {
  return (
    <div style={{ padding: '20px 24px', maxWidth: 960, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 6px', fontSize: 17, fontWeight: 600 }}>Agents</h2>
      <p style={{ margin: '0 0 20px', fontSize: 12.5, color: 'var(--ink-3)', lineHeight: 1.6 }}>
        Four agents run in sequence for each incident. Each is stateless and communicates via events.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 16 }}>
        {(['handler', 'qa', 'dev', 'human'] as AgentId[]).map(id => (
          <AgentDetailCard key={id} id={id} />
        ))}
      </div>
    </div>
  );
}
