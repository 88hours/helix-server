import { AgentId } from '../constants';
import { AgentChip, Icon, ToolIcon } from './primitives';

export interface ToolCall {
  id: string;
  agent: AgentId;
  tool: string;
  input: string;
  output?: string;
  ts: string;
  durationMs?: number;
}

export interface DiffHunk {
  file: string;
  lang?: string;
  lines: { type: '+' | '-' | ' '; text: string }[];
}

// ---- ToolCallRow ----

interface ToolCallRowProps {
  tc: ToolCall;
  expanded: boolean;
  onToggle: () => void;
}

function ToolCallRow({ tc, expanded, onToggle }: ToolCallRowProps) {
  return (
    <div style={{ borderBottom: '1px solid var(--line)' }}>
      <button
        onClick={onToggle}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 8,
          padding: '6px 10px', background: 'none', border: 'none', cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <ToolIcon tool={tc.tool} agent={tc.agent} />
        <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-2)', flex: 1 }}>
          {tc.tool}
        </span>
        <AgentChip id={tc.agent} />
        {tc.durationMs !== undefined && (
          <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>
            {tc.durationMs < 1000 ? `${tc.durationMs}ms` : `${(tc.durationMs / 1000).toFixed(1)}s`}
          </span>
        )}
        <span style={{ color: 'var(--ink-3)', transition: 'transform 150ms', transform: expanded ? 'rotate(90deg)' : 'none' }}>
          <Icon.chev size={10} />
        </span>
      </button>
      {expanded && (
        <div style={{ padding: '0 10px 8px 42px' }}>
          <div style={{
            fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--term-ink)',
            background: 'var(--term-bg)', borderRadius: 4,
            padding: '6px 8px', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
            maxHeight: 180, overflowY: 'auto',
          }}>
            <span style={{ color: 'var(--term-ink-dim)' }}>{'→ '}</span>
            {tc.input}
            {tc.output && (
              <>
                {'\n'}
                <span style={{ color: 'var(--term-ink-dim)' }}>{'← '}</span>
                <span style={{ color: 'var(--term-green)' }}>{tc.output}</span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---- ToolCallsList ----

interface ToolCallsListProps {
  calls: ToolCall[];
}

export function ToolCallsList({ calls }: ToolCallsListProps) {
  const [expanded, setExpanded] = React.useState<string | null>(null);

  if (!calls.length) {
    return (
      <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--ink-3)' }} className="mono">
        no tool calls yet
      </div>
    );
  }

  return (
    <div>
      {calls.map(tc => (
        <ToolCallRow
          key={tc.id}
          tc={tc}
          expanded={expanded === tc.id}
          onToggle={() => setExpanded(prev => prev === tc.id ? null : tc.id)}
        />
      ))}
    </div>
  );
}

// ---- PRDiff ----

interface DiffFileProps {
  hunk: DiffHunk;
}

function DiffFile({ hunk }: DiffFileProps) {
  return (
    <div style={{ border: '1px solid var(--line-2)', borderRadius: 6, overflow: 'hidden', marginBottom: 10 }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '6px 10px', background: 'var(--bg-2)',
        borderBottom: '1px solid var(--line)',
      }}>
        <Icon.git size={11} />
        <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-2)' }}>{hunk.file}</span>
      </div>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 11, lineHeight: 1.6, overflowX: 'auto' }}>
        {hunk.lines.map((line, i) => (
          <div key={i} style={{
            padding: '0 10px',
            background: line.type === '+' ? 'oklch(0.95 0.04 155 / 0.4)' : line.type === '-' ? 'oklch(0.95 0.04 25 / 0.4)' : 'transparent',
            color: line.type === '+' ? 'oklch(0.4 0.12 155)' : line.type === '-' ? 'oklch(0.42 0.14 25)' : 'var(--ink-2)',
            whiteSpace: 'pre',
          }}>
            {line.type === ' ' ? ' ' : line.type} {line.text}
          </div>
        ))}
      </div>
    </div>
  );
}

interface PRDiffProps {
  hunks: DiffHunk[];
  prUrl?: string | null;
}

export function PRDiff({ hunks, prUrl }: PRDiffProps) {
  return (
    <div data-tour="pr-diff">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          Pull Request Diff
        </span>
        {prUrl && (
          <a href={prUrl} target="_blank" rel="noopener noreferrer" style={{
            display: 'flex', alignItems: 'center', gap: 5,
            fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--accent)',
          }}>
            <Icon.github size={11} /> view PR
          </a>
        )}
      </div>
      {hunks.map((h, i) => <DiffFile key={i} hunk={h} />)}
    </div>
  );
}

// Need React for useState
import React from 'react';
