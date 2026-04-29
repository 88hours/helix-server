/* Slim app — Incidents only */
function App(){
  const [page, setPage] = useState('list');
  const [openId, setOpenId] = useState(window.INCIDENTS[0].id);
  const [tweaks] = useState(window.__TWEAKS);
  useEffect(() => { window.__TWEAKS = tweaks; }, [tweaks]);
  const navigate = (p, id) => { setPage(p); if (id) setOpenId(id); };
  return (
    <div>
      <header style={{
        display:'flex', alignItems:'center', gap: 14,
        padding: '12px 22px', borderBottom: '1px solid var(--line)',
        background: 'var(--bg)', position:'sticky', top: 0, zIndex: 30,
      }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
          <path d="M8 3.5 C5.5 3.5 5.5 6 5.5 8 C5.5 10.5 4 11 3 12 C4 13 5.5 13.5 5.5 16 C5.5 18 5.5 20.5 8 20.5" stroke="var(--ink)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          <path d="M16 3.5 C18.5 3.5 18.5 6 18.5 8 C18.5 10.5 20 11 21 12 C20 13 18.5 13.5 18.5 16 C18.5 18 18.5 20.5 16 20.5" stroke="var(--ink)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          <path d="M10 6 Q14 12 10 18" stroke="oklch(0.68 0.17 50)" strokeWidth="2" strokeLinecap="round"/>
          <path d="M14 6 Q10 12 14 18" stroke="oklch(0.62 0.16 155)" strokeWidth="2" strokeLinecap="round"/>
        </svg>
        <span style={{ fontFamily:'var(--mono)', fontSize: 14, fontWeight: 600 }}>helix</span>
        <span className="mono" style={{ fontSize: 10, color:'var(--ink-3)', padding:'2px 5px', border:'1px solid var(--line-2)', borderRadius:3 }}>incidents</span>
      </header>
      {page === 'list' && <IncidentsList onOpen={(id) => navigate('detail', id)}/>}
      {page === 'detail' && <IncidentDetail id={openId} onBack={() => navigate('list')}/>}
    </div>
  );
}
ReactDOM.createRoot(document.getElementById('root')).render(<App/>);