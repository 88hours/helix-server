import { WalkthroughButton } from './Walkthrough';

export type Page = 'list' | 'detail' | 'projects' | 'github' | 'agents' | 'settings';

interface NavTabProps {
  label: string;
  active: boolean;
  onClick: () => void;
}

function NavTab({ label, active, onClick }: NavTabProps) {
  return (
    <button onClick={onClick} className="mono" style={{
      fontSize: 11.5, letterSpacing: '0.04em',
      padding: '6px 10px', borderRadius: 4,
      background: active ? 'var(--bg-3)' : 'transparent',
      border: active ? '1px solid var(--line-2)' : '1px solid transparent',
      color: active ? 'var(--ink)' : 'var(--ink-3)',
      cursor: 'pointer', transition: 'all 120ms',
    }}>
      {label}
    </button>
  );
}

interface HeaderProps {
  page: Page;
  go: (p: Page) => void;
  walkthroughRunning: boolean;
  onWalkthrough: () => void;
  onEditMode: () => void;
}

export function Header({ page, go, walkthroughRunning, onWalkthrough, onEditMode }: HeaderProps) {
  return (
    <header style={{
      display: 'flex', alignItems: 'center',
      padding: '0 16px', height: 44,
      borderBottom: '1px solid var(--line)',
      background: 'var(--bg)',
      position: 'sticky', top: 0, zIndex: 50,
    }}>
      <div className="mono" style={{
        fontSize: 13, fontWeight: 600, letterSpacing: '-0.01em',
        marginRight: 20, color: 'var(--ink)',
        display: 'flex', alignItems: 'center', gap: 7,
        userSelect: 'none',
      }}>
        <span style={{ color: 'var(--accent)', fontSize: 10 }}>◆</span>
        helix
        <span style={{ fontSize: 10, color: 'var(--ink-3)', fontWeight: 400 }}>v0.1</span>
      </div>

      <nav style={{ display: 'flex', alignItems: 'center', gap: 2, flex: 1 }}>
        <NavTab label="incidents" active={page === 'list' || page === 'detail'} onClick={() => go('list')} />
        <NavTab label="projects"  active={page === 'projects'} onClick={() => go('projects')} />
        <NavTab label="github"    active={page === 'github'}   onClick={() => go('github')} />
        <NavTab label="agents"    active={page === 'agents'}   onClick={() => go('agents')} />
        <NavTab label="settings"  active={page === 'settings'} onClick={() => go('settings')} />
      </nav>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <WalkthroughButton onClick={onWalkthrough} running={walkthroughRunning} />
        <button
          onClick={onEditMode}
          className="mono"
          style={{
            fontSize: 10.5, letterSpacing: '0.06em', padding: '5px 9px', borderRadius: 4,
            background: 'var(--bg-2)', border: '1px solid var(--line-2)',
            color: 'var(--ink-3)', cursor: 'pointer',
          }}
        >
          tweaks
        </button>
      </div>
    </header>
  );
}
