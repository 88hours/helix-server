import { useEffect, useRef } from 'react';
import { AgentId } from '../constants';
import { AgentChip } from './primitives';

export interface ActivityEvent {
  id: string;
  ts: string;
  agent?: AgentId;
  type: 'log' | 'tool' | 'status' | 'error' | 'info';
  message: string;
}

interface LogLineProps {
  ev: ActivityEvent;
}

function typeColor(type: ActivityEvent['type']) {
  switch (type) {
    case 'error':  return 'var(--crash)';
    case 'status': return 'var(--ok)';
    case 'tool':   return 'var(--warn)';
    default:       return 'var(--term-ink)';
  }
}

function LogLine({ ev }: LogLineProps) {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 8,
      padding: '3px 10px',
      borderBottom: '1px solid oklch(0.28 0.01 260)',
    }}>
      <span className="mono" style={{ fontSize: 10, color: 'var(--term-ink-dim)', flexShrink: 0, paddingTop: 1 }}>
        {ev.ts}
      </span>
      {ev.agent && (
        <span style={{ flexShrink: 0, paddingTop: 1 }}>
          <AgentChip id={ev.agent} size="sm" />
        </span>
      )}
      <span className="mono" style={{ fontSize: 11, color: typeColor(ev.type), wordBreak: 'break-all', lineHeight: 1.45 }}>
        {ev.message}
      </span>
    </div>
  );
}

interface ActivityRailProps {
  events: ActivityEvent[];
  title?: string;
}

export function ActivityRail({ events, title = 'Activity' }: ActivityRailProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      background: 'var(--term-bg)', borderRadius: 6,
      border: '1px solid oklch(0.28 0.01 260)',
      overflow: 'hidden', height: '100%', minHeight: 0,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '6px 10px',
        borderBottom: '1px solid oklch(0.28 0.01 260)',
        background: 'var(--term-bg-2)',
        flexShrink: 0,
      }}>
        <span className="mono" style={{ fontSize: 10, color: 'var(--term-ink-dim)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          {title}
        </span>
        <span style={{
          width: 7, height: 7, borderRadius: '50%', background: 'var(--ok)',
          animation: events.length ? 'pulse-dot 1.6s ease-in-out infinite' : 'none',
        }}/>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {events.length === 0 ? (
          <div style={{ padding: '20px 10px', color: 'var(--term-ink-dim)', fontFamily: 'var(--mono)', fontSize: 11, textAlign: 'center' }}>
            waiting for events…<span className="cursor" style={{ marginLeft: 2 }}/>
          </div>
        ) : (
          events.map(ev => <LogLine key={ev.id} ev={ev} />)
        )}
        <div ref={bottomRef}/>
      </div>
    </div>
  );
}
