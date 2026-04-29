import { useState, useRef, useEffect } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { WalkthroughButton } from './Walkthrough';
import { Icon } from './primitives';
import helixLogo from '../assets/helix-logo.svg';

export type Page = 'list' | 'detail' | 'projects' | 'github' | 'agents' | 'settings';

function NavTab({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} className="mono" style={{
      fontSize: 12, padding: '5px 10px', borderRadius: 4,
      color: active ? 'var(--ink)' : 'var(--ink-3)',
      background: active ? 'var(--bg-3)' : 'transparent',
      border: active ? '1px solid var(--line-2)' : '1px solid transparent',
      cursor: 'pointer',
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

function UserMenu({ onEditMode }: { onEditMode: () => void }) {
  const { user, logout } = useAuth0();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const displayName = user?.given_name ?? user?.name?.split(' ')[0] ?? user?.email?.split('@')[0] ?? 'you';

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button onClick={() => setOpen(o => !o)} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', background: 'none', border: 'none', padding: 0 }}>
        {user?.picture ? (
          <img src={user.picture} alt={displayName} referrerPolicy="no-referrer" style={{ width: 22, height: 22, borderRadius: '50%', border: '1px solid var(--line-2)' }} />
        ) : (
          <div style={{ width: 22, height: 22, borderRadius: '50%', background: 'linear-gradient(135deg, oklch(0.65 0.15 40), oklch(0.55 0.15 280))', border: '1px solid var(--line-2)' }} />
        )}
        <span className="mono" style={{ fontSize: 11.5, color: 'var(--ink)' }}>{displayName}</span>
      </button>

      {open && (
        <div style={{
          position: 'absolute', right: 0, top: 'calc(100% + 8px)', zIndex: 100,
          background: 'var(--bg)', border: '1px solid var(--line-2)',
          borderRadius: 6, boxShadow: '0 8px 24px oklch(0.22 0.01 260 / 0.08)',
          minWidth: 160, overflow: 'hidden',
        }}>
          <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--line)' }}>
            <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{user?.email}</div>
          </div>
          <button onClick={() => { setOpen(false); onEditMode(); }} style={{
            display: 'flex', alignItems: 'center', gap: 8, width: '100%',
            padding: '8px 12px', background: 'none', border: 'none', cursor: 'pointer',
            fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-2)', textAlign: 'left',
          }}
            onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-2)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'none')}
          >
            tweaks
          </button>
          <button onClick={() => logout({ logoutParams: { returnTo: window.location.origin } })} style={{
            display: 'flex', alignItems: 'center', gap: 8, width: '100%',
            padding: '8px 12px', background: 'none', border: 'none', cursor: 'pointer',
            fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--crash)', textAlign: 'left',
          }}
            onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-2)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'none')}
          >
            sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function Header({ page, go, walkthroughRunning, onWalkthrough, onEditMode }: HeaderProps) {

  return (
    <header style={{
      display: 'flex', alignItems: 'center', gap: 14,
      padding: '12px 22px', borderBottom: '1px solid var(--line)',
      background: 'var(--bg)', position: 'sticky', top: 0, zIndex: 50,
    }}>
      {/* Logo */}
      <a onClick={() => go('list')} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
        <img src={helixLogo} alt="helix" width={20} height={20} />
        <span style={{ fontFamily: 'var(--mono)', fontSize: 14, fontWeight: 600, letterSpacing: '-0.01em' }}>helix</span>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', padding: '2px 5px', border: '1px solid var(--line-2)', borderRadius: 3 }}>
          v0.1
        </span>
      </a>

      {/* Nav */}
      <nav style={{ display: 'flex', gap: 2, marginLeft: 12 }}>
        <NavTab label="Incidents" active={page === 'list' || page === 'detail'} onClick={() => go('list')} />
        <NavTab label="Projects"  active={page === 'projects'} onClick={() => go('projects')} />
        <NavTab label="GitHub"    active={page === 'github'}   onClick={() => go('github')} />
        <NavTab label="Agents"    active={page === 'agents'}   onClick={() => go('agents')} />
        <NavTab label="Settings"  active={page === 'settings'} onClick={() => go('settings')} />
      </nav>

      <span style={{ flex: 1 }} />

      {/* Search */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '5px 10px', border: '1px solid var(--line-2)', borderRadius: 5,
        background: 'var(--bg-2)', width: 260, cursor: 'text',
      }}>
        <Icon.search size={12} />
        <span className="mono" style={{ fontSize: 11.5, color: 'var(--ink-3)', flex: 1 }}>
          Search incidents, PRs, commits…
        </span>
        <kbd className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', padding: '1px 5px', border: '1px solid var(--line-2)', borderRadius: 3 }}>⌘K</kbd>
      </div>

      {/* Right section */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <WalkthroughButton onClick={onWalkthrough} running={walkthroughRunning} />

        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ok)', animation: 'pulse-dot 1.8s ease-in-out infinite' }} />
          <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-2)', letterSpacing: '0.06em' }}>3 agents online</span>
        </span>

        <span style={{ width: 1, height: 16, background: 'var(--line-2)', margin: '0 4px' }} />

        <UserMenu onEditMode={onEditMode} />
      </div>
    </header>
  );
}
