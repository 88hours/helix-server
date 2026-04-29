/* Shared UI primitives */

const { useState, useEffect, useRef, useMemo, useCallback, createContext, useContext } = React;

// ---- Badges ----
function Badge({ children, tone = 'neutral', style = {} }) {
  const tones = {
    neutral: { bg: 'var(--bg-3)', fg: 'var(--ink-2)', bd: 'var(--line-2)' },
    crash:   { bg: 'oklch(0.95 0.04 25)', fg: 'oklch(0.42 0.14 25)', bd: 'oklch(0.88 0.08 25)' },
    warn:    { bg: 'oklch(0.96 0.05 70)', fg: 'oklch(0.4 0.12 50)',  bd: 'oklch(0.88 0.08 65)' },
    ok:      { bg: 'oklch(0.95 0.04 155)', fg: 'oklch(0.4 0.11 155)', bd: 'oklch(0.88 0.08 155)' },
    info:    { bg: 'oklch(0.95 0.03 230)', fg: 'oklch(0.4 0.1 230)',  bd: 'oklch(0.88 0.06 230)' },
    violet:  { bg: 'oklch(0.95 0.04 295)', fg: 'oklch(0.4 0.14 295)', bd: 'oklch(0.88 0.08 295)' },
    amber:   { bg: 'oklch(0.96 0.06 70)', fg: 'oklch(0.42 0.14 50)',  bd: 'oklch(0.86 0.1 65)' },
    dim:     { bg: 'transparent', fg: 'var(--ink-3)', bd: 'var(--line-2)' },
  };
  const t = tones[tone] || tones.neutral;
  return (
    <span className="mono" style={{
      display:'inline-flex', alignItems:'center', gap:4,
      fontSize: 10.5, lineHeight: 1, padding: '3px 6px',
      border: `1px solid ${t.bd}`, borderRadius: 3,
      background: t.bg, color: t.fg,
      textTransform: 'uppercase', letterSpacing: '0.06em',
      fontWeight: 500,
      ...style
    }}>{children}</span>
  );
}

function StatusPill({ status }) {
  const map = {
    merged:    { tone: 'ok',     label: 'merged' },
    pr:        { tone: 'ok',     label: 'pr created' },
    approval:  { tone: 'amber',  label: 'awaiting approval' },
    analysing: { tone: 'warn',   label: 'analysing' },
    testing:   { tone: 'violet', label: 'test gen' },
    fixing:    { tone: 'ok',     label: 'fixing' },
    duplicate: { tone: 'dim',    label: 'duplicate' },
    failed:    { tone: 'crash',  label: 'failed' },
    crash:     { tone: 'crash',  label: 'crash' },
  };
  const s = map[status] || { tone: 'neutral', label: status };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

function Severity({ level }) {
  const fg = level === 'high' ? 'var(--crash)'
           : level === 'medium' ? 'var(--warn)'
           : 'var(--ink-3)';
  return (
    <span className="mono" style={{
      display:'inline-flex', alignItems:'center', gap:6,
      fontSize:11, color: 'var(--ink-2)',
    }}>
      <span style={{
        width:6, height:6, borderRadius: '50%',
        background: fg,
        boxShadow: level === 'high' ? `0 0 0 3px ${fg.replace(')', ' / 0.18)')}` : 'none',
      }}/>
      {level}
    </span>
  );
}

// ---- Agent chip ----
function AgentChip({ id, size = 'sm' }) {
  const a = window.AGENTS[id];
  if (!a) return null;
  const h = size === 'sm' ? 16 : 20;
  return (
    <span className="mono" style={{
      display:'inline-flex', alignItems:'center', gap:5, fontSize: size==='sm'?10.5:12,
      color: a.color, letterSpacing: '0.04em', fontWeight: 600,
    }}>
      <span style={{
        width: h, height: h, borderRadius: 3,
        background: `color-mix(in oklch, ${a.color} 14%, transparent)`,
        color: a.color, display:'inline-flex', alignItems:'center', justifyContent:'center',
        fontSize: 10, fontWeight: 700,
        border: `1px solid color-mix(in oklch, ${a.color} 35%, transparent)`,
      }}>{a.short.slice(0,2)}</span>
      <span style={{textTransform: 'lowercase'}}>{a.short}</span>
    </span>
  );
}

// ---- Icons (minimal, hand-tuned) ----
const Icon = {
  git: ({ size=12 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
      <circle cx="5" cy="4" r="1.6" /><circle cx="5" cy="12" r="1.6" /><circle cx="11" cy="8" r="1.6" />
      <path d="M5 5.6v4.8 M6.4 12a4.4 4.4 0 0 0 3.2-2.8" />
    </svg>
  ),
  github: ({ size=12 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 1a7 7 0 0 0-2.2 13.65c.35.07.48-.15.48-.34v-1.2c-1.95.43-2.36-.93-2.36-.93-.32-.81-.78-1.03-.78-1.03-.64-.44.05-.43.05-.43.71.05 1.08.73 1.08.73.63 1.07 1.64.76 2.04.58.06-.45.25-.76.45-.94-1.56-.18-3.2-.78-3.2-3.47 0-.77.27-1.4.72-1.89-.07-.18-.31-.9.07-1.87 0 0 .59-.19 1.93.72a6.7 6.7 0 0 1 3.52 0c1.34-.91 1.93-.72 1.93-.72.38.97.14 1.69.07 1.87.45.49.72 1.12.72 1.89 0 2.7-1.64 3.29-3.2 3.47.25.22.48.65.48 1.31v1.94c0 .19.13.42.49.34A7 7 0 0 0 8 1Z"/>
    </svg>
  ),
  llm: ({ size=12 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M8 2.5l1.3 2.7 2.9.3-2.2 2 .6 2.9L8 9l-2.6 1.4.6-2.9-2.2-2 2.9-.3L8 2.5Z" />
    </svg>
  ),
  claude: ({ size=12 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M3 12L6.5 3.5 7.5 6 10 3.5 13 12" />
    </svg>
  ),
  check: ({ size=12 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 8.5 L6.5 12 L13 4.5" />
    </svg>
  ),
  cross: ({ size=12 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M4 4l8 8 M12 4l-8 8"/>
    </svg>
  ),
  chev: ({ size=12, dir='right' }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6"
         style={{ transform: `rotate(${ {right:0, down:90, left:180, up:270}[dir] }deg)`}}>
      <path d="M6 3l5 5-5 5"/>
    </svg>
  ),
  refresh: ({ size=12 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
      <path d="M2.5 8a5.5 5.5 0 0 1 9.8-3.4M13.5 8a5.5 5.5 0 0 1-9.8 3.4"/>
      <path d="M12.5 2.5v2.6H10M3.5 13.5v-2.6H6"/>
    </svg>
  ),
  dot: ({ size=12 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16"><circle cx="8" cy="8" r="3" fill="currentColor"/></svg>
  ),
  search: ({ size=12 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
      <circle cx="7" cy="7" r="4.5"/><path d="M10.3 10.3L14 14"/>
    </svg>
  ),
  bolt: ({ size=12 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor">
      <path d="M9 1 3 9h4l-1 6 6-8H8l1-6Z"/>
    </svg>
  ),
};

function ToolIcon({ tool, agent }) {
  const color = window.AGENTS[agent]?.color || 'var(--ink-2)';
  const I = {
    Git: Icon.git,
    GitHub: Icon.github,
    LLM: Icon.llm,
    Claude: Icon.claude,
  }[tool] || Icon.dot;
  return (
    <span style={{
      width: 22, height: 22, borderRadius: 4,
      background: `color-mix(in oklch, ${color} 10%, transparent)`,
      border: `1px solid color-mix(in oklch, ${color} 25%, transparent)`,
      color: color, display:'inline-flex', alignItems:'center', justifyContent:'center',
      flex: '0 0 auto',
    }}>
      <I size={12} />
    </span>
  );
}

// ---- Button ----
function Button({ children, variant='ghost', size='md', onClick, style={}, ...rest }) {
  const base = {
    display:'inline-flex', alignItems:'center', gap:6,
    fontFamily: 'var(--mono)', fontSize: 11.5,
    padding: size==='sm' ? '5px 8px' : '7px 10px',
    borderRadius: 4, border: '1px solid transparent',
    cursor: 'pointer', letterSpacing: '0.02em',
    transition: 'background 120ms, border-color 120ms',
  };
  const v = {
    ghost:    { color:'var(--ink-2)', border:'1px solid var(--line-2)', background:'transparent' },
    primary:  { color:'var(--bg)', background:'var(--ink)', borderColor:'var(--ink)' },
    accent:   { color:'var(--bg)', background:'var(--accent)', borderColor:'var(--accent)' },
    danger:   { color:'oklch(0.98 0.03 25)', background:'var(--crash)', borderColor:'var(--crash)' },
    subtle:   { color:'var(--ink-2)', background:'transparent' },
  }[variant];
  return <button onClick={onClick} style={{...base, ...v, ...style}} {...rest}>{children}</button>;
}

// ---- Mini spark ----
function Spark({ points = [], w = 72, h = 18, color = 'var(--ink-3)' }) {
  if (!points.length) return null;
  const max = Math.max(...points, 1);
  const pts = points.map((p, i) => {
    const x = (i/(points.length-1))*w;
    const y = h - (p/max)*h + 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg width={w} height={h} style={{ display:'block' }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.2" strokeLinejoin="round"/>
    </svg>
  );
}

Object.assign(window, { Badge, StatusPill, Severity, AgentChip, Icon, ToolIcon, Button, Spark });
