/* Tool-calls list + PR diff */

function ToolCallsList({ calls, focusIdx, onFocus }) {
  return (
    <section style={{
      border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden',
      background: 'var(--bg)',
    }}>
      <div style={{
        display:'flex', alignItems:'center', justifyContent:'space-between',
        padding: '10px 14px', borderBottom: '1px solid var(--line)', background: 'var(--bg-2)',
      }}>
        <div style={{ display:'flex', alignItems:'center', gap: 10 }}>
          <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.1em', color:'var(--ink-3)', textTransform:'uppercase' }}>
            Tool calls
          </span>
          <span className="mono" style={{ fontSize: 11, color:'var(--ink-2)' }}>{calls.length}</span>
        </div>
        <div style={{ display:'flex', gap: 6 }}>
          <Badge tone="dim">filter</Badge>
          <Badge tone="dim">group by agent</Badge>
        </div>
      </div>

      <ol style={{ listStyle:'none', margin:0, padding:0 }}>
        {calls.map((c, i) => (
          <ToolCallRow key={i} idx={i} call={c} focused={focusIdx === i} onClick={() => onFocus(i)} />
        ))}
      </ol>
    </section>
  );
}

function ToolCallRow({ idx, call, focused, onClick }){
  const a = window.AGENTS[call.agent];
  return (
    <li onClick={onClick} style={{
      display:'grid',
      gridTemplateColumns: '34px 36px 90px 1fr auto auto',
      gap: 10, alignItems:'center',
      padding: '9px 14px',
      borderTop: '1px solid var(--line)',
      cursor: 'pointer',
      background: focused ? 'var(--bg-3)' : 'transparent',
      transition: 'background 100ms',
    }}
    onMouseEnter={(e) => !focused && (e.currentTarget.style.background = 'var(--bg-2)')}
    onMouseLeave={(e) => !focused && (e.currentTarget.style.background = 'transparent')}
    >
      <span className="mono" style={{ color:'var(--ink-3)', fontSize: 10.5 }}>
        {String(idx+1).padStart(2,'0')}
      </span>
      <ToolIcon tool={call.tool} agent={call.agent} />
      <AgentChip id={call.agent} />
      <div style={{ display:'flex', alignItems:'baseline', gap: 8, minWidth: 0 }}>
        <span className="mono" style={{ fontSize: 12, color:'var(--ink)' }}>
          {call.tool} <span style={{color:'var(--ink-3)'}}>·</span> {call.action}
        </span>
        {call.payload && (
          <span className="mono" style={{ fontSize: 11, color:'var(--ink-3)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
            {call.payload}
          </span>
        )}
      </div>
      <span style={{ color: call.ok ? 'var(--ok)' : 'var(--crash)' }}>
        {call.ok ? <Icon.check size={13}/> : <Icon.cross size={13}/>}
      </span>
      <span className="mono" style={{ fontSize: 10.5, color:'var(--ink-3)' }}>{call.t}</span>
    </li>
  );
}

// ---- PR Diff ----
function PRDiff({ diff }){
  const [open, setOpen] = useState(true);
  return (
    <section style={{
      border: '1px solid var(--line)', borderRadius: 8, overflow:'hidden', background: 'var(--bg)',
    }}>
      <div style={{
        display:'flex', alignItems:'center', justifyContent:'space-between',
        padding: '10px 14px', borderBottom: '1px solid var(--line)', background: 'var(--bg-2)',
      }}>
        <div style={{ display:'flex', alignItems:'center', gap: 10 }}>
          <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.1em', color:'var(--ink-3)', textTransform:'uppercase' }}>
            Pull request
          </span>
          <span className="mono" style={{ fontSize: 12, color:'var(--dev)', fontWeight: 600 }}>{diff.pr}</span>
          <span className="mono" style={{ fontSize: 11, color:'var(--ink)' }}>{diff.title}</span>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap: 10 }}>
          <span className="mono" style={{ fontSize: 10.5, color:'var(--ink-3)' }}>
            {diff.files} files · <span style={{ color:'var(--ok)' }}>+{diff.additions}</span> <span style={{ color:'var(--crash)' }}>−{diff.deletions}</span>
          </span>
          <button onClick={() => setOpen(o=>!o)} style={{
            fontFamily:'var(--mono)', fontSize:10.5, color:'var(--ink-2)',
            padding:'3px 6px', border:'1px solid var(--line-2)', borderRadius:3, cursor:'pointer', background:'transparent'
          }}>
            {open ? 'collapse' : 'expand'}
          </button>
        </div>
      </div>

      {open && (
        <div>
          <div style={{
            display:'flex', gap:8, padding:'8px 14px',
            borderBottom: '1px solid var(--line)', background:'var(--bg-2)',
            fontFamily:'var(--mono)', fontSize: 11, color:'var(--ink-2)',
          }}>
            <span>branch</span>
            <span style={{color:'var(--ink)'}}>{diff.branch}</span>
            <span>→</span>
            <span style={{color:'var(--ink)'}}>{diff.base}</span>
          </div>
          {diff.hunks.map((hunk, i) => (
            <DiffFile key={i} hunk={hunk} />
          ))}
          <div style={{ display:'flex', alignItems:'center', gap: 8, padding: '10px 14px', background:'var(--bg-2)', borderTop:'1px solid var(--line)' }}>
            <Button variant="primary">
              <Icon.check size={12}/> Approve &amp; merge
            </Button>
            <Button variant="ghost">Request changes</Button>
            <Button variant="subtle">View on GitHub →</Button>
            <span style={{ flex: 1 }}/>
            <span className="mono" style={{ fontSize:10.5, color:'var(--ink-3)' }}>
              tests: <span style={{color:'var(--ok)'}}>passing</span> · ci: <span style={{color:'var(--ok)'}}>green</span>
            </span>
          </div>
        </div>
      )}
    </section>
  );
}

function DiffFile({ hunk }){
  return (
    <div>
      <div style={{
        padding:'8px 14px', background: 'var(--bg-2)',
        borderBottom: '1px solid var(--line)',
        display:'flex', alignItems:'center', gap: 8,
      }}>
        <Icon.github size={12}/>
        <span className="mono" style={{ fontSize: 11, color:'var(--ink)' }}>{hunk.file}</span>
      </div>
      <div style={{ background:'var(--bg)' }}>
        {hunk.lines.map((l, i) => (
          <div key={i} className="mono" style={{
            display:'grid', gridTemplateColumns: '42px 14px 1fr',
            background: l.k === 'add' ? 'oklch(0.96 0.04 155)' : l.k === 'del' ? 'oklch(0.96 0.04 25)' : 'transparent',
            color: 'var(--ink)', fontSize: 12,
            padding: '1px 0',
          }}>
            <span style={{ textAlign:'right', paddingRight: 10, color:'var(--ink-3)' }}>{l.n}</span>
            <span style={{ color: l.k === 'add' ? 'var(--ok)' : l.k === 'del' ? 'var(--crash)' : 'var(--ink-3)' }}>
              {l.k === 'add' ? '+' : l.k === 'del' ? '−' : ' '}
            </span>
            <span style={{ whiteSpace:'pre', paddingLeft: 8 }}>{l.t || ' '}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { ToolCallsList, PRDiff });
