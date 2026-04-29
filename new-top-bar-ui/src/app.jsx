/* Slim app — Top bar only */
function App(){
  const [page, setPage] = useState('list');
  const [tweaks] = useState(window.__TWEAKS);
  useEffect(() => { window.__TWEAKS = tweaks; }, [tweaks]);
  return (
    <div>
      <Header page={page} onNavigate={setPage}/>
      <div style={{ padding: '40px 22px', color:'var(--ink-3)', fontFamily:'var(--mono)', fontSize: 12 }}>
        active: <span style={{ color:'var(--ink)' }}>{page}</span>
      </div>
    </div>
  );
}
ReactDOM.createRoot(document.getElementById('root')).render(<App/>);