/* Screens: Incidents list + Incident detail */

function Header({ page, onNavigate, tour }){
  return (
    <header style={{
      display:'flex', alignItems:'center', gap: 14,
      padding: '12px 22px', borderBottom: '1px solid var(--line)',
      background: 'var(--bg)',
      position: 'sticky', top: 0, zIndex: 30,
    }}>
      <a onClick={() => onNavigate('list')} style={{ display:'flex', alignItems:'center', gap: 8, cursor:'pointer' }}>
        <Logo/>
        <span style={{ fontFamily:'var(--mono)', fontSize: 14, fontWeight: 600, letterSpacing: '-0.01em' }}>helix</span>
        <span className="mono" style={{ fontSize: 10, color:'var(--ink-3)', padding:'2px 5px', border:'1px solid var(--line-2)', borderRadius:3 }}>
          v1.4.2
        </span>
      </a>

      <nav style={{ display:'flex', gap: 2, marginLeft: 12 }}>
        <NavTab active={page==='list' || page==='detail'} onClick={()=>onNavigate('list')}>Incidents</NavTab>
        <NavTab active={page==='projects'} onClick={()=>onNavigate('projects')}>Projects</NavTab>
        <NavTab active={page==='github'} onClick={()=>onNavigate('github')}>GitHub</NavTab>
        <NavTab active={page==='agents'} onClick={()=>onNavigate('agents')}>Agents</NavTab>
        <NavTab active={page==='settings'} onClick={()=>onNavigate('settings')}>Settings</NavTab>
      </nav>

      <span style={{ flex: 1 }}/>

      <div style={{
        display:'flex', alignItems:'center', gap: 8,
        padding: '5px 10px', border:'1px solid var(--line-2)', borderRadius: 5,
        background: 'var(--bg-2)', width: 260,
      }}>
        <Icon.search size={12}/>
        <span className="mono" style={{ fontSize: 11.5, color:'var(--ink-3)' }}>Search incidents, PRs, commits…</span>
        <span style={{ flex: 1 }}/>
        <kbd className="mono" style={{ fontSize: 10, color:'var(--ink-3)', padding:'1px 5px', border:'1px solid var(--line-2)', borderRadius: 3 }}>⌘K</kbd>
      </div>

      <div style={{ display:'flex', alignItems:'center', gap: 8 }}>
        {tour && <WalkthroughButton onClick={tour.run} running={tour.running}/>}
        <span style={{ display:'flex', alignItems:'center', gap: 6 }}>
          <span style={{ width:7, height:7, borderRadius:'50%', background:'var(--ok)', animation:'pulse-dot 1.8s ease-in-out infinite' }}/>
          <span className="mono" style={{ fontSize: 10.5, color:'var(--ink-2)', letterSpacing:'0.06em' }}>3 agents online</span>
        </span>
        <span style={{ width:1, height: 16, background: 'var(--line-2)', margin:'0 4px' }}/>
        <div style={{
          width: 22, height: 22, borderRadius: '50%',
          background: 'linear-gradient(135deg, oklch(0.65 0.15 40), oklch(0.55 0.15 280))',
          border: '1px solid var(--line-2)',
        }}/>
        <span className="mono" style={{ fontSize: 11.5 }}>nauman</span>
      </div>
    </header>
  );
}

function NavTab({ active, children, onClick }){
  return (
    <button onClick={onClick} style={{
      fontFamily:'var(--mono)', fontSize: 12,
      padding: '5px 10px', borderRadius: 4,
      color: active ? 'var(--ink)' : 'var(--ink-3)',
      background: active ? 'var(--bg-3)' : 'transparent',
      border: active ? '1px solid var(--line-2)' : '1px solid transparent',
    }}>{children}</button>
  );
}

function Logo(){
  // Code braces { } wrapping an inner helix — developer-tool coding mark
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
      {/* Left brace { */}
      <path
        d="M8 3.5 C5.5 3.5 5.5 6 5.5 8 C5.5 10.5 4 11 3 12 C4 13 5.5 13.5 5.5 16 C5.5 18 5.5 20.5 8 20.5"
        stroke="var(--ink)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      />
      {/* Right brace } */}
      <path
        d="M16 3.5 C18.5 3.5 18.5 6 18.5 8 C18.5 10.5 20 11 21 12 C20 13 18.5 13.5 18.5 16 C18.5 18 18.5 20.5 16 20.5"
        stroke="var(--ink)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      />
      {/* Inner helix — orange + green crossing strands (X) */}
      <path d="M10 6 Q14 12 10 18" stroke="oklch(0.68 0.17 50)" strokeWidth="2" strokeLinecap="round"/>
      <path d="M14 6 Q10 12 14 18" stroke="oklch(0.62 0.16 155)" strokeWidth="2" strokeLinecap="round"/>
    </svg>
  );
}

// ---------------- INCIDENT LIST ----------------
function IncidentsList({ onOpen }){
  const [filter, setFilter] = useState('all');
  const [severity, setSeverity] = useState('any');

  const list = window.INCIDENTS.filter(i => {
    if (filter !== 'all' && i.status !== filter && !(filter === 'active' && !['merged','duplicate','failed'].includes(i.status))) return false;
    if (severity !== 'any' && i.severity !== severity) return false;
    return true;
  });

  const counts = {
    all: window.INCIDENTS.length,
    active: window.INCIDENTS.filter(i => !['merged','duplicate','failed'].includes(i.status)).length,
    merged: window.INCIDENTS.filter(i => i.status === 'merged').length,
    duplicate: window.INCIDENTS.filter(i => i.status === 'duplicate').length,
    failed: window.INCIDENTS.filter(i => i.status === 'failed').length,
  };

  return (
    <div style={{ padding: '22px 28px 60px', maxWidth: 1400, margin: '0 auto' }}>
      {/* Hero block */}
      <div style={{ display:'grid', gridTemplateColumns:'minmax(0, 1.3fr) minmax(0, 1fr)', alignItems:'end', gap: 32, marginBottom: 26 }}>
        <div style={{ minWidth: 0 }}>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing:'0.1em', textTransform:'uppercase', marginBottom: 10 }}>
            Incidents · last 7 days
          </div>
          <h1 style={{
            margin: 0, fontFamily:'var(--serif)', fontWeight: 400,
            fontSize: 'clamp(28px, 3.6vw, 46px)', lineHeight: 1.05, letterSpacing: '-0.02em', color:'var(--ink)',
            textWrap: 'balance',
          }}>
            <span style={{ color:'var(--ok)' }}>23 crashes</span>
            <span style={{ color:'var(--ink-3)' }}> became </span>
            <span style={{ color:'var(--ok)' }}>19 pull&nbsp;requests</span>.
            <br/>
            <span style={{ color:'var(--ink-3)' }}>4 need your review.</span>
          </h1>
        </div>
        <div style={{ display:'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 10, minWidth: 0 }}>
          <Stat value="23" label="incidents" trend={[1,3,2,5,3,6,3]} />
          <Stat value="19" label="PRs" accent="var(--ok)" trend={[0,2,2,4,3,5,3]}/>
          <Stat value="14" label="merged" accent="var(--ok)" trend={[0,1,2,3,2,4,2]}/>
          <Stat value="1m 28s" label="median fix" small trend={[3,2,4,3,3,2,2]}/>
        </div>
      </div>

      {/* Filter bar */}
      <div style={{
        display:'flex', alignItems:'center', gap: 6,
        padding: '8px 10px',
        border: '1px solid var(--line)', borderRadius: 8,
        background: 'var(--bg-2)', marginBottom: 14,
      }}>
        <span className="mono" style={{ fontSize: 10.5, color:'var(--ink-3)', letterSpacing: '0.1em', textTransform:'uppercase', marginRight: 6 }}>filter</span>
        {['all','active','pr','approval','merged','duplicate','failed'].map(k => (
          <FilterChip key={k} active={filter===k} onClick={()=>setFilter(k)} count={counts[k]}>
            {k}
          </FilterChip>
        ))}
        <span style={{ width:1, height:18, background:'var(--line-2)', margin:'0 8px' }}/>
        <span className="mono" style={{ fontSize: 10.5, color:'var(--ink-3)', letterSpacing: '0.1em', textTransform:'uppercase' }}>severity</span>
        {['any','high','medium','low'].map(k => (
          <FilterChip key={k} active={severity===k} onClick={()=>setSeverity(k)}>
            {k}
          </FilterChip>
        ))}
        <span style={{ flex: 1 }}/>
        <Button variant="ghost" size="sm"><Icon.refresh size={11}/> refresh</Button>
        <Button variant="subtle" size="sm">newest ↓</Button>
      </div>

      {/* Table */}
      <div style={{
        border: '1px solid var(--line)', borderRadius: 8,
        background: 'var(--bg)', overflow: 'hidden',
      }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '150px 1fr 180px 140px 110px 120px',
          gap: 16, padding: '10px 16px',
          background: 'var(--bg-2)', borderBottom: '1px solid var(--line)',
          fontFamily:'var(--mono)', fontSize: 10.5, color:'var(--ink-3)',
          letterSpacing: '0.1em', textTransform: 'uppercase',
        }}>
          <span>Incident</span>
          <span>Error</span>
          <span>Pipeline</span>
          <span>Agents</span>
          <span>Status</span>
          <span style={{ textAlign:'right' }}>Opened</span>
        </div>
        {list.map((inc, i) => (
          <IncidentRow key={inc.id} inc={inc} onClick={() => onOpen(inc.id)} />
        ))}
      </div>
    </div>
  );
}

function FilterChip({ active, children, count, onClick }){
  return (
    <button onClick={onClick} style={{
      fontFamily:'var(--mono)', fontSize: 11.5,
      padding: '4px 9px', borderRadius: 4,
      color: active ? 'var(--ink)' : 'var(--ink-2)',
      background: active ? 'var(--bg)' : 'transparent',
      border: active ? '1px solid var(--line-2)' : '1px solid transparent',
      boxShadow: active ? '0 1px 0 oklch(0.22 0.01 260 / 0.03)' : 'none',
      display:'inline-flex', alignItems:'center', gap: 6,
    }}>
      {children}
      {count != null && (
        <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{count}</span>
      )}
    </button>
  );
}

function Stat({ value, label, accent, trend, small }){
  return (
    <div style={{
      padding: '10px 12px',
      border: '1px solid var(--line)', borderRadius: 8,
      background: 'var(--bg-2)',
      minWidth: 0,
    }}>
      <div className="mono" style={{
        fontSize: small ? 18 : 24, color: accent || 'var(--ink)',
        lineHeight: 1, letterSpacing: '-0.02em', fontWeight: 500,
        whiteSpace:'nowrap',
      }}>{value}</div>
      <div style={{ display:'flex', alignItems:'flex-end', justifyContent:'space-between', marginTop: 6, gap: 6 }}>
        <span className="mono" style={{ fontSize: 10, color:'var(--ink-3)', letterSpacing:'0.06em', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>{label}</span>
        <Spark points={trend} color={accent || 'var(--ink-3)'} w={40} h={12}/>
      </div>
    </div>
  );
}

function IncidentRow({ inc, onClick }){
  return (
    <div onClick={onClick} style={{
      display: 'grid',
      gridTemplateColumns: '150px 1fr 180px 140px 110px 120px',
      gap: 16, padding: '14px 16px',
      borderTop: '1px solid var(--line)',
      alignItems: 'center',
      cursor: 'pointer',
      transition: 'background 120ms',
    }}
    onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-2)'}
    onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
    >
      {/* ID / component */}
      <div style={{ display:'flex', flexDirection:'column', gap: 2 }}>
        <span className="mono" style={{ fontSize: 11.5, color:'var(--accent)' }}>{inc.short}</span>
        <span style={{ fontSize: 11, color:'var(--ink-3)' }}>{inc.component}</span>
      </div>

      {/* Error */}
      <div style={{ display:'flex', flexDirection:'column', gap: 2, minWidth: 0 }}>
        <span className="mono" style={{ fontSize: 13, color:'var(--ink)', fontWeight: 500 }}>
          {inc.error}
        </span>
        <span style={{ fontSize: 11.5, color:'var(--ink-2)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
          {inc.message}
        </span>
      </div>

      {/* Pipeline mini */}
      <MiniPipeline inc={inc}/>

      {/* Agents */}
      <div style={{ display:'flex', gap: 4 }}>
        {agentsForIncident(inc).map(a => (
          <span key={a} title={window.AGENTS[a].name} style={{
            width: 20, height: 20, borderRadius: 3,
            background: `color-mix(in oklch, ${window.AGENTS[a].color} 14%, transparent)`,
            border: `1px solid color-mix(in oklch, ${window.AGENTS[a].color} 35%, transparent)`,
            color: window.AGENTS[a].color,
            fontFamily: 'var(--mono)', fontSize: 10, fontWeight: 700,
            display:'inline-flex', alignItems:'center', justifyContent:'center',
          }}>
            {window.AGENTS[a].short.slice(0,2)}
          </span>
        ))}
      </div>

      {/* Status */}
      <StatusPill status={inc.status}/>

      {/* Time */}
      <div style={{ textAlign:'right', display:'flex', flexDirection:'column', gap: 2 }}>
        <span className="mono" style={{ fontSize: 11.5, color:'var(--ink-2)' }}>{inc.createdAt}</span>
        <span style={{ fontSize: 10.5, color:'var(--ink-3)' }}>
          {inc.occurrences}× · {inc.users} user{inc.users !== 1 ? 's' : ''}
        </span>
      </div>
    </div>
  );
}

function agentsForIncident(inc){
  if (inc.status === 'duplicate' || inc.status === 'failed') return ['handler'];
  if (inc.status === 'analysing') return ['handler'];
  if (inc.status === 'testing') return ['handler','qa'];
  return ['handler','qa','dev'];
}

function MiniPipeline({ inc }){
  const progress = inc.progress ?? 0;
  if (inc.status === 'duplicate'){
    return (
      <div className="mono" style={{ fontSize: 11, color:'var(--ink-3)' }}>
        ↳ dup of <span style={{color:'var(--accent)'}}>{inc.duplicateOf}</span>
      </div>
    );
  }
  if (inc.status === 'failed'){
    return (
      <div className="mono" style={{ fontSize: 11, color:'var(--crash)' }}>
        {inc.note || 'escalated'}
      </div>
    );
  }
  const segs = ['handler','qa','dev','dev','human'];
  return (
    <div style={{ display:'flex', alignItems:'center', gap: 3 }}>
      {segs.map((a, i) => {
        const filled = progress >= (i+1)/segs.length - 0.08;
        return (
          <span key={i} style={{
            flex: 1, height: 4, borderRadius: 2,
            background: filled ? window.AGENTS[a].color : 'var(--bg-3)',
            opacity: filled ? 1 : 1,
            border: filled ? 'none' : '1px solid var(--line-2)',
          }}/>
        );
      })}
    </div>
  );
}

// ---------------- INCIDENT DETAIL ----------------
function IncidentDetail({ id, onBack }){
  const inc = window.INCIDENTS.find(i => i.id === id) || window.INCIDENTS[0];
  const [focusCall, setFocusCall] = useState(0);
  const [traceView, setTraceView] = useState('activity'); // activity | diff

  return (
    <div style={{
      display:'grid',
      gridTemplateColumns: window.__TWEAKS.showActivityRail ? 'minmax(0,1fr) 420px' : '1fr',
      gap: 16,
      padding: '16px 22px 40px',
      maxWidth: 1600, margin:'0 auto',
    }}>
      {/* Main column */}
      <div style={{ minWidth: 0 }}>
        {/* Breadcrumb + title */}
        <div style={{ marginBottom: 16 }}>
          <button onClick={onBack} className="mono" style={{
            fontSize: 11, color:'var(--ink-3)', padding:'3px 6px', border:'1px solid var(--line-2)',
            borderRadius: 4, background:'var(--bg-2)',
          }}>
            ← all incidents
          </button>
          <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between', gap: 20, marginTop: 14 }}>
            <div style={{ minWidth: 0 }}>
              <div className="mono" style={{ fontSize: 12, color:'var(--accent)', letterSpacing: '0.01em', marginBottom: 4 }}>
                {inc.id}
              </div>
              <h1 style={{
                margin: 0, fontFamily:'var(--serif)', fontSize: 42, fontWeight: 400,
                letterSpacing: '-0.02em', lineHeight: 1.05,
              }}>
                <span style={{ color:'var(--crash)' }}>{inc.error}</span>
                <span style={{ color:'var(--ink-3)' }}> in </span>
                <span className="mono" style={{ fontSize: 30, color:'var(--ink)' }}>{inc.component}</span>
              </h1>
              <p style={{ margin: '8px 0 0', fontSize: 14, color:'var(--ink-2)' }}>
                <span className="mono" style={{ fontSize: 13 }}>{inc.message}</span>
              </p>
            </div>
            <div style={{ display:'flex', gap: 6, alignItems:'center', flex:'0 0 auto' }}>
              <Severity level={inc.severity}/>
              <StatusPill status={inc.status}/>
              <span style={{ width:1, height:18, background:'var(--line-2)', margin:'0 4px' }}/>
              <Button variant="ghost" size="sm"><Icon.refresh size={11}/> rerun</Button>
              <Button variant="primary" size="sm"><Icon.check size={11}/> approve PR</Button>
            </div>
          </div>
        </div>

        {/* Hero pipeline */}
        <div style={{ marginBottom: 16 }}>
          <Pipeline incident={inc} activeStage={4}/>
        </div>

        {/* Dual pane: tool calls + diff OR crash report */}
        <div style={{ display:'grid', gridTemplateColumns: '1fr', gap: 16 }}>
          <ToolCallsList calls={window.TOOL_CALLS} focusIdx={focusCall} onFocus={setFocusCall}/>
          <PRDiff diff={window.PR_DIFF}/>
          <CrashReport inc={inc}/>
        </div>
      </div>

      {/* Right rail */}
      {window.__TWEAKS.showActivityRail && (
        <div style={{ minWidth: 0 }}>
          <ActivityRail log={window.ACTIVITY_LOG}/>
        </div>
      )}
    </div>
  );
}

function CrashReport({ inc }){
  const [open, setOpen] = useState(false);
  return (
    <section style={{
      border:'1px solid var(--line)', borderRadius:8, background:'var(--bg)', overflow:'hidden',
    }}>
      <div style={{ padding:'10px 14px', borderBottom:'1px solid var(--line)', background:'var(--bg-2)', display:'flex', alignItems:'center', gap:10 }}>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing:'0.1em', color:'var(--ink-3)', textTransform:'uppercase' }}>
          Crash report
        </span>
        <span style={{ color:'var(--ink-3)' }}>·</span>
        <span className="mono" style={{ fontSize: 11, color:'var(--ink-2)' }}>{inc.source}</span>
      </div>
      <div style={{ padding: '16px 18px', display:'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        <Field label="Error type" value={inc.error} mono/>
        <Field label="Component" value={inc.component}/>
        <Field label="Endpoint" value={inc.endpoint || '—'} mono/>
        <Field label="Language" value={inc.language || '—'} mono/>
        <Field label="Source" value={inc.source}/>
        <Field label="Detected" value={inc.createdAtLong || inc.createdAt}/>
        <Field label="Occurrences" value={`${inc.occurrences || 0}× · ${inc.users || 0} users`}/>
        <Field label="Dedupe hash" value="a92f…4d" mono/>
      </div>
      <div style={{ padding:'0 18px 16px' }}>
        <div style={{ fontFamily:'var(--mono)', fontSize:10.5, color:'var(--ink-3)', letterSpacing:'0.1em', textTransform:'uppercase', marginBottom: 6 }}>Summary</div>
        <p style={{ margin:0, fontSize: 13.5, color:'var(--ink-2)', textWrap:'pretty', maxWidth: 800 }}>{inc.summary || 'No summary available.'}</p>
      </div>

      <div style={{ borderTop:'1px solid var(--line)' }}>
        <button onClick={()=>setOpen(o=>!o)} style={{
          display:'flex', alignItems:'center', gap: 8, padding: '10px 18px', width:'100%', textAlign:'left',
          fontFamily:'var(--mono)', fontSize: 11.5, color:'var(--ink-2)',
        }}>
          <Icon.chev size={11} dir={open?'down':'right'}/> Stack trace
          <span style={{ color:'var(--ink-3)' }}>{window.STACK_TRACE.length} frames</span>
        </button>
        {open && (
          <div style={{ padding:'6px 18px 16px', fontFamily:'var(--mono)', fontSize: 12 }}>
            {window.STACK_TRACE.map((f, i) => (
              <div key={i} style={{
                padding: '4px 8px',
                background: f.highlight ? 'oklch(0.97 0.04 25)' : 'transparent',
                borderLeft: f.highlight ? '2px solid var(--crash)' : '2px solid transparent',
                color: f.highlight ? 'var(--crash)' : 'var(--ink-2)',
              }}>
                <span>{f.file}:{f.line}</span>
                <span style={{ color:'var(--ink-3)' }}> in </span>
                <span>{f.fn}()</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function Field({ label, value, mono }){
  return (
    <div>
      <div style={{ fontFamily:'var(--mono)', fontSize: 10, color:'var(--ink-3)', letterSpacing:'0.1em', textTransform:'uppercase', marginBottom: 3 }}>
        {label}
      </div>
      <div style={{ fontSize: 13, color:'var(--ink)', fontFamily: mono ? 'var(--mono)' : 'inherit' }}>
        {value}
      </div>
    </div>
  );
}

Object.assign(window, { Header, IncidentsList, IncidentDetail });
