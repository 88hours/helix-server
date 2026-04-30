import { useState, useEffect } from 'react';
import { Tweaks, Incident, useIncidents } from './constants';
import { Header, Page } from './components/Header';
import { useWalkthrough, WalkthroughOverlay } from './components/Walkthrough';
import { IncidentsPage } from './pages/IncidentsPage';
import { IncidentDetailPage } from './pages/IncidentDetailPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { GitHubPage } from './pages/GitHubPage';
import { AgentsPage } from './pages/AgentsPage';
import { SettingsPage } from './pages/SettingsPage';

function TweaksPanel({ tweaks, onUpdate, onClose }: {
  tweaks: Tweaks;
  onUpdate: (k: keyof Tweaks, v: string | boolean) => void;
  onClose: () => void;
}) {
  return (
    <div className="tweaks">
      <header>
        <h4>tweaks</h4>
        <button onClick={onClose} style={{ color: 'var(--ink-3)', cursor: 'pointer' }}>×</button>
      </header>
      <div className="row">
        <label>theme</label>
        <select value={tweaks.theme} onChange={e => onUpdate('theme', e.target.value)}>
          <option>light</option>
          <option>dark</option>
        </select>
      </div>
      <div className="row">
        <label>density</label>
        <select value={tweaks.density} onChange={e => onUpdate('density', e.target.value)}>
          <option>compact</option>
          <option>comfortable</option>
        </select>
      </div>
      <div className="row">
        <label>pipeline</label>
        <select value={tweaks.pipeline} onChange={e => onUpdate('pipeline', e.target.value)}>
          <option>horizontal</option>
          <option>swimlane</option>
        </select>
      </div>
      <div className="row">
        <label>accent</label>
        <select value={tweaks.accent} onChange={e => onUpdate('accent', e.target.value)}>
          <option>amber</option>
          <option>green</option>
          <option>violet</option>
          <option>blue</option>
          <option>ink</option>
        </select>
      </div>
      <div className="row">
        <label>activity rail</label>
        <input
          type="range" min={0} max={1} step={1}
          value={tweaks.showActivityRail ? 1 : 0}
          onChange={e => onUpdate('showActivityRail', e.target.value === '1')}
        />
      </div>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>('list');
  const [openId, setOpenId] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [tour, setTour] = useState(false);
  const [tweaks, setTweaks] = useState<Tweaks>(window.__TWEAKS ?? {
    theme: 'light', accent: 'amber', density: 'compact', pipeline: 'horizontal', showActivityRail: true,
  });

  const { incidents, loading, reload: reloadIncidents } = useIncidents();

  const updateTweak = (k: keyof Tweaks, v: string | boolean) => {
    setTweaks(prev => {
      const next = { ...prev, [k]: v };
      window.__TWEAKS = next;
      return next;
    });
  };

  useEffect(() => {
    document.documentElement.dataset.density = tweaks.density;
  }, [tweaks.density]);

  useEffect(() => {
    const ACCENT_COLORS: Record<string, string> = {
      amber:  'oklch(0.68 0.17 50)',
      green:  'oklch(0.62 0.16 155)',
      violet: 'oklch(0.62 0.18 295)',
      blue:   'oklch(0.56 0.12 230)',
      ink:    'var(--ink)',
    };
    document.documentElement.style.setProperty('--accent', ACCENT_COLORS[tweaks.accent] ?? ACCENT_COLORS.amber);
  }, [tweaks.accent]);

  // Apply theme CSS variable updates
  useEffect(() => {
    const root = document.documentElement;
    if (tweaks.theme === 'dark') {
      root.style.setProperty('--bg',   'oklch(0.12 0.01 260)');
      root.style.setProperty('--bg-2', 'oklch(0.16 0.01 260)');
      root.style.setProperty('--bg-3', 'oklch(0.20 0.01 260)');
      root.style.setProperty('--ink',   'oklch(0.92 0.005 85)');
      root.style.setProperty('--ink-2', 'oklch(0.72 0.008 260)');
      root.style.setProperty('--ink-3', 'oklch(0.52 0.008 260)');
      root.style.setProperty('--line',  'oklch(0.24 0.01 260)');
      root.style.setProperty('--line-2','oklch(0.28 0.01 260)');
    } else {
      root.style.removeProperty('--bg');
      root.style.removeProperty('--bg-2');
      root.style.removeProperty('--bg-3');
      root.style.removeProperty('--ink');
      root.style.removeProperty('--ink-2');
      root.style.removeProperty('--ink-3');
      root.style.removeProperty('--line');
      root.style.removeProperty('--line-2');
    }
  }, [tweaks.theme]);

  const selectedIncident: Incident | null = openId
    ? incidents.find(i => i.id === openId) ?? null
    : null;

  const go = (p: Page) => setPage(p);

  const walkthrough = useWalkthrough({
    go: (p: string) => setPage(p as Page),
    setOpenId: (id) => { setOpenId(id); },
    setEditMode,
    setTour,
  });

  const handleOpenIncident = (id: string) => {
    setOpenId(id);
    setPage('detail');
  };

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <Header
        page={page}
        go={go}
        walkthroughRunning={walkthrough.running}
        onWalkthrough={walkthrough.running ? walkthrough.stop : walkthrough.run}
        onEditMode={() => setEditMode(e => !e)}

      />

      {page === 'list' && (
        <IncidentsPage
          incidents={incidents}
          loading={loading}
          onOpen={handleOpenIncident}
          onRefresh={reloadIncidents}
        />
      )}

      {page === 'detail' && (
        <IncidentDetailPage
          incident={selectedIncident}
          onBack={() => setPage('list')}
          showActivityRail={tweaks.showActivityRail}
          pipelineLayout={tweaks.pipeline as 'horizontal' | 'swimlane'}
        />
      )}

      {page === 'projects' && <ProjectsPage />}
      {page === 'github'   && <GitHubPage onGo={(p: string) => go(p as Page)} />}
      {page === 'agents'   && <AgentsPage />}
      {page === 'settings' && <SettingsPage />}

      {editMode && (
        <TweaksPanel tweaks={tweaks} onUpdate={updateTweak} onClose={() => setEditMode(false)} />
      )}

      <WalkthroughOverlay caption={walkthrough.caption} running={tour && walkthrough.running} onStop={walkthrough.stop} />
    </div>
  );
}
