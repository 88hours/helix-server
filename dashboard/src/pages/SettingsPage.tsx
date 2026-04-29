import { useState, useEffect } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { useSettings, AGENTS, AgentId } from '../constants';
import { Badge, Button, Icon } from '../components/primitives';

// ---- Primitives ----

function SettingsCard({ id, title, subtitle, footer, children }: {
  id?: string; title: string; subtitle?: string;
  footer?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section id={id ? 'sec-' + id : undefined} style={{
      border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg)',
      scrollMarginTop: 80,
    }}>
      <div style={{
        padding: '12px 16px', borderBottom: '1px solid var(--line)', background: 'var(--bg-2)',
        display: 'flex', alignItems: 'baseline', gap: 10,
      }}>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
          {title}
        </span>
        {subtitle && <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>· {subtitle}</span>}
      </div>
      <div style={{ padding: '16px 18px' }}>{children}</div>
      {footer && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
          borderTop: '1px solid var(--line)', background: 'var(--bg-2)',
        }}>
          {footer}
        </div>
      )}
    </section>
  );
}

function Row({ label, hint, children, align = 'center' }: {
  label: string; hint?: string; children: React.ReactNode; align?: string;
}) {
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '220px 1fr',
      gap: 18, padding: '12px 0', alignItems: align,
      borderTop: '1px solid var(--line)',
    }}>
      <div>
        <div style={{ fontSize: 13, color: 'var(--ink)' }}>{label}</div>
        {hint && <div style={{ fontSize: 11.5, color: 'var(--ink-3)', marginTop: 3, maxWidth: 260, lineHeight: 1.5 }}>{hint}</div>}
      </div>
      <div style={{ minWidth: 0 }}>{children}</div>
    </div>
  );
}

function TextInput({ value, onChange, placeholder, type = 'text', mono, suffix, defaultValue, readOnly }: {
  value?: string; onChange?: (v: string) => void; placeholder?: string;
  type?: string; mono?: boolean; suffix?: string; defaultValue?: string; readOnly?: boolean;
}) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center',
      background: 'var(--bg)', border: '1px solid var(--line-2)', borderRadius: 4,
      paddingLeft: 10, maxWidth: 420,
    }}>
      <input
        type={type}
        value={value}
        defaultValue={defaultValue}
        onChange={e => onChange?.(e.target.value)}
        placeholder={placeholder}
        readOnly={readOnly}
        className={mono ? 'mono' : ''}
        style={{
          flex: 1, border: 0, outline: 'none', background: 'transparent',
          fontSize: 12.5, color: 'var(--ink)', padding: '7px 0',
          fontFamily: mono ? 'var(--mono)' : 'inherit',
        }}
      />
      {suffix && (
        <span className="mono" style={{
          fontSize: 10.5, color: 'var(--ink-3)', padding: '4px 10px',
          borderLeft: '1px solid var(--line-2)',
        }}>{suffix}</span>
      )}
    </div>
  );
}

function Toggle({ on, onClick, label }: { on: boolean; onClick: () => void; label?: string }) {
  return (
    <button onClick={onClick} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
      <span style={{
        width: 28, height: 16, borderRadius: 999,
        background: on ? 'var(--ok)' : 'var(--bg-3)',
        border: '1px solid ' + (on ? 'var(--ok)' : 'var(--line-2)'),
        position: 'relative', transition: 'all 150ms', display: 'block', flexShrink: 0,
      }}>
        <span style={{
          position: 'absolute', top: 1, left: on ? 13 : 1,
          width: 12, height: 12, borderRadius: '50%',
          background: on ? 'var(--bg)' : 'var(--ink-3)',
          transition: 'left 150ms',
        }} />
      </span>
      {label && <span className="mono" style={{ fontSize: 11.5, color: 'var(--ink-2)' }}>{label}</span>}
    </button>
  );
}

function Segment({ value, onChange, options }: {
  value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div style={{
      display: 'inline-flex', padding: 2,
      background: 'var(--bg-2)', border: '1px solid var(--line-2)', borderRadius: 5,
    }}>
      {options.map(o => (
        <button key={o.value} onClick={() => onChange(o.value)} style={{
          fontFamily: 'var(--mono)', fontSize: 11.5,
          padding: '4px 10px', borderRadius: 3,
          color: value === o.value ? 'var(--ink)' : 'var(--ink-3)',
          background: value === o.value ? 'var(--bg)' : 'transparent',
          border: value === o.value ? '1px solid var(--line-2)' : '1px solid transparent',
          cursor: 'pointer',
        }}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ---- Sections ----

function AccountSection() {
  const { user } = useAuth0();
  const name = user?.name ?? 'You';
  const email = user?.email ?? '—';

  return (
    <SettingsCard
      id="account"
      title="Account"
      subtitle={`signed in as ${email}`}
      footer={<>
        <Button variant="primary"><Icon.check size={11} /> save changes</Button>
        <Button variant="ghost">discard</Button>
        <span style={{ flex: 1 }} />
      </>}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, paddingBottom: 8 }}>
        {user?.picture ? (
          <img src={user.picture} alt={name} style={{ width: 56, height: 56, borderRadius: 8, border: '1px solid var(--line-2)', flexShrink: 0 }} />
        ) : (
          <div style={{
            width: 56, height: 56, borderRadius: 8,
            background: 'linear-gradient(135deg, oklch(0.65 0.15 40), oklch(0.55 0.15 280))',
            border: '1px solid var(--line-2)', flexShrink: 0,
          }} />
        )}
        <div>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{name}</div>
          <div className="mono" style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{email}</div>
        </div>
        <span style={{ flex: 1 }} />
        <Button variant="ghost" size="sm">replace avatar</Button>
      </div>

      <Row label="Display name" hint="Shown on PRs, comments and audit log entries.">
        <TextInput defaultValue={name} />
      </Row>
      <Row label="Email" hint="Used for sign-in and approval notifications.">
        <TextInput defaultValue={email} type="email" mono />
      </Row>
      <Row label="Handle" hint="Mentioned by agents in PR descriptions.">
        <TextInput defaultValue={user?.nickname ?? name.split(' ')[0].toLowerCase()} mono suffix="@" />
      </Row>
      <Row label="Timezone">
        <select className="mono" defaultValue="asia/karachi" style={{
          padding: '7px 10px', fontSize: 12.5,
          background: 'var(--bg)', border: '1px solid var(--line-2)', borderRadius: 4, color: 'var(--ink)',
        }}>
          <option value="europe/london">Europe/London (BST · UTC+1)</option>
          <option value="america/new_york">America/New_York (EDT · UTC−4)</option>
          <option value="america/los_angeles">America/Los_Angeles (PDT · UTC−7)</option>
          <option value="asia/karachi">Asia/Karachi (PKT · UTC+5)</option>
        </select>
      </Row>
    </SettingsCard>
  );
}

function OrgSection() {
  const members = [
    { name: 'Nauman Qazi', email: 'nauman.qazi@88hours.co', role: 'admin',    last: '2m ago',    you: true },
    { name: 'Priya Shah',  email: 'priya.shah@88hours.co',  role: 'admin',    last: '1h ago' },
    { name: 'Tom Reyes',   email: 'tom.reyes@88hours.co',   role: 'reviewer', last: 'yesterday' },
    { name: 'Hana Müller', email: 'hana.muller@88hours.co', role: 'reviewer', last: '3 days ago' },
    { name: 'on-call bot', email: 'oncall@88hours.co',      role: 'service',  last: '4m ago' },
  ];

  return (
    <SettingsCard
      id="org"
      title="Organization"
      subtitle="88hours · 5 members · 2 admins"
      footer={<>
        <Button variant="primary"><Icon.bolt size={11} /> invite member</Button>
        <Button variant="ghost">SSO settings</Button>
        <span style={{ flex: 1 }} />
        <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>5 / 10 seats used</span>
      </>}
    >
      <Row label="Workspace name">
        <TextInput defaultValue="88hours" />
      </Row>
      <Row label="Workspace slug" hint="Used in URLs: helix.sh/88hours.">
        <TextInput defaultValue="88hours" mono suffix="helix.sh/" />
      </Row>
      <Row label="Default reviewer" hint="Approves PRs when the originating component has no CODEOWNER.">
        <select defaultValue="nauman" className="mono" style={{
          padding: '7px 10px', fontSize: 12.5,
          background: 'var(--bg)', border: '1px solid var(--line-2)', borderRadius: 4, color: 'var(--ink)',
        }}>
          <option value="nauman">@nauman (you)</option>
          <option value="priya">@priya</option>
          <option value="tom">@tom</option>
        </select>
      </Row>
      <Row label="Members" hint="Who can view incidents and approve agent PRs." align="flex-start">
        <div style={{ border: '1px solid var(--line)', borderRadius: 6, overflow: 'hidden' }}>
          {members.map((m, i) => (
            <div key={m.email} style={{
              display: 'grid', gridTemplateColumns: '1.5fr 1fr 110px 110px',
              gap: 10, padding: '10px 12px', alignItems: 'center',
              borderTop: i === 0 ? 'none' : '1px solid var(--line)',
              background: m.you ? 'var(--bg-2)' : 'transparent',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  width: 22, height: 22, borderRadius: 4,
                  background: m.role === 'service'
                    ? 'oklch(0.92 0.04 70)'
                    : `linear-gradient(135deg, oklch(0.7 0.12 ${i * 60}), oklch(0.55 0.12 ${i * 60 + 120}))`,
                  border: '1px solid var(--line-2)',
                  fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-2)',
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                }}>{m.role === 'service' ? '⚙' : ''}</span>
                <span style={{ fontSize: 12.5 }}>{m.name}{m.you && <span style={{ color: 'var(--ink-3)' }}> · you</span>}</span>
              </div>
              <span className="mono" style={{ fontSize: 11.5, color: 'var(--ink-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.email}</span>
              <Badge tone={m.role === 'admin' ? 'amber' : m.role === 'service' ? 'dim' : 'neutral'}>{m.role}</Badge>
              <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', textAlign: 'right' }}>{m.last}</span>
            </div>
          ))}
        </div>
      </Row>
    </SettingsCard>
  );
}

function AgentBehaviourSection() {
  const [autoMerge, setAutoMerge] = useState(false);
  const [draft, setDraft] = useState(true);
  const [requireTests, setRequireTests] = useState(true);
  const [reanalyse, setReanalyse] = useState(true);
  const [strategy, setStrategy] = useState('test-first');
  const [maxIters, setMaxIters] = useState(3);
  const [maxFiles, setMaxFiles] = useState(8);
  const [escalate, setEscalate] = useState('low_confidence');

  return (
    <SettingsCard
      id="agents"
      title="Agent behaviour"
      subtitle="how agents fix, escalate and stop"
      footer={<>
        <Button variant="primary"><Icon.check size={11} /> save policy</Button>
        <Button variant="ghost">reset to defaults</Button>
        <span style={{ flex: 1 }} />
        <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>applies to all projects · per-project overrides on the project page</span>
      </>}
    >
      <Row label="Fix strategy" hint="Test-first asks the QA agent to write a failing test before any code change.">
        <Segment value={strategy} onChange={setStrategy} options={[
          { value: 'test-first',  label: 'test-first' },
          { value: 'patch-first', label: 'patch-first' },
          { value: 'minimal',     label: 'minimal patch' },
        ]} />
      </Row>
      <Row label="Max TDD iterations" hint="Hard ceiling on rewrite cycles before the dev agent gives up.">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <input type="range" min="1" max="6" step="1" value={maxIters} onChange={e => setMaxIters(+e.target.value)} style={{ width: 180 }} />
          <span className="mono" style={{ fontSize: 13, color: 'var(--ink)', minWidth: 22 }}>{maxIters}</span>
          <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>iterations</span>
        </div>
      </Row>
      <Row label="Max files per patch" hint="Crashes touching more files than this auto-escalate to a human.">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <input type="range" min="1" max="20" step="1" value={maxFiles} onChange={e => setMaxFiles(+e.target.value)} style={{ width: 180 }} />
          <span className="mono" style={{ fontSize: 13, color: 'var(--ink)', minWidth: 22 }}>{maxFiles}</span>
          <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>files</span>
        </div>
      </Row>
      <Row label="Auto-merge approved PRs" hint="When all checks pass and a reviewer approves, merge without waiting.">
        <Toggle on={autoMerge} onClick={() => setAutoMerge(x => !x)} label={autoMerge ? 'on' : 'off'} />
      </Row>
      <Row label="Open PRs as drafts" hint="Recommended while you build trust with the agents.">
        <Toggle on={draft} onClick={() => setDraft(x => !x)} label={draft ? 'on' : 'off'} />
      </Row>
      <Row label="Require new tests" hint="Reject patches that don't add or modify a test.">
        <Toggle on={requireTests} onClick={() => setRequireTests(x => !x)} label={requireTests ? 'required' : 'optional'} />
      </Row>
      <Row label="Re-analyse on duplicate" hint="If a crash dedupes against a closed incident, re-run analysis.">
        <Toggle on={reanalyse} onClick={() => setReanalyse(x => !x)} label={reanalyse ? 'on' : 'off'} />
      </Row>
      <Row label="Escalate when…" hint="Pause and ping a human reviewer instead of opening a PR.">
        <select value={escalate} onChange={e => setEscalate(e.target.value)} className="mono" style={{
          padding: '7px 10px', fontSize: 12.5,
          background: 'var(--bg)', border: '1px solid var(--line-2)', borderRadius: 4, color: 'var(--ink)',
        }}>
          <option value="low_confidence">confidence &lt; 60%</option>
          <option value="touches_migrations">patch touches a migration or schema file</option>
          <option value="prod_only">crash only seen in production</option>
          <option value="never">never (always open a PR)</option>
        </select>
      </Row>
    </SettingsCard>
  );
}

function AgentModelCard({ id, model, rate, budget, passthrough }: {
  id: AgentId; model: string; rate: string; budget: string; passthrough?: boolean;
}) {
  const a = AGENTS[id];
  return (
    <div style={{ border: '1px solid var(--line)', borderRadius: 6, padding: '12px 14px', background: 'var(--bg-2)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{
          width: 22, height: 22, borderRadius: 4,
          background: `color-mix(in oklch, ${a.color} 14%, transparent)`,
          border: `1px solid color-mix(in oklch, ${a.color} 35%, transparent)`,
          color: a.color, fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 700,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }}>{a.symbol}</span>
        <span style={{ fontSize: 13, fontWeight: 500 }}>{a.name}</span>
        {passthrough && <Badge tone="dim">passthrough</Badge>}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {[['model', model], ['rate limit', rate], ['daily budget', budget]].map(([k, v]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '0.06em' }}>{k}</span>
            <span className="mono" style={{ fontSize: 11.5, color: 'var(--ink)' }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ModelsSection() {
  const { settings, saveSettings } = useSettings();
  const [anthropicKey, setAnthropicKey] = useState('');
  const [openrouterKey, setOpenrouterKey] = useState('');
  const [ollamaUrl, setOllamaUrl] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [failover, setFailover] = useState(true);

  useEffect(() => {
    if (settings.anthropic_api_key)  setAnthropicKey(settings.anthropic_api_key === '***' ? '' : (settings.anthropic_api_key ?? ''));
    if (settings.openrouter_api_key) setOpenrouterKey(settings.openrouter_api_key === '***' ? '' : (settings.openrouter_api_key ?? ''));
    if (settings.ollama_base_url)    setOllamaUrl(settings.ollama_base_url ?? '');
  }, [settings]);

  const handleSave = async () => {
    setSaving(true); setError('');
    const updates: Record<string, string> = {};
    if (anthropicKey)  updates.anthropic_api_key  = anthropicKey;
    if (openrouterKey) updates.openrouter_api_key = openrouterKey;
    if (ollamaUrl)     updates.ollama_base_url    = ollamaUrl;
    const ok = await saveSettings(updates);
    setSaving(false);
    if (ok) { setSaved(true); setTimeout(() => setSaved(false), 2000); }
    else setError('Failed to save. Check server logs.');
  };

  const anthropicSet  = settings.anthropic_api_key  === '***';
  const openrouterSet = settings.openrouter_api_key === '***';

  return (
    <SettingsCard
      id="models"
      title="Models & limits"
      subtitle="which model each agent uses, and how much it can spend"
      footer={<>
        <Button variant="primary" onClick={handleSave} disabled={saving}>
          <Icon.check size={11} /> {saved ? 'saved' : saving ? 'saving…' : 'save'}
        </Button>
        <span style={{ flex: 1 }} />
        {error && <span className="mono" style={{ fontSize: 11, color: 'var(--crash)' }}>{error}</span>}
      </>}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 14, marginBottom: 16 }}>
        <AgentModelCard id="handler" model="claude-haiku-4-5"  rate="60 req/min" budget="$120 / day" />
        <AgentModelCard id="qa"      model="claude-sonnet-4-6" rate="20 req/min" budget="$80 / day" />
        <AgentModelCard id="dev"     model="claude-code (CLI)" rate="20 req/min" budget="$200 / day" />
        <AgentModelCard id="human"   model="—" rate="—" budget="—" passthrough />
      </div>

      <Row label="Anthropic API key" hint="Used by the handler and QA agents.">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <TextInput type="password" value={anthropicKey} onChange={setAnthropicKey} placeholder={anthropicSet ? '••••••••••• (set)' : 'sk-ant-…'} mono />
          {anthropicSet && <Badge tone="ok">connected</Badge>}
        </div>
      </Row>
      <Row label="OpenRouter API key" hint="Enables access to non-Anthropic models (GPT-4o, Gemini, etc).">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <TextInput type="password" value={openrouterKey} onChange={setOpenrouterKey} placeholder={openrouterSet ? '••••••••••• (set)' : 'sk-or-…'} mono />
          {openrouterSet && <Badge tone="ok">connected</Badge>}
        </div>
      </Row>
      <Row label="Ollama base URL" hint="Leave blank to disable local model routing.">
        <TextInput value={ollamaUrl} onChange={setOllamaUrl} placeholder="http://localhost:11434" mono />
      </Row>
      <Row label="Hard monthly cap" hint="When this is hit, all agents pause and a human is paged.">
        <TextInput defaultValue="2,400" mono suffix="USD / month" />
      </Row>
      <Row label="Allow vendor failover" hint="If Anthropic is degraded, fall back to a configured alternate provider.">
        <Toggle on={failover} onClick={() => setFailover(x => !x)} label={failover ? 'on' : 'off'} />
      </Row>
    </SettingsCard>
  );
}

function SecuritySection() {
  const [twoFactor] = useState(true);
  const [residency, setResidency] = useState('eu');

  return (
    <SettingsCard
      id="security"
      title="Security"
      subtitle="auth, audit and data residency"
      footer={<>
        <Button variant="ghost"><Icon.refresh size={11} /> rotate workspace key</Button>
        <Button variant="ghost">download audit log (CSV)</Button>
        <span style={{ flex: 1 }} />
      </>}
    >
      <Row label="Two-factor auth" hint="Required for users with the admin role.">
        <Toggle on={twoFactor} onClick={() => {}} label="enforced for admins" />
      </Row>
      <Row label="SSO" hint="Single sign-on via Google Workspace.">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Badge tone="ok">connected</Badge>
          <span className="mono" style={{ fontSize: 11.5, color: 'var(--ink-2)' }}>google · 88hours.co</span>
          <Button variant="ghost" size="sm">reconfigure</Button>
        </div>
      </Row>
      <Row label="Personal access tokens" hint="Used by the Helix CLI and CI integrations." align="flex-start">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[
            { name: 'cli-laptop', scope: 'incidents:read pr:write', last: 'used 4m ago' },
            { name: 'gh-actions', scope: 'incidents:write',         last: 'used 1h ago' },
          ].map(t => (
            <div key={t.name} style={{
              display: 'grid', gridTemplateColumns: '140px 1fr 130px 80px', gap: 10, alignItems: 'center',
              padding: '8px 10px', border: '1px solid var(--line)', borderRadius: 4, background: 'var(--bg-2)',
            }}>
              <span className="mono" style={{ fontSize: 12, color: 'var(--ink)' }}>{t.name}</span>
              <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.scope}</span>
              <span className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>{t.last}</span>
              <Button variant="subtle" size="sm" style={{ color: 'var(--crash)' }}>revoke</Button>
            </div>
          ))}
          <Button variant="ghost" size="sm" style={{ alignSelf: 'flex-start' }}>+ new token</Button>
        </div>
      </Row>
      <Row label="Data residency" hint="Where Helix stores incident bodies and stack traces.">
        <Segment value={residency} onChange={setResidency} options={[{ value: 'us', label: 'US' }, { value: 'eu', label: 'EU' }]} />
      </Row>
      <Row label="Source code retention" hint="How long agent-checked-out repos are kept on disk after a fix.">
        <select defaultValue="24h" className="mono" style={{
          padding: '7px 10px', fontSize: 12.5,
          background: 'var(--bg)', border: '1px solid var(--line-2)', borderRadius: 4, color: 'var(--ink)',
        }}>
          <option value="0">delete immediately</option>
          <option value="1h">1 hour</option>
          <option value="24h">24 hours</option>
          <option value="7d">7 days</option>
        </select>
      </Row>
    </SettingsCard>
  );
}

function BillingSection() {
  return (
    <SettingsCard
      id="billing"
      title="Billing"
      subtitle="team plan · billed monthly"
      footer={<>
        <Button variant="ghost">change plan</Button>
        <Button variant="ghost">download invoices</Button>
        <span style={{ flex: 1 }} />
        <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>next invoice · 01 May 2026</span>
      </>}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12, paddingBottom: 12 }}>
        {[
          { v: '$842.10', l: 'this period',      trend: '+12% vs last' },
          { v: '318',     l: 'incidents handled' },
          { v: '241',     l: 'PRs opened' },
          { v: '$2.65',   l: 'per merged fix',   accent: 'var(--ok)' },
        ].map(s => (
          <div key={s.l} style={{ padding: '10px 12px', border: '1px solid var(--line)', borderRadius: 6, background: 'var(--bg-2)' }}>
            <div className="mono" style={{ fontSize: 22, color: s.accent ?? 'var(--ink)', lineHeight: 1, fontWeight: 500, letterSpacing: '-0.02em' }}>{s.v}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 6, gap: 6 }}>
              <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>{s.l}</span>
              {s.trend && <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>{s.trend}</span>}
            </div>
          </div>
        ))}
      </div>
      <Row label="Plan">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Badge tone="ok">team</Badge>
          <span style={{ fontSize: 12.5 }}>$199 / month · up to 10 seats · unlimited projects</span>
        </div>
      </Row>
      <Row label="Payment method">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ padding: '3px 7px', border: '1px solid var(--line-2)', borderRadius: 3, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-2)', background: 'var(--bg-2)' }}>VISA</span>
          <span className="mono" style={{ fontSize: 12, color: 'var(--ink-2)' }}>•••• 4242 · exp 09/27</span>
          <Button variant="ghost" size="sm">update</Button>
        </div>
      </Row>
      <Row label="Billing email">
        <TextInput defaultValue="finance@88hours.co" type="email" mono />
      </Row>
      <Row label="Tax / VAT id" hint="Appears on each invoice.">
        <TextInput defaultValue="GB 327 1894 02" mono />
      </Row>
      <div style={{ marginTop: 14 }}>
        <div className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 8 }}>
          Recent invoices
        </div>
        <div style={{ border: '1px solid var(--line)', borderRadius: 6, overflow: 'hidden' }}>
          {[
            { date: 'Apr 01 2026', amount: '$842.10' },
            { date: 'Mar 01 2026', amount: '$751.30' },
            { date: 'Feb 01 2026', amount: '$612.90' },
            { date: 'Jan 01 2026', amount: '$199.00' },
          ].map((inv, i) => (
            <div key={inv.date} style={{
              display: 'grid', gridTemplateColumns: '160px 1fr 100px 80px',
              gap: 10, padding: '10px 12px', alignItems: 'center',
              borderTop: i === 0 ? 'none' : '1px solid var(--line)',
            }}>
              <span className="mono" style={{ fontSize: 12, color: 'var(--ink-2)' }}>{inv.date}</span>
              <span style={{ fontSize: 12.5 }}>Helix · team plan</span>
              <span className="mono" style={{ fontSize: 12, color: 'var(--ink)', textAlign: 'right' }}>{inv.amount}</span>
              <Badge tone="ok">paid</Badge>
            </div>
          ))}
        </div>
      </div>
    </SettingsCard>
  );
}

function DangerZoneSection() {
  return (
    <section id="sec-danger" style={{
      border: '1px solid oklch(0.85 0.1 25)', borderRadius: 8, overflow: 'hidden',
      background: 'var(--bg)', scrollMarginTop: 80,
    }}>
      <div style={{ padding: '12px 16px', background: 'oklch(0.97 0.04 25)', borderBottom: '1px solid oklch(0.85 0.1 25)' }}>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.1em', color: 'var(--crash)', textTransform: 'uppercase', fontWeight: 600 }}>
          Danger zone
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {[
          { title: 'Pause all agents', desc: 'Stop the handler, QA and dev agents from picking up new incidents. Existing PRs stay open.', action: 'pause workspace', critical: false },
          { title: 'Reset all webhook secrets', desc: "Rotate every Sentry and Rollbar webhook URL. You'll need to update each integration.", action: 'rotate all', critical: false },
          { title: 'Delete workspace', desc: 'Permanently removes all projects, incidents and audit history. Cannot be undone.', action: 'delete workspace', critical: true },
        ].map(r => (
          <div key={r.title} style={{
            display: 'grid', gridTemplateColumns: '1fr auto', gap: 16,
            padding: '14px 18px', borderTop: '1px solid var(--line)', alignItems: 'center',
          }}>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 500 }}>{r.title}</div>
              <div style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 3, maxWidth: 540, lineHeight: 1.5 }}>{r.desc}</div>
            </div>
            <Button
              variant={r.critical ? 'danger' : 'ghost'}
              size="sm"
              style={!r.critical ? { color: 'var(--crash)', borderColor: 'oklch(0.85 0.1 25)' } : {}}
            >
              {r.action}
            </Button>
          </div>
        ))}
      </div>
    </section>
  );
}

// ---- Page ----

const SECTIONS = [
  { id: 'account', label: 'Account' },
  { id: 'org',     label: 'Organization' },
  { id: 'agents',  label: 'Agent behaviour' },
  { id: 'models',  label: 'Models & limits' },
  { id: 'security',label: 'Security' },
  { id: 'billing', label: 'Billing' },
  { id: 'danger',  label: 'Danger zone' },
];

export function SettingsPage() {
  const [active, setActive] = useState('account');

  const scrollTo = (id: string) => {
    setActive(id);
    const el = document.getElementById('sec-' + id);
    if (el) window.scrollTo({ top: (el as HTMLElement).offsetTop - 70, behavior: 'smooth' });
  };

  return (
    <div style={{ padding: '22px 28px 60px', maxWidth: 1400, margin: '0 auto' }}>

      {/* Hero */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'minmax(0, 1.3fr) minmax(0, 1fr)',
        alignItems: 'end', gap: 32, marginBottom: 22,
      }}>
        <div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>
            Settings · workspace
          </div>
          <h1 style={{ margin: 0, fontFamily: 'var(--serif)', fontWeight: 400, fontSize: 'clamp(28px, 3.4vw, 42px)', lineHeight: 1.05, letterSpacing: '-0.02em' }}>
            How <span style={{ color: 'var(--ink-3)' }}>your agents</span> work,
            <br />
            who they <span style={{ color: 'var(--ok)' }}>answer&nbsp;to.</span>
          </h1>
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', alignItems: 'center' }}>
          <Button variant="ghost" size="sm"><Icon.refresh size={11} /> reload</Button>
        </div>
      </div>

      {/* Two-column layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '200px minmax(0, 1fr)', gap: 22, alignItems: 'flex-start' }}>

        {/* Sticky side nav */}
        <nav style={{
          position: 'sticky', top: 76,
          display: 'flex', flexDirection: 'column', gap: 2,
          padding: 6, border: '1px solid var(--line)', borderRadius: 8, background: 'var(--bg-2)',
        }}>
          {SECTIONS.map(s => (
            <button key={s.id} onClick={() => scrollTo(s.id)} style={{
              fontFamily: 'var(--mono)', fontSize: 11.5, textAlign: 'left',
              padding: '7px 10px', borderRadius: 4, cursor: 'pointer',
              color: active === s.id ? 'var(--ink)' : 'var(--ink-2)',
              background: active === s.id ? 'var(--bg)' : 'transparent',
              border: active === s.id ? '1px solid var(--line-2)' : '1px solid transparent',
            }}>
              {s.label}
            </button>
          ))}
        </nav>

        {/* Content */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
          <AccountSection />
          <OrgSection />
          <AgentBehaviourSection />
          <ModelsSection />
          <SecuritySection />
          <BillingSection />
          <DangerZoneSection />
        </div>
      </div>
    </div>
  );
}
