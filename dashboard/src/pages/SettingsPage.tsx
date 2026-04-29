import { useState, useEffect } from 'react';
import { useSettings } from '../constants';
import { Badge, Button, Icon } from '../components/primitives';

// ---- Building blocks ----

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

function TextInput({ value, onChange, placeholder, type = 'text' }: {
  value: string; onChange: (v: string) => void; placeholder?: string; type?: string;
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
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="mono"
        style={{
          flex: 1, border: 0, outline: 'none', background: 'transparent',
          fontSize: 12.5, color: 'var(--ink)', padding: '7px 0',
        }}
      />
    </div>
  );
}

// ---- Sections ----

function ModelsSection() {
  const { settings, saveSettings } = useSettings();
  const [anthropicKey, setAnthropicKey] = useState('');
  const [openrouterKey, setOpenrouterKey] = useState('');
  const [ollamaUrl, setOllamaUrl] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

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
      subtitle="LLM provider keys used by agents"
      footer={<>
        <Button variant="primary" onClick={handleSave} disabled={saving}>
          <Icon.check size={11} /> {saved ? 'saved' : saving ? 'saving…' : 'save'}
        </Button>
        <span style={{ flex: 1 }} />
        {error && <span className="mono" style={{ fontSize: 11, color: 'var(--crash)' }}>{error}</span>}
      </>}
    >
      <Row label="Anthropic API key" hint="Used by all agents unless overridden per-project.">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <TextInput
            type="password"
            value={anthropicKey}
            onChange={setAnthropicKey}
            placeholder={anthropicSet ? '••••••••••• (set)' : 'sk-ant-…'}
          />
          {anthropicSet && <Badge tone="ok">connected</Badge>}
        </div>
      </Row>
      <Row label="OpenRouter API key" hint="Enables access to non-Anthropic models (GPT-4o, Gemini, etc).">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <TextInput
            type="password"
            value={openrouterKey}
            onChange={setOpenrouterKey}
            placeholder={openrouterSet ? '••••••••••• (set)' : 'sk-or-…'}
          />
          {openrouterSet && <Badge tone="ok">connected</Badge>}
        </div>
      </Row>
      <Row label="Ollama base URL" hint="Leave blank to disable local model routing.">
        <TextInput
          value={ollamaUrl}
          onChange={setOllamaUrl}
          placeholder="http://localhost:11434"
        />
      </Row>
    </SettingsCard>
  );
}

// ---- Page ----

const SECTIONS = [
  { id: 'models', label: 'Models & limits', active: true },
  { id: 'account',  label: 'Account',          active: false },
  { id: 'org',      label: 'Organization',      active: false },
  { id: 'agents',   label: 'Agent behaviour',   active: false },
  { id: 'security', label: 'Security',          active: false },
  { id: 'billing',  label: 'Billing',           active: false },
  { id: 'danger',   label: 'Danger zone',       active: false },
];

export function SettingsPage() {
  const [active, setActive] = useState('models');

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
            <button key={s.id} onClick={() => s.active && scrollTo(s.id)} style={{
              fontFamily: 'var(--mono)', fontSize: 11.5, textAlign: 'left',
              padding: '7px 10px', borderRadius: 4,
              color: !s.active ? 'var(--ink-3)' : active === s.id ? 'var(--ink)' : 'var(--ink-2)',
              background: active === s.id && s.active ? 'var(--bg)' : 'transparent',
              border: active === s.id && s.active ? '1px solid var(--line-2)' : '1px solid transparent',
              cursor: s.active ? 'pointer' : 'default',
              opacity: s.active ? 1 : 0.45,
            }}>
              {s.label}
            </button>
          ))}
        </nav>

        {/* Content */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
          <ModelsSection />
        </div>
      </div>
    </div>
  );
}
