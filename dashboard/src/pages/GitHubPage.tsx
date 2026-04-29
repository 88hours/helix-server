import { authFetch } from '../authFetch';
import { useState, useEffect } from 'react';
import { Badge, Button, Icon, LiveDot, Field } from '../components/primitives';

interface Repo {
  full_name: string;
  private: boolean;
  default_branch: string;
  description: string;
}

interface Project {
  project_id: string;
  name: string;
  repo: string;
}

interface RepoRowProps {
  repo: Repo;
  linkedProject: Project | undefined;
  onGo: (page: string, projectId?: string) => void;
}

function RepoRow({ repo, linkedProject, onGo }: RepoRowProps) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1.5fr 110px 140px 1fr 150px',
        gap: 16,
        padding: '14px 16px',
        borderTop: '1px solid var(--line)',
        alignItems: 'center',
        transition: 'background 120ms',
      }}
      onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-2)')}
      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        <Icon.github size={13} />
        <span className="mono" style={{ fontSize: 12.5, color: 'var(--accent)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {repo.full_name}
        </span>
      </div>
      <Badge tone={repo.private ? 'neutral' : 'info'}>{repo.private ? 'private' : 'public'}</Badge>
      <span className="mono" style={{ fontSize: 12, color: 'var(--ink-2)' }}>{repo.default_branch}</span>
      <div>
        {linkedProject
          ? <span className="mono" style={{ fontSize: 12, color: 'var(--ink)' }}>→ {linkedProject.name}</span>
          : <span className="mono" style={{ fontSize: 12, color: 'var(--ink-3)' }}>— unlinked</span>}
      </div>
      <div style={{ textAlign: 'right' }}>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onGo(linkedProject ? 'projects' : 'projects')}
        >
          {linkedProject ? 'configure' : '+ link project'}
        </Button>
      </div>
    </div>
  );
}

interface GitHubPageProps {
  onGo: (page: string) => void;
}

export function GitHubPage({ onGo }: GitHubPageProps) {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [installationId, setInstallationId] = useState<string | null>(null);
  const [installed, setInstalled] = useState(false);
  const [installUrl, setInstallUrl] = useState<string | null>(null);
  const [manualId, setManualId] = useState('');
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState('');

  const loadRepos = () => {
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
    loadRepos();
    authFetch('/api/github/install-url')
      .then((r: Response) => r.ok ? r.json() : null)
      .then((d: { install_url?: string } | null) => { if (d?.install_url) setInstallUrl(d.install_url); })
      .catch(() => {});
    authFetch('/api/projects')
      .then((r: Response) => r.ok ? r.json() : null)
      .then((d: { projects?: Project[] } | null) => { if (d?.projects) setProjects(d.projects); })
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
        loadRepos();
      } else {
        const d = await res.json() as { detail?: string };
        setRegisterError(d.detail ?? 'Failed to register installation');
      }
    } catch {
      setRegisterError('Network error');
    }
    setRegistering(false);
  };

  const linkedCount = repos.filter(r => projects.some(p => p.repo === r.full_name)).length;

  return (
    <div style={{ padding: '22px 28px 60px', maxWidth: 1400, margin: '0 auto' }}>

      {/* Page header */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'minmax(0,1.3fr) minmax(0,1fr)',
        alignItems: 'end', gap: 32, marginBottom: 22,
      }}>
        <div>
          <div className="mono" style={{
            fontSize: 11, color: 'var(--ink-3)', letterSpacing: '0.1em',
            textTransform: 'uppercase', marginBottom: 10,
          }}>
            Integrations · GitHub
          </div>
          {installed ? (
            <h1 style={{
              margin: 0, fontFamily: 'var(--serif)', fontWeight: 400,
              fontSize: 'clamp(28px, 3.4vw, 42px)', lineHeight: 1.05, letterSpacing: '-0.02em',
            }}>
              <span style={{ color: 'var(--ok)' }}>Connected</span>
              {' '}to GitHub
              <span style={{ color: 'var(--ink-3)' }}> · {repos.length} repos · {linkedCount} linked</span>
            </h1>
          ) : (
            <h1 style={{
              margin: 0, fontFamily: 'var(--serif)', fontWeight: 400,
              fontSize: 'clamp(28px, 3.4vw, 42px)', lineHeight: 1.05, letterSpacing: '-0.02em',
            }}>
              Connect GitHub
              <span style={{ color: 'var(--ink-3)' }}> to get started</span>
            </h1>
          )}
        </div>
        {installed && (
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <Button variant="ghost" size="sm" onClick={loadRepos}>
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

      {/* Connection card */}
      <section style={{
        border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden',
        background: 'var(--bg)', marginBottom: 16,
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
          <div style={{ padding: '16px 18px', display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 20 }}>
            <Field label="Installation" value={installationId ?? '—'} />
            <Field label="Repositories" value={`${repos.length} accessible`} />
            <Field label="Linked projects" value={`${linkedCount} of ${repos.length}`} />
            <Field label="Permissions" value="contents · issues · pull_requests" />
            <Field label="Webhook events" value="push · pull_request · issue" />
          </div>
        ) : (
          <div style={{ padding: '20px 18px' }}>
            <p style={{ margin: '0 0 14px', fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.6 }}>
              Install the Helix GitHub App to allow Helix to clone repositories, open pull requests, and report CI status on your behalf.
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

      {/* Repos table */}
      {installed && repos.length > 0 && (
        <div style={{
          border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg)',
        }}>
          <div style={{
            display: 'grid', gridTemplateColumns: '1.5fr 110px 140px 1fr 150px',
            gap: 16, padding: '10px 16px',
            background: 'var(--bg-2)', borderBottom: '1px solid var(--line)',
            fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ink-3)',
            letterSpacing: '0.1em', textTransform: 'uppercase',
          }}>
            <span>Repository</span>
            <span>Visibility</span>
            <span>Default branch</span>
            <span>Helix project</span>
            <span style={{ textAlign: 'right' }}>Action</span>
          </div>
          {repos.map(r => (
            <RepoRow
              key={r.full_name}
              repo={r}
              linkedProject={projects.find(p => p.repo === r.full_name)}
              onGo={onGo}
            />
          ))}
        </div>
      )}

      {installed && repos.length === 0 && (
        <div style={{
          border: '1px solid var(--line)', borderRadius: 8, background: 'var(--bg)',
          padding: '32px 24px', textAlign: 'center',
        }}>
          <span className="mono" style={{ fontSize: 12, color: 'var(--ink-3)' }}>no repositories found in this installation</span>
        </div>
      )}
    </div>
  );
}
