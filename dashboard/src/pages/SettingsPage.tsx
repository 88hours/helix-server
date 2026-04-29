import { useState, useEffect } from 'react';
import { useSettings } from '../constants';
import { Button, Badge } from '../components/primitives';

interface TextInputProps {
  label: string;
  placeholder?: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  hint?: string;
}

function TextInput({ label, placeholder, value, onChange, type = 'text', hint }: TextInputProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
        {label}
      </span>
      <input
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          fontFamily: 'var(--mono)', fontSize: 11.5,
          padding: '7px 10px', border: '1px solid var(--line-2)',
          borderRadius: 4, background: 'var(--bg-2)', color: 'var(--ink)', outline: 'none',
          width: '100%',
        }}
      />
      {hint && <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>{hint}</span>}
    </div>
  );
}

interface SettingsCardProps {
  title: string;
  children: React.ReactNode;
}

function SettingsCard({ title, children }: SettingsCardProps) {
  return (
    <div style={{ border: '1px solid var(--line-2)', borderRadius: 8, overflow: 'hidden', marginBottom: 20 }}>
      <div style={{ padding: '10px 16px', background: 'var(--bg-2)', borderBottom: '1px solid var(--line)' }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{title}</span>
      </div>
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
        {children}
      </div>
    </div>
  );
}

export function SettingsPage() {
  const { settings, saveSettings } = useSettings();
  const [anthropicKey, setAnthropicKey] = useState('');
  const [openrouterKey, setOpenrouterKey] = useState('');
  const [ollamaUrl, setOllamaUrl] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (settings.anthropic_api_key)   setAnthropicKey(settings.anthropic_api_key === '***' ? '' : (settings.anthropic_api_key ?? ''));
    if (settings.openrouter_api_key)  setOpenrouterKey(settings.openrouter_api_key === '***' ? '' : (settings.openrouter_api_key ?? ''));
    if (settings.ollama_base_url)     setOllamaUrl(settings.ollama_base_url ?? '');
  }, [settings]);

  const handleSave = async () => {
    setSaving(true);
    setError('');
    const updates: Record<string, string> = {};
    if (anthropicKey)  updates.anthropic_api_key  = anthropicKey;
    if (openrouterKey) updates.openrouter_api_key = openrouterKey;
    if (ollamaUrl)     updates.ollama_base_url     = ollamaUrl;

    const ok = await saveSettings(updates);
    setSaving(false);
    if (ok) {
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } else {
      setError('Failed to save. Check server logs.');
    }
  };

  const anthropicSet  = settings.anthropic_api_key  === '***';
  const openrouterSet = settings.openrouter_api_key === '***';

  return (
    <div style={{ padding: '20px 24px', maxWidth: 640, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 20px', fontSize: 17, fontWeight: 600 }}>Settings</h2>

      <SettingsCard title="LLM Providers">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 12.5, fontWeight: 500 }}>Anthropic</span>
          {anthropicSet && <Badge tone="ok">connected</Badge>}
        </div>
        <TextInput
          label="API Key"
          placeholder={anthropicSet ? '••••••••••• (set)' : 'sk-ant-…'}
          value={anthropicKey}
          onChange={setAnthropicKey}
          type="password"
          hint="Used by all agents unless overridden per-project."
        />

        <hr style={{ border: 0, borderTop: '1px solid var(--line)', margin: '4px 0' }}/>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 12.5, fontWeight: 500 }}>OpenRouter</span>
          {openrouterSet && <Badge tone="ok">connected</Badge>}
        </div>
        <TextInput
          label="API Key"
          placeholder={openrouterSet ? '••••••••••• (set)' : 'sk-or-…'}
          value={openrouterKey}
          onChange={setOpenrouterKey}
          type="password"
          hint="Enables access to non-Anthropic models (GPT-4o, Gemini, etc)."
        />

        <hr style={{ border: 0, borderTop: '1px solid var(--line)', margin: '4px 0' }}/>

        <div style={{ fontSize: 12.5, fontWeight: 500, marginBottom: 4 }}>Ollama (local)</div>
        <TextInput
          label="Base URL"
          placeholder="http://localhost:11434"
          value={ollamaUrl}
          onChange={setOllamaUrl}
          hint="Leave blank to disable local model routing."
        />
      </SettingsCard>

      {error && (
        <div style={{ padding: '8px 12px', background: 'oklch(0.95 0.04 25 / 0.5)', border: '1px solid oklch(0.88 0.08 25)', borderRadius: 4, marginBottom: 16 }}>
          <span className="mono" style={{ fontSize: 11, color: 'var(--crash)' }}>{error}</span>
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <Button variant="accent" onClick={handleSave} disabled={saving}>
          {saved ? '✓ saved' : saving ? 'saving…' : 'save settings'}
        </Button>
      </div>
    </div>
  );
}
