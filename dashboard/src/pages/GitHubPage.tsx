import { authFetch } from '../authFetch';
import { useState, useEffect } from 'react';
import { Badge, Button, Icon, LiveDot, Field } from '../components/primitives';

interface GitHubPageProps {
  onGo: (page: string) => void;
}

interface Repo {
  full_name: string;
  private: boolean;
  default_branch: string;
  description?: string;
}

export function GitHubPage({ onGo: _onGo }: GitHubPageProps) {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [installationId, setInstallationId] = useState<string | null>(null);
  const [installed, setInstalled] = useState(false);
  const [installUrl, setInstallUrl] = useState<string | null>(null);
  const [manualId, setManualId] = useState('');
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState('');

  const load = () => {
    authFetch('/api/github/repos')
      .then((r: Response) => r.ok ? r.json() : null)
      .then((d: { repos?: Repo[]; install_url?: string; installation_id?: string } | null) => {
        if (!d) return;
        if (d.repos) { setRepos(d.repos); setInstalled(true); }
        if (d.installation_id) setInstallationId(d.installation_id);
        if (d.install_url) setInstallUrl(d.install_url);
      })
      .catch(() => {});
  };

  useEffect(() => {
    load();
    authFetch('/api/github/install-url')
      .then((r: Response) => r.ok ? r.json() : null)
      .then((d: { install_url?: string } | null) => { if (d?.install_url) setInstallUrl(d.install_url); })
      .catch(() => {});
  }, []);

  const handleRegister = async () => {
    const id = manualId.trim();
    if (!id) return;
    setRegistering(true);
    setRegisterError('');
    try {
      const res = await authFetch('/api/github/installations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ installation_id: id }),
      });
      if (res.ok) {
        setManualId('');
        load();
      } else {
        const d = await res.json() as { detail?: string };
        setRegisterError(d.detail ?? 'Failed to register installation');
      }
    } catch {
      setRegisterError('Network error');
    }
    setRegistering(false);
  };

  return (
    <div style={{ padding: '22px 28px 60px', maxWidth: 900, margin: '0 auto' }}>

      {/* Page header */}
      <div style={{ marginBottom: 22 }}>
        <div className="mono" style={{
          fontSize: 11, color: 'var(--ink-3)', letterSpacing: '0.1em',
          textTransform: 'uppercase', marginBottom: 10,
        }}>
          Integrations · GitHub
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16 }}>
          <h1 style={{
            margin: 0, fontFamily: 'var(--serif)', fontWeight: 400,
            fontSize: 'clamp(28px, 3.4vw, 42px)', lineHeight: 1.05, letterSpacing: '-0.02em',
          }}>
            {installed ? (
              <>
                <span style={{ color: 'var(--ok)' }}>Connected</span>
                {' '}to GitHub
                <span style={{ color: 'var(--ink-3)' }}> · {repos.length} repos</span>
              </>
            ) : (
              <>
                Connect GitHub
                <span style={{ color: 'var(--ink-3)' }}> to get started</span>
              </>
            )}
          </h1>
          {installed && (
            <div style={{ display: 'flex', gap: 8 }}>
              <Button variant="ghost" size="sm" onClick={load}>
                <Icon.refresh size={11} /> refresh
              </Button>
              {installUrl && (
                <Button variant="ghost" size="sm" onClick={() => window.open(installUrl, '_blank', 'noopener,noreferrer')}>
                  <Icon.github size={11} /> manage on github →
                </Button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Connection card */}
      <section style={{
        border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg)',
      }}>
        <div style={{
          padding: '10px 14px', background: 'var(--bg-2)', borderBottom: '1px solid var(--line)',
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
            GitHub App
          </span>
          {installationId && (
            <span className="mono" style={{ fontSize: 11, color: 'var(--ink-2)' }}>#{installationId}</span>
          )}
          <span style={{ flex: 1 }} />
          {installed ? <LiveDot /> : <Badge tone="warn">not installed</Badge>}
        </div>

        {installed ? (
          <div style={{ padding: '16px 18px', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 20 }}>
            <Field label="Installation" value={installationId ?? '—'} />
            <Field label="Repositories" value={`${repos.length} accessible`} />
            <Field label="Permissions" value="contents · issues · pull_requests" />
            <Field label="Webhook events" value="push · pull_request · issue" />
          </div>
        ) : (
          <div style={{ padding: '20px 18px' }}>
            <p style={{ margin: '0 0 14px', fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.6 }}>
              Install the Helix GitHub App to allow Helix to clone repositories, open pull requests, and report CI status on your behalf.
              Once installed, add a project from the <strong>Projects</strong> page and select a repository from the list — Helix links them automatically.
            </p>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              {installUrl && (
                <Button variant="accent" size="sm" onClick={() => window.open(installUrl, '_blank', 'noopener,noreferrer')}>
                  <Icon.github size={11} /> Install GitHub App
                </Button>
              )}
              <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>or enter your installation ID manually</span>
            </div>
            <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                type="text"
                placeholder="installation ID  (e.g. 12345678)"
                value={manualId}
                onChange={e => setManualId(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleRegister()}
                style={{
                  fontFamily: 'var(--mono)', fontSize: 11.5,
                  padding: '6px 10px', border: '1px solid var(--line-2)',
                  borderRadius: 4, background: 'var(--bg-3)', color: 'var(--ink)',
                  outline: 'none', width: 240,
                }}
              />
              <Button variant="ghost" size="sm" onClick={handleRegister} disabled={registering || !manualId.trim()}>
                {registering ? 'connecting…' : 'connect'}
              </Button>
            </div>
            {registerError && (
              <p style={{ margin: '6px 0 0', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--crash)' }}>
                {registerError}
              </p>
            )}
          </div>
        )}
      </section>

      {/* Read-only repo list */}
      {installed && repos.length > 0 && (
        <div style={{ border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg)', marginTop: 16 }}>
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 100px 140px',
            gap: 16, padding: '10px 16px',
            background: 'var(--bg-2)', borderBottom: '1px solid var(--line)',
            fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ink-3)',
            letterSpacing: '0.1em', textTransform: 'uppercase',
          }}>
            <span>Repository</span>
            <span>Visibility</span>
            <span>Default branch</span>
          </div>
          {repos.map((r, i) => (
            <div key={r.full_name} style={{
              display: 'grid', gridTemplateColumns: '1fr 100px 140px',
              gap: 16, padding: '12px 16px', alignItems: 'center',
              borderTop: i === 0 ? 'none' : '1px solid var(--line)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                <Icon.github size={13} />
                <span className="mono" style={{ fontSize: 12.5, color: 'var(--accent)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {r.full_name}
                </span>
                {r.description && (
                  <span style={{ fontSize: 12, color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    — {r.description}
                  </span>
                )}
              </div>
              <Badge tone={r.private ? 'neutral' : 'info'}>{r.private ? 'private' : 'public'}</Badge>
              <span className="mono" style={{ fontSize: 12, color: 'var(--ink-2)' }}>{r.default_branch}</span>
            </div>
          ))}
        </div>
      )}

    </div>
  );
}
