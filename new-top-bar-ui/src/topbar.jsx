/* Top bar — Header + nav tabs + search + user chip */
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

Object.assign(window, { Header });