/* Live activity rail — always-visible terminal */

function ActivityRail({ log, liveMode = true }){
  const [visible, setVisible] = useState(0);
  const bodyRef = useRef(null);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    setVisible(liveMode ? 0 : log.length);
  }, [liveMode, log.length]);

  useEffect(() => {
    if (!liveMode || paused) return;
    if (visible >= log.length) return;
    const delay = 240 + Math.random() * 220;
    const t = setTimeout(() => setVisible(v => Math.min(v+1, log.length)), delay);
    return () => clearTimeout(t);
  }, [visible, liveMode, paused, log.length]);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [visible]);

  const shown = log.slice(0, visible);
  const running = visible < log.length;

  return (
    <aside style={{
      position:'sticky', top: 16,
      height: 'calc(100vh - 32px)',
      background: 'var(--term-bg)',
      border: '1px solid var(--line-2)',
      borderRadius: 8,
      overflow: 'hidden',
      display: 'flex', flexDirection:'column',
      boxShadow: '0 20px 40px oklch(0.22 0.01 260 / 0.05)',
    }}>
      {/* Titlebar */}
      <div style={{
        display:'flex', alignItems:'center', gap: 8,
        padding: '9px 12px', background: 'var(--term-bg-2)',
        borderBottom: '1px solid oklch(0.28 0.012 260)',
      }}>
        <span style={{ display:'flex', gap: 6 }}>
          <span style={{ width:10, height:10, borderRadius:'50%', background:'oklch(0.65 0.19 25)' }}/>
          <span style={{ width:10, height:10, borderRadius:'50%', background:'oklch(0.78 0.16 85)' }}/>
          <span style={{ width:10, height:10, borderRadius:'50%', background:'oklch(0.72 0.17 155)' }}/>
        </span>
        <span className="mono" style={{ fontSize: 11, color:'var(--term-ink-dim)', marginLeft: 8 }}>
          helix ~ agent trace
        </span>
        <span style={{ flex: 1 }}/>
        <span className="mono" style={{ fontSize: 10, color: running ? 'var(--term-green)' : 'var(--term-ink-dim)', letterSpacing:'0.08em', textTransform:'uppercase' }}>
          {running ? (<span style={{ display:'inline-flex', alignItems:'center', gap:5 }}>
            <span style={{ width:6, height:6, borderRadius:'50%', background:'var(--term-green)', animation:'pulse-dot 1.4s ease-in-out infinite' }}/>
            live
          </span>) : 'idle'}
        </span>
        <button onClick={() => setPaused(p=>!p)} style={{
          fontFamily:'var(--mono)', fontSize:10, color:'var(--term-ink-dim)',
          padding:'2px 6px', border:'1px solid oklch(0.3 0.012 260)', borderRadius: 3,
        }}>
          {paused ? 'resume' : 'pause'}
        </button>
      </div>

      {/* Body */}
      <div ref={bodyRef} style={{
        flex: 1, overflow:'auto',
        padding: '10px 12px',
        fontFamily:'var(--mono)', fontSize: 11.5,
        color: 'var(--term-ink)',
        lineHeight: 1.55,
      }}>
        <div style={{ color:'var(--term-ink-dim)' }}>
          $ helix trace --incident 7e5ebf67-…
        </div>
        <div style={{ color:'var(--term-ink-dim)', marginBottom: 8 }}>
          streaming events · press <kbd style={{ border:'1px solid oklch(0.3 0.012 260)', padding:'1px 4px', borderRadius:2 }}>j/k</kbd> to navigate
        </div>

        {shown.map((ev, i) => <LogLine key={i} ev={ev} />)}
        {running && (
          <div style={{ color:'var(--term-ink-dim)', display:'flex', alignItems:'center', gap:8, marginTop:2 }}>
            <span style={{ color:'var(--term-green)' }}>→</span>
            <span>waiting for next event</span>
            <span className="cursor" style={{ color: 'var(--term-green)' }}/>
          </div>
        )}
      </div>

      {/* Footer */}
      <div style={{
        display:'flex', alignItems:'center', gap: 10,
        padding:'8px 12px', background:'var(--term-bg-2)',
        borderTop: '1px solid oklch(0.28 0.012 260)',
        fontFamily:'var(--mono)', fontSize: 10.5, color:'var(--term-ink-dim)',
      }}>
        <span>{shown.length}/{log.length} events</span>
        <span>·</span>
        <span>filter: <span style={{ color:'var(--term-ink)' }}>all</span></span>
        <span style={{ flex: 1 }}/>
        <span>helix@1.4.2</span>
      </div>
    </aside>
  );
}

function LogLine({ ev }){
  const a = window.AGENTS[ev.agent];
  const kindColor = {
    info:  'var(--term-ink-dim)',
    tool:  'oklch(0.82 0.14 230)',
    llm:   'oklch(0.82 0.16 295)',
    done:  'var(--term-green)',
    err:   'oklch(0.72 0.19 25)',
  }[ev.kind] || 'var(--term-ink)';

  const sigil = {
    info:  '·',
    tool:  '⟶',
    llm:   '◆',
    done:  '✓',
    err:   '✗',
  }[ev.kind] || '·';

  return (
    <div style={{
      display:'grid', gridTemplateColumns: '64px 14px 44px 1fr',
      gap: 6, padding:'1px 0',
    }}>
      <span style={{ color:'var(--term-ink-dim)' }}>{ev.t}</span>
      <span style={{ color: kindColor, textAlign:'center' }}>{sigil}</span>
      <span style={{
        color: a.color, textTransform:'lowercase', fontWeight: 600,
      }}>{a.short}</span>
      <span style={{ color: ev.kind === 'done' ? 'var(--term-green)' : 'var(--term-ink)' }}>
        {ev.text}
      </span>
    </div>
  );
}

Object.assign(window, { ActivityRail });
