import { authFetch } from '../authFetch';
import { useState, useEffect } from 'react';
import { Project, Incident, useProjects } from '../constants';
import { Badge, Button, Icon, Spark } from '../components/primitives';

// ---- Helpers ----

function Label({ children, small }: { children: React.ReactNode; small?: boolean }) {
  return (
    <div className="mono" style={{
      fontSize: small ? 10 : 10.5, color: 'var(--ink-3)',
      letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 5,
    }}>{children}</div>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 11.5, color: 'var(--ink-3)', marginTop: 5 }}>{children}</div>;
}

function TextInput({ value, onChange, placeholder, mono, type = 'text' }: {
  value: string; onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  placeholder?: string; mono?: boolean; type?: string;
}) {
  return (
    <input
      type={type} value={value} onChange={onChange} placeholder={placeholder}
      className={mono ? 'mono' : ''}
      style={{
        width: '100%', fontFamily: mono ? 'var(--mono)' : 'inherit', fontSize: 12.5,
        padding: '7px 10px', border: '1px solid var(--line-2)', borderRadius: 4,
        background: 'var(--bg)', color: 'var(--ink)', outline: 'none',
      }}
    />
  );
}

function Toggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button onClick={onToggle} style={{
      width: 32, height: 18, borderRadius: 999,
      background: on ? 'var(--ok)' : 'var(--bg-3)',
      border: '1px solid ' + (on ? 'var(--ok)' : 'var(--line-2)'),
      position: 'relative', transition: 'all 150ms', cursor: 'pointer',
      flexShrink: 0,
    }}>
      <span style={{
        position: 'absolute', top: 1, left: on ? 14 : 1,
        width: 14, height: 14, borderRadius: '50%',
        background: on ? 'var(--bg)' : 'var(--ink-3)',
        transition: 'left 150ms',
      }}/>
    </button>
  );
}

function MiniStat({ v, l, c }: { v: number | string; l: string; c?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2, minWidth: 50 }}>
      <span className="mono" style={{ fontSize: 18, color: c ?? 'var(--ink)', lineHeight: 1, fontWeight: 500, letterSpacing: '-0.02em' }}>{v}</span>
      <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.06em' }}>{l}</span>
    </div>
  );
}

// ---- Secret field ----

function SecretField({ label, set, preview, placeholder, onSave }: {
  label: string; set: boolean; preview?: string; placeholder: string;
  onSave?: (val: string) => Promise<boolean>;
}) {
  const [show, setShow] = useState(false);
  const [val, setVal] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    if (!onSave || !val.trim()) return;
    setSaving(true);
    const ok = await onSave(val.trim());
    setSaving(false);
    if (ok) { setSaved(true); setVal(''); setTimeout(() => setSaved(false), 2000); }
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: 'var(--ink)' }}>{label}</span>
        {saved ? <Badge tone="ok">saved!</Badge> : set ? <Badge tone="ok">set</Badge> : null}
      </div>
      <div style={{
        display: 'flex', alignItems: 'center',
        background: 'var(--bg)', border: '1px solid var(--line-2)', borderRadius: 4, paddingLeft: 10,
      }}>
        <input
          type={show ? 'text' : 'password'}
          value={val}
          onChange={e => setVal(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSave()}
          placeholder={set ? '••••••••••' : placeholder}
          className="mono"
          style={{ flex: 1, border: 0, outline: 'none', background: 'transparent', fontSize: 12, color: 'var(--ink)', padding: '7px 0' }}
        />
        <button onClick={() => setShow(s => !s)} className="mono" style={{
          fontSize: 10.5, color: 'var(--ink-3)', padding: '4px 10px',
          borderLeft: '1px solid var(--line-2)', cursor: 'pointer',
        }}>{show ? 'hide' : 'show'}</button>
        {val.trim() && (
          <button onClick={handleSave} disabled={saving} className="mono" style={{
            fontSize: 10.5, color: saving ? 'var(--ink-3)' : 'var(--ok)', padding: '4px 10px',
            borderLeft: '1px solid var(--line-2)', cursor: 'pointer', fontWeight: 600,
          }}>{saving ? '…' : 'save'}</button>
        )}
      </div>
      {set && preview && <div className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', marginTop: 4 }}>{preview}</div>}
    </div>
  );
}

// ---- Notify row ----

interface NotifyField {
  key: string;
  label: string;
  placeholder: string;
  type?: 'text' | 'password';
  initialValue?: string;
}

function NotifyRow({ kind, enabled, detail, fields, onSave }: {
  kind: string; enabled: boolean; detail?: string;
  fields: NotifyField[];
  onSave: (enabled: boolean, values: Record<string, string>) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [on, setOn] = useState(enabled);
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries(fields.map(f => [f.key, f.initialValue ?? '']))
  );
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    const ok = await onSave(on, values);
    setSaving(false);
    if (ok) setEditing(false);
  };

  const handleCancel = () => {
    setOn(enabled);
    setValues(Object.fromEntries(fields.map(f => [f.key, f.initialValue ?? ''])));
    setEditing(false);
  };

  const inputStyle: React.CSSProperties = {
    fontFamily: 'var(--mono)', fontSize: 12, padding: '6px 10px',
    border: '1px solid var(--line-2)', borderRadius: 4, background: 'var(--bg)',
    color: 'var(--ink)', width: '100%', boxSizing: 'border-box',
  };

  return (
    <div style={{ border: '1px solid var(--line)', borderRadius: 6, background: 'var(--bg)', overflow: 'hidden' }}>
      <div style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 500 }}>{kind}</span>
        {(editing ? on : enabled) ? <Badge tone="ok">on</Badge> : <Badge tone="dim">off</Badge>}
        <span style={{ flex: 1 }}/>
        <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {enabled ? (detail || '—') : 'not configured'}
        </span>
        <Button variant="ghost" size="sm" onClick={() => setEditing(e => !e)}>edit</Button>
      </div>
      {editing && (
        <div style={{ padding: '10px 12px', borderTop: '1px solid var(--line)', background: 'var(--bg-2)', display: 'flex', flexDirection: 'column', gap: 8 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, cursor: 'pointer' }}>
            <input type="checkbox" checked={on} onChange={e => setOn(e.target.checked)} />
            Enable {kind} notifications
          </label>
          {on && fields.map(f => (
            <div key={f.key}>
              <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 3, fontFamily: 'var(--mono)' }}>{f.label}</div>
              <input
                type={f.type ?? 'text'}
                value={values[f.key]}
                onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                placeholder={f.placeholder}
                style={inputStyle}
              />
            </div>
          ))}
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="primary" size="sm" disabled={saving} onClick={handleSave}>
              {saving ? 'saving…' : 'save'}
            </Button>
            <Button variant="ghost" size="sm" onClick={handleCancel}>cancel</Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---- Webhook list with copy feedback ----

function WebhookList({ webhooks }: { webhooks: Record<string, string> }) {
  const [copied, setCopied] = useState<string | null>(null);
  const copy = (source: string, url: string) => {
    navigator.clipboard.writeText(url).then(() => {
      setCopied(source);
      setTimeout(() => setCopied(null), 2000);
    });
  };
  return (
    <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
      {Object.entries(webhooks).map(([source, url]) => (
        <div key={source} style={{ display: 'grid', gridTemplateColumns: '100px 1fr auto', gap: 10, alignItems: 'center' }}>
          <Badge tone={source === 'sentry' ? 'violet' : 'amber'}>{source}</Badge>
          <code className="mono" style={{
            fontSize: 11.5, color: 'var(--ink)', padding: '6px 10px',
            background: 'var(--bg)', border: '1px solid var(--line-2)', borderRadius: 4,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>{url}</code>
          <Button variant="ghost" size="sm" onClick={() => copy(source, url)}>
            {copied === source ? '✓ copied' : 'copy'}
          </Button>
        </div>
      ))}
    </div>
  );
}

// ---- Project settings (inline) ----

function ProjectSettings({ p, onSave }: { p: Project; onSave: (s: Record<string, string>) => Promise<boolean> }) {
  const [showHooks, setShowHooks] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    const ok = await onSave({});
    setSaving(false);
    if (ok) { setSaved(true); setTimeout(() => setSaved(false), 2000); }
  };

  return (
    <div style={{ borderTop: '1px solid var(--line)', background: 'var(--bg-2)' }}>
      {/* Webhook URLs */}
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--line)' }}>
        <button onClick={() => setShowHooks(s => !s)} style={{
          display: 'flex', alignItems: 'center', gap: 6,
          fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--accent)', cursor: 'pointer',
        }}>
          <Icon.chev size={10} dir={showHooks ? 'down' : 'right'}/> Webhook URLs
        </button>
        {showHooks && (
          <WebhookList webhooks={p.webhooks} />
        )}
      </div>

      {/* Secrets */}
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--line)' }}>
        <div className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>Secrets</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
          <SecretField label="Anthropic API key"     set={p.secrets.anthropic.set} placeholder="sk-ant-… (falls back to env var)"
            onSave={v => onSave({ anthropic_api_key: v })} />
          <SecretField label="Sentry webhook secret" set={p.secrets.sentry.set}   preview={p.secrets.sentry.preview}   placeholder="whsec_…"
            onSave={v => onSave({ sentry_webhook_secret: v })} />
          <SecretField label="Rollbar access token"  set={p.secrets.rollbar.set}  preview={p.secrets.rollbar.preview}  placeholder="rtp_…"
            onSave={v => onSave({ rollbar_access_token: v })} />
        </div>
      </div>

      {/* Notifications */}
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--line)' }}>
        <div className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>Notifications</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <NotifyRow
            kind="Slack" enabled={p.notify.slack.enabled} detail={p.notify.slack.channel}
            fields={[
              { key: 'slack_bot_token',      label: 'Bot Token',       placeholder: 'xoxb-…',           type: 'password' },
              { key: 'slack_signing_secret', label: 'Signing Secret',  placeholder: 'feb56cbe…',         type: 'password' },
              { key: 'slack_approval_channel', label: 'Approval Channel', placeholder: '#eng-incidents', initialValue: p.notify.slack.channel },
            ]}
            onSave={(en, vals) => {
              const body: Record<string, string> = { slack_approval_channel: en ? (vals.slack_approval_channel || '') : '' };
              if (vals.slack_bot_token)      body.slack_bot_token      = vals.slack_bot_token;
              if (vals.slack_signing_secret) body.slack_signing_secret = vals.slack_signing_secret;
              return onSave(body);
            }}
          />
          <NotifyRow
            kind="Email" enabled={p.notify.email.enabled} detail={p.notify.email.to}
            fields={[
              { key: 'email_to', label: 'Email address', placeholder: 'oncall@example.com', initialValue: p.notify.email.to },
            ]}
            onSave={(en, vals) => onSave({ email_to: en ? (vals.email_to || '') : '' })}
          />
        </div>
      </div>

      {/* Action bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 18px' }}>
        <Button variant="primary" onClick={handleSave} disabled={saving}>
          <Icon.check size={11}/> {saved ? 'saved!' : saving ? 'saving…' : 'save settings'}
        </Button>
        <Button variant="ghost">discard changes</Button>
      </div>
    </div>
  );
}

// ---- Project card ----

function ProjectCard({ p, open, onToggle, onSave, onDelete, stats }: {
  p: Project; open: boolean; onToggle: () => void;
  onSave: (s: Record<string, string>) => Promise<boolean>;
  onDelete: () => void;
  stats: { incidents7d: number; prs7d: number; merged7d: number };
}) {
  return (
    <section style={{ border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg)' }}>
      {p.warning && (
        <div style={{
          padding: '10px 14px', background: 'oklch(0.96 0.06 70)', color: 'oklch(0.35 0.14 50)',
          borderBottom: '1px solid oklch(0.88 0.08 65)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ fontFamily: 'var(--mono)' }}>⚠</span>
          <span>{p.warning}</span>
        </div>
      )}

      <div style={{
        display: 'grid', gridTemplateColumns: 'minmax(0,1.8fr) minmax(0,1fr) auto auto',
        gap: 18, padding: '14px 18px', alignItems: 'center',
      }}>
        {/* Name + badges */}
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em' }}>{p.name}</h3>
            <Badge tone={p.status === 'ready' ? 'ok' : 'dim'}>{p.status}</Badge>
            <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>→ {p.repo}</span>
          </div>
          <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
            <Badge>{p.language}</Badge>
            <Badge>branch: {p.branch}</Badge>
            <Badge tone="ok">github app ✓</Badge>
          </div>
        </div>

        {/* Stats + spark */}
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <MiniStat v={stats.incidents7d} l="incidents" />
          <MiniStat v={stats.prs7d}       l="PRs"       c="var(--ok)" />
          <MiniStat v={stats.merged7d}    l="merged"    c="var(--ok)" />
          {p.activity.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 90 }}>
              <Spark points={p.activity} w={90} h={18} color="var(--accent)" />
              <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.06em' }}>14d activity</span>
            </div>
          )}
        </div>

        <Button variant="ghost" size="sm" onClick={onToggle}>
          <Icon.chev size={10} dir={open ? 'down' : 'right'}/> {open ? 'close' : 'configure'}
        </Button>
        <Button variant="subtle" size="sm" style={{ color: 'var(--crash)' }} onClick={() => {
          if (window.confirm(`Delete project "${p.name}"? This cannot be undone.`)) onDelete();
        }}>delete</Button>
      </div>

      {open && <ProjectSettings p={p} onSave={onSave} />}
    </section>
  );
}

// ---- New project wizard ----

interface WizardData {
  repo: string | null;
  branch: string;
  name: string;
  language: string;
  sources: { sentry: boolean; rollbar: boolean };
  secrets: { sentry: string; rollbar: string };
  notify: { slack: { on: boolean; channel: string }; email: { on: boolean; to: string } };
  autoMerge: boolean;
  draftPRs: boolean;
}

interface GithubRepo {
  full_name: string;
  name: string;
  private: boolean;
  default_branch?: string;
}

const STEPS = [
  { n: 1, label: 'Repository' },
  { n: 2, label: 'Project' },
  { n: 3, label: 'Crash source' },
  { n: 4, label: 'Notifications' },
  { n: 5, label: 'Review' },
];

const STEP_TITLES: Record<number, string> = {
  1: 'Pick a repository to monitor',
  2: 'Name the project',
  3: 'Where do crashes come from?',
  4: 'Who hears about new PRs?',
  5: 'Review and create',
};

function SourceCard({ name, tone, on, onToggle, children }: {
  name: string; tone: string; on: boolean; onToggle: () => void; children?: React.ReactNode;
}) {
  const color = tone === 'violet' ? 'var(--qa)' : 'var(--handler)';
  return (
    <div style={{
      border: on ? `1px solid color-mix(in oklch, ${color} 50%, var(--line-2))` : '1px solid var(--line)',
      borderRadius: 8, padding: 14,
      background: on ? `color-mix(in oklch, ${color} 4%, var(--bg))` : 'var(--bg)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: on ? 12 : 0 }}>
        <Badge tone={tone as 'violet' | 'amber'}>{name.toLowerCase()}</Badge>
        <span style={{ fontSize: 13.5, fontWeight: 500 }}>{name}</span>
        <span style={{ flex: 1 }}/>
        <Toggle on={on} onToggle={onToggle} />
      </div>
      {children}
    </div>
  );
}

function NotifyCard({ kind, on, onToggle, children }: {
  kind: string; on: boolean; onToggle: () => void; children?: React.ReactNode;
}) {
  return (
    <div style={{
      border: '1px solid var(--line)', borderRadius: 8, padding: 14,
      background: on ? 'var(--bg)' : 'var(--bg-2)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: on ? 12 : 0 }}>
        <span style={{ fontSize: 13.5, fontWeight: 500 }}>{kind}</span>
        {on ? <Badge tone="ok">on</Badge> : <Badge tone="dim">off</Badge>}
        <span style={{ flex: 1 }}/>
        <Toggle on={on} onToggle={onToggle} />
      </div>
      {children}
    </div>
  );
}

function DefaultRow({ label, hint, on, onToggle }: { label: string; hint: string; on: boolean; onToggle: () => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <button onClick={onToggle} style={{
        width: 18, height: 18, borderRadius: 4, cursor: 'pointer',
        background: on ? 'var(--accent)' : 'var(--bg)',
        border: '1px solid ' + (on ? 'var(--accent)' : 'var(--line-2)'),
        color: 'var(--bg)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
      }}>
        {on && <Icon.check size={11}/>}
      </button>
      <div>
        <div style={{ fontSize: 12.5, color: 'var(--ink)' }}>{label}</div>
        <div style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{hint}</div>
      </div>
    </div>
  );
}

function ReviewRow({ label, value, mono, accent }: { label: string; value?: string; mono?: boolean; accent?: boolean }) {
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '180px 1fr', gap: 12, padding: '10px 14px',
      borderTop: '1px solid var(--line)', alignItems: 'center',
    }}>
      <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>{label}</span>
      <span className={mono ? 'mono' : ''} style={{ fontSize: 13, color: accent ? 'var(--accent)' : 'var(--ink)' }}>
        {value || <span style={{ color: 'var(--ink-3)' }}>—</span>}
      </span>
    </div>
  );
}

// Step 1
function StepRepo({ data, set, repos, loadingRepos }: {
  data: WizardData; set: (p: Partial<WizardData>) => void;
  repos: GithubRepo[]; loadingRepos: boolean;
}) {
  const [q, setQ] = useState('');
  const filtered = repos.filter(r => r.full_name.toLowerCase().includes(q.toLowerCase()));

  return (
    <div>
      <p style={{ margin: '0 0 14px', fontSize: 13, color: 'var(--ink-2)', maxWidth: 560 }}>
        Helix listens to crashes from this repo and opens PRs back to it. Each repo can only be linked to one project.
      </p>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
        border: '1px solid var(--line-2)', borderRadius: 6, background: 'var(--bg-2)', marginBottom: 12,
      }}>
        <Icon.search size={12}/>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="filter repositories…" className="mono"
          style={{ flex: 1, border: 0, outline: 'none', background: 'transparent', fontSize: 12, color: 'var(--ink)' }}/>
        <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>{filtered.length} available</span>
      </div>
      <div style={{ border: '1px solid var(--line)', borderRadius: 6, overflow: 'hidden' }}>
        {loadingRepos && <div style={{ padding: 24, textAlign: 'center', color: 'var(--ink-3)', fontFamily: 'var(--mono)', fontSize: 12 }}>loading repos…</div>}
        {!loadingRepos && filtered.length === 0 && (
          <div style={{ padding: 24, textAlign: 'center', color: 'var(--ink-3)', fontSize: 13 }}>
            {repos.length === 0 ? 'No GitHub repos found — install the GitHub App first.' : 'No repositories match.'}
          </div>
        )}
        {filtered.map((r, i) => {
          const selected = data.repo === r.full_name;
          return (
            <button key={r.full_name}
              onClick={() => set({ repo: r.full_name, branch: r.default_branch ?? 'main', name: r.name ?? r.full_name.split('/')[1] ?? '' })}
              style={{
                display: 'grid', gridTemplateColumns: '24px 1fr 90px 18px', gap: 12,
                padding: '12px 14px', alignItems: 'center', width: '100%', textAlign: 'left', cursor: 'pointer',
                borderTop: i === 0 ? 'none' : '1px solid var(--line)',
                background: selected ? 'color-mix(in oklch, var(--accent) 8%, var(--bg))' : 'var(--bg)',
              }}
              onMouseEnter={e => { if (!selected) e.currentTarget.style.background = 'var(--bg-2)'; }}
              onMouseLeave={e => { if (!selected) e.currentTarget.style.background = selected ? 'color-mix(in oklch, var(--accent) 8%, var(--bg))' : 'var(--bg)'; }}
            >
              <span style={{
                width: 18, height: 18, borderRadius: '50%',
                border: selected ? '5px solid var(--accent)' : '1.5px solid var(--line-2)',
                background: 'var(--bg)', transition: 'all 120ms',
              }}/>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                <Icon.github size={13}/>
                <span className="mono" style={{ fontSize: 12.5, color: selected ? 'var(--accent)' : 'var(--ink)' }}>{r.full_name}</span>
              </div>
              <Badge tone={r.private ? 'neutral' : 'info'}>{r.private ? 'private' : 'public'}</Badge>
              <span style={{ color: selected ? 'var(--accent)' : 'transparent' }}><Icon.check size={12}/></span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// Step 2
function StepProject({ data, set }: { data: WizardData; set: (p: Partial<WizardData>) => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 560 }}>
      <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-2)' }}>Defaults are taken from your repo — adjust if needed.</p>
      <div>
        <Label>Project name</Label>
        <TextInput value={data.name} onChange={e => set({ name: e.target.value })} placeholder="e.g. payments-api" />
        <Hint>Shown in the navigation and on every PR title.</Hint>
      </div>
      <div>
        <Label>Default branch</Label>
        <TextInput value={data.branch} onChange={e => set({ branch: e.target.value })} mono />
        <Hint>Agents always branch off this and target it for PRs.</Hint>
      </div>
      <div>
        <Label>Language</Label>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {['python', 'typescript', 'javascript', 'go', 'ruby', 'rust', 'java', 'kotlin'].map(l => (
            <button key={l} onClick={() => set({ language: l })} style={{
              fontFamily: 'var(--mono)', fontSize: 11.5, padding: '5px 10px', borderRadius: 4, cursor: 'pointer',
              color: data.language === l ? 'var(--ink)' : 'var(--ink-2)',
              background: data.language === l ? 'var(--bg)' : 'var(--bg-2)',
              border: data.language === l ? '1px solid var(--accent)' : '1px solid var(--line-2)',
            }}>{l}</button>
          ))}
        </div>
        <Hint>Determines which test runner and linter the agents use.</Hint>
      </div>
    </div>
  );
}

// Step 3
function StepSource({ data, set }: { data: WizardData; set: (p: Partial<WizardData>) => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-2)', maxWidth: 580 }}>
        At least one crash source is required — Helix only acts on incidents it receives.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <SourceCard name="Sentry" tone="violet" on={data.sources.sentry}
          onToggle={() => set({ sources: { ...data.sources, sentry: !data.sources.sentry } })}>
          {data.sources.sentry && (
            <>
              <Label small>Webhook secret</Label>
              <TextInput value={data.secrets.sentry} onChange={e => set({ secrets: { ...data.secrets, sentry: e.target.value } })} placeholder="whsec_…" mono />
              <Hint>From Sentry → Settings → Integrations → Webhooks.</Hint>
            </>
          )}
        </SourceCard>
        <SourceCard name="Rollbar" tone="amber" on={data.sources.rollbar}
          onToggle={() => set({ sources: { ...data.sources, rollbar: !data.sources.rollbar } })}>
          {data.sources.rollbar && (
            <>
              <Label small>Access token</Label>
              <TextInput value={data.secrets.rollbar} onChange={e => set({ secrets: { ...data.secrets, rollbar: e.target.value } })} placeholder="rtp_…" mono />
              <Hint>A read access token from your Rollbar project.</Hint>
            </>
          )}
        </SourceCard>
      </div>
      <div style={{ padding: '10px 12px', borderRadius: 6, background: 'var(--bg-2)', border: '1px solid var(--line)', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>i</span>
        <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>You'll get a unique webhook URL per source after creation. Paste it into Sentry / Rollbar to start receiving crashes.</span>
      </div>
    </div>
  );
}

// Step 4
function StepNotify({ data, set }: { data: WizardData; set: (p: Partial<WizardData>) => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 600 }}>
      <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-2)' }}>Where do agent updates land? You can change this anytime.</p>
      <NotifyCard kind="Slack" on={data.notify.slack.on} onToggle={() => set({ notify: { ...data.notify, slack: { ...data.notify.slack, on: !data.notify.slack.on } } })}>
        {data.notify.slack.on && (
          <>
            <Label small>Channel</Label>
            <TextInput value={data.notify.slack.channel} onChange={e => set({ notify: { ...data.notify, slack: { ...data.notify.slack, channel: e.target.value } } })} placeholder="#eng-incidents" mono />
          </>
        )}
      </NotifyCard>
      <NotifyCard kind="Email" on={data.notify.email.on} onToggle={() => set({ notify: { ...data.notify, email: { ...data.notify.email, on: !data.notify.email.on } } })}>
        {data.notify.email.on && (
          <>
            <Label small>Recipients</Label>
            <TextInput value={data.notify.email.to} onChange={e => set({ notify: { ...data.notify, email: { ...data.notify.email, to: e.target.value } } })} placeholder="oncall@88hours.co" mono />
            <Hint>Comma-separated. PR-created and failed-fix events only.</Hint>
          </>
        )}
      </NotifyCard>
      <div style={{ marginTop: 4, padding: '12px 14px', borderRadius: 6, border: '1px solid var(--line)', background: 'var(--bg-2)' }}>
        <div className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 8 }}>Defaults</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <DefaultRow label="Open PRs as drafts" hint="Recommended while you build trust with the agents." on={data.draftPRs} onToggle={() => set({ draftPRs: !data.draftPRs })} />
          <DefaultRow label="Auto-merge approved PRs" hint="Merge once a reviewer approves and CI is green." on={data.autoMerge} onToggle={() => set({ autoMerge: !data.autoMerge })} />
        </div>
      </div>
    </div>
  );
}

// Step 5
function StepReview({ data }: { data: WizardData }) {
  const sources = (Object.entries(data.sources) as [string, boolean][]).filter(([, v]) => v).map(([k]) => k);
  const notifs: string[] = [];
  if (data.notify.slack.on) notifs.push('slack ' + data.notify.slack.channel);
  if (data.notify.email.on) notifs.push('email ' + (data.notify.email.to || '—'));
  return (
    <div>
      <p style={{ margin: '0 0 14px', fontSize: 13, color: 'var(--ink-2)', maxWidth: 560 }}>
        Almost there. We'll generate webhook URLs after creation — copy them into Sentry / Rollbar.
      </p>
      <div style={{ border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg)' }}>
        <ReviewRow label="Repository"     value={data.repo ?? '—'} mono accent />
        <ReviewRow label="Project name"   value={data.name} />
        <ReviewRow label="Default branch" value={data.branch} mono />
        <ReviewRow label="Language"       value={data.language} mono />
        <ReviewRow label="Crash sources"  value={sources.length ? sources.join(' · ') : '— none'} mono />
        <ReviewRow label="Notifications"  value={notifs.length ? notifs.join(' · ') : '— none'} mono />
        <ReviewRow label="Open PRs as drafts"  value={data.draftPRs ? 'yes' : 'no'} />
        <ReviewRow label="Auto-merge approved" value={data.autoMerge ? 'yes' : 'no'} />
      </div>
      <div style={{
        marginTop: 14, padding: '10px 12px', borderRadius: 6,
        background: 'oklch(0.96 0.05 145)', border: '1px solid oklch(0.85 0.1 145)',
        color: 'oklch(0.34 0.12 150)', fontSize: 12.5, display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <Icon.check size={12}/>
        <span>The Crash Handler will start watching as soon as you paste the webhook URLs in.</span>
      </div>
    </div>
  );
}

// New project modal
function NewProjectModal({ onClose, onCreated }: { onClose: () => void; onCreated: (name: string, repo: string) => void }) {
  const [step, setStep] = useState(1);
  const [repos, setRepos] = useState<GithubRepo[]>([]);
  const [loadingRepos, setLoadingRepos] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<WizardData>({
    repo: null, branch: 'main', name: '', language: 'python',
    sources: { sentry: true, rollbar: false },
    secrets: { sentry: '', rollbar: '' },
    notify: { slack: { on: true, channel: '#eng-incidents' }, email: { on: false, to: '' } },
    autoMerge: false, draftPRs: true,
  });

  useEffect(() => {
    authFetch('/api/github/repos')
      .then((r: Response) => r.ok ? r.json() : null)
      .then((d: { repos?: GithubRepo[] } | null) => { if (d?.repos) setRepos(d.repos); setLoadingRepos(false); })
      .catch(() => setLoadingRepos(false));
  }, []);

  const set = (patch: Partial<WizardData>) => setData(d => ({ ...d, ...patch }));

  const canAdvance = () => {
    if (step === 1) return !!data.repo;
    if (step === 2) return (data.name ?? '').trim().length > 0;
    if (step === 3) return data.sources.sentry || data.sources.rollbar;
    return true;
  };

  const handleCreate = async () => {
    setSubmitting(true); setError('');
    const body: Record<string, unknown> = {
      name: data.name, repo: data.repo, base_branch: data.branch, language: data.language,
    };
    if (data.secrets.sentry)           body.sentry_webhook_secret  = data.secrets.sentry;
    if (data.secrets.rollbar)          body.rollbar_access_token   = data.secrets.rollbar;
    if (data.notify.slack.on && data.notify.slack.channel) body.slack_approval_channel = data.notify.slack.channel;
    if (data.notify.email.on && data.notify.email.to)      body.email_to               = data.notify.email.to;
    try {
      const res = await authFetch('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (res.ok) { onCreated(data.name, data.repo ?? ''); onClose(); }
      else { const d = await res.json() as { detail?: string }; setError(d.detail ?? 'Failed to create project'); }
    } catch { setError('Network error'); }
    setSubmitting(false);
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 100,
      background: 'oklch(0.18 0.012 260 / 0.42)', backdropFilter: 'blur(3px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 'min(820px, 100%)', maxHeight: 'calc(100vh - 48px)',
        background: 'var(--bg)', border: '1px solid var(--line-2)', borderRadius: 10,
        boxShadow: '0 30px 80px oklch(0.18 0.01 260 / 0.18)',
        overflow: 'hidden', display: 'flex', flexDirection: 'column',
      }}>
        {/* Header */}
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--line)', background: 'var(--bg-2)', display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ flex: 1 }}>
            <div className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
              New project · step {step} of {STEPS.length}
            </div>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 22, marginTop: 2, letterSpacing: '-0.01em' }}>
              {STEP_TITLES[step]}
            </div>
          </div>
          <button onClick={onClose} style={{
            width: 28, height: 28, borderRadius: 4, color: 'var(--ink-3)', cursor: 'pointer',
            border: '1px solid var(--line-2)', background: 'var(--bg)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          }}><Icon.cross size={11}/></button>
        </div>

        {/* Stepper rail */}
        <div style={{ display: 'flex', gap: 6, padding: '10px 20px', borderBottom: '1px solid var(--line)', background: 'var(--bg)' }}>
          {STEPS.map(s => (
            <div key={s.n} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div style={{ height: 3, borderRadius: 2, background: s.n <= step ? 'var(--accent)' : 'var(--bg-3)' }}/>
              <div className="mono" style={{
                fontSize: 10.5, letterSpacing: '0.04em',
                color: s.n === step ? 'var(--ink)' : s.n < step ? 'var(--ink-2)' : 'var(--ink-3)',
              }}>
                {s.n}. {s.label}
              </div>
            </div>
          ))}
        </div>

        {/* Body */}
        <div style={{ padding: '20px 22px', overflow: 'auto', minHeight: 360 }}>
          {step === 1 && <StepRepo data={data} set={set} repos={repos} loadingRepos={loadingRepos} />}
          {step === 2 && <StepProject data={data} set={set} />}
          {step === 3 && <StepSource data={data} set={set} />}
          {step === 4 && <StepNotify data={data} set={set} />}
          {step === 5 && <StepReview data={data} />}
          {error && <p style={{ margin: '12px 0 0', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--crash)' }}>{error}</p>}
        </div>

        {/* Footer */}
        <div style={{ padding: '12px 20px', borderTop: '1px solid var(--line)', background: 'var(--bg-2)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <Button variant="ghost" size="sm" onClick={onClose}>cancel</Button>
          <span style={{ flex: 1 }}/>
          {step > 1 && <Button variant="ghost" onClick={() => setStep(s => s - 1)}><Icon.chev size={10} dir="left"/> back</Button>}
          {step < STEPS.length && (
            <Button
              variant={canAdvance() ? 'primary' : 'ghost'}
              onClick={() => canAdvance() && setStep(s => s + 1)}
              style={!canAdvance() ? { opacity: 0.5, cursor: 'not-allowed' } : {}}
            >
              continue <Icon.chev size={10} dir="right"/>
            </Button>
          )}
          {step === STEPS.length && (
            <Button variant="accent" onClick={handleCreate} disabled={submitting}>
              <Icon.bolt size={11}/> {submitting ? 'creating…' : 'create project'}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---- Main page ----

export function ProjectsPage({ incidents = [] }: { incidents?: Incident[] }) {
  const { projects, loading, saveProjectSettings, deleteProject, reload } = useProjects();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [created, setCreated] = useState<{ name: string; repo: string } | null>(null);

  // Compute real stats from live incidents, keyed by project_id
  const projectStats = (projectId: string) => {
    const proj = incidents.filter(i => i.project_id === projectId);
    return {
      incidents7d: proj.length,
      prs7d:       proj.filter(i => ['pr', 'approval', 'merged'].includes(i.status)).length,
      merged7d:    proj.filter(i => i.status === 'merged').length,
    };
  };

  const totals = {
    inc:    incidents.length,
    prs:    incidents.filter(i => ['pr', 'approval', 'merged'].includes(i.status)).length,
    merged: incidents.filter(i => i.status === 'merged').length,
  };

  return (
    <div style={{ padding: '22px 28px 60px', maxWidth: 1400, margin: '0 auto' }}>
      {/* Page header */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.3fr) minmax(0,1fr)', alignItems: 'end', gap: 32, marginBottom: 22 }}>
        <div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>
            Projects · {projects.length} configured
          </div>
          <h1 style={{ margin: 0, fontFamily: 'var(--serif)', fontWeight: 400, fontSize: 'clamp(28px, 3.4vw, 42px)', lineHeight: 1.05, letterSpacing: '-0.02em' }}>
            Each project monitors <span style={{ color: 'var(--ink-3)' }}>one repo,</span>
            <br/>owns <span style={{ color: 'var(--ok)' }}>one webhook URL.</span>
          </h1>
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', alignItems: 'center' }}>
          <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>
            Σ {totals.inc} incidents · {totals.prs} PRs · {totals.merged} merged (7d)
          </span>
          <Button variant="primary" onClick={() => setShowNew(true)}>
            <Icon.bolt size={11}/> new project
          </Button>
        </div>
      </div>

      {/* Created banner */}
      {created && (
        <div style={{
          padding: '10px 14px', borderRadius: 6, marginBottom: 14,
          background: 'oklch(0.96 0.05 145)', border: '1px solid oklch(0.85 0.1 145)',
          color: 'oklch(0.34 0.12 150)', fontSize: 12.5, display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <Icon.check size={12}/>
          <span>Project <span className="mono" style={{ fontWeight: 600 }}>{created.name}</span> created · <span className="mono">{created.repo}</span> linked. Copy the webhook URLs from its drawer to start receiving crashes.</span>
          <span style={{ flex: 1 }}/>
          <button onClick={() => setCreated(null)} style={{ color: 'inherit', cursor: 'pointer' }}><Icon.cross size={11}/></button>
        </div>
      )}

      {/* Project cards */}
      {loading ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-3)' }} className="mono">loading…</div>
      ) : projects.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-3)' }} className="mono">
          no projects yet — click "new project" to add one
        </div>
      ) : (() => {
        const orgs = Array.from(new Set(projects.map(p => p.github_org_login ?? '—'))).sort();
        const grouped = orgs.map(org => ({
          org,
          projects: projects.filter(p => (p.github_org_login ?? '—') === org),
        }));
        const showHeaders = orgs.length > 0;
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: showHeaders ? 24 : 14 }}>
            {grouped.map(({ org, projects: group }) => (
              <div key={org}>
                {showHeaders && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                    <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                      {org}
                    </span>
                    <span style={{ flex: 1, height: 1, background: 'var(--line)' }} />
                    <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>{group.length} project{group.length !== 1 ? 's' : ''}</span>
                  </div>
                )}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {group.map(p => (
                    <ProjectCard
                      key={p.id} p={p}
                      open={expanded === p.id}
                      onToggle={() => setExpanded(x => x === p.id ? null : p.id)}
                      onSave={s => saveProjectSettings(p.id, s)}
                      onDelete={() => deleteProject(p.id)}
                      stats={projectStats(p.id)}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        );
      })()}

      {showNew && (
        <NewProjectModal
          onClose={() => setShowNew(false)}
          onCreated={(name, repo) => { setCreated({ name, repo }); setShowNew(false); reload(); }}
        />
      )}
    </div>
  );
}
