import { useState, useRef, useEffect } from 'react';

interface WalkthroughControls {
  go: (page: string) => void;
  setOpenId: (id: string) => void;
  setEditMode: (v: boolean) => void;
  setTour: (v: boolean) => void;
}

export interface WalkthroughHandle {
  step: number;
  caption: string;
  running: boolean;
  run: () => void;
  stop: () => void;
}

export function useWalkthrough(controls: WalkthroughControls): WalkthroughHandle {
  const { go, setOpenId, setEditMode, setTour } = controls;
  const [step, setStep] = useState(-1);
  const [caption, setCaption] = useState('');
  const [running, setRunning] = useState(false);
  const tRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearAll = () => { tRef.current.forEach(clearTimeout); tRef.current = []; };

  const run = () => {
    clearAll();
    setRunning(true);
    setTour(true);
    const schedule = (delay: number, fn: () => void) => {
      tRef.current.push(setTimeout(fn, delay));
    };
    let t = 0;
    schedule(t += 0,    () => { go('list'); setStep(0); setCaption('Helix — your crash-to-PR pipeline'); });
    schedule(t += 3500, () => { setStep(1); setCaption('19 of 23 crashes auto-fixed. 4 need review.'); });
    schedule(t += 3000, () => { setStep(2); setCaption('Opening the AttributeError incident…'); });
    schedule(t += 1200, () => { setOpenId('7e5ebf67-8315-47fb-a49e-5552975b98d3'); go('detail'); });
    schedule(t += 2500, () => { setStep(3); setCaption('Handler → QA → Dev → Human. Every stage, every tool call.'); });
    schedule(t += 3800, () => { setStep(4); setCaption('The agent trace streams live on the right.'); });
    schedule(t += 3500, () => {
      setStep(5);
      setCaption('A real PR, opened by the Dev agent. Approve or request changes.');
      document.querySelector('[data-tour="pr-diff"]')?.scrollIntoView({ behavior:'smooth', block:'center' });
    });
    schedule(t += 4000, () => { go('projects'); setStep(6); setCaption('Projects — one per repo, one webhook URL.'); window.scrollTo({ top:0, behavior:'smooth' }); });
    schedule(t += 3500, () => { setStep(7); setCaption('Secrets, Slack, rotation — all in one drawer.'); });
    schedule(t += 4000, () => { go('github'); setStep(8); setCaption('GitHub App — installed, permissions visible, repos linked.'); window.scrollTo({ top:0, behavior:'smooth' }); });
    schedule(t += 4200, () => { go('list'); setStep(9); setCaption('From crash to PR in 1 minute 28 seconds.'); window.scrollTo({ top:0, behavior:'smooth' }); });
    schedule(t += 3600, () => { setRunning(false); setTour(false); setCaption(''); setStep(-1); });
  };

  // suppress unused warning — controls is used via destructuring above
  void setEditMode;

  const stop = () => { clearAll(); setRunning(false); setTour(false); setCaption(''); setStep(-1); };
  useEffect(() => () => clearAll(), []);

  return { step, caption, running, run, stop };
}

export function WalkthroughOverlay({ caption, running, onStop }: { caption: string; running: boolean; onStop: () => void }) {
  return (
    <>
      {running && caption && (
        <div style={{
          position:'fixed', bottom:40, left:'50%', transform:'translateX(-50%)',
          zIndex:90, padding:'14px 22px',
          background:'oklch(0.18 0.012 260 / 0.92)', color:'oklch(0.96 0.004 85)',
          borderRadius:10, boxShadow:'0 20px 50px oklch(0.18 0.01 260 / 0.28)',
          fontFamily:'var(--serif)', fontSize:22, letterSpacing:'-0.01em',
          backdropFilter:'blur(8px)',
          maxWidth:'min(760px, 80vw)', textAlign:'center',
          border:'1px solid oklch(0.3 0.012 260)',
        }}>
          <span style={{
            display:'inline-block', width:8, height:8, borderRadius:'50%',
            background:'oklch(0.72 0.17 155)', marginRight:10, verticalAlign:'middle',
            animation:'pulse-dot 1.4s ease-in-out infinite',
          }}/>
          {caption}
        </div>
      )}
      {running && (
        <button onClick={onStop} style={{
          position:'fixed', top:12, right:12, zIndex:91,
          fontFamily:'var(--mono)', fontSize:10.5, color:'oklch(0.96 0.004 85)',
          background:'oklch(0.18 0.012 260 / 0.88)',
          padding:'4px 8px', borderRadius:4, border:'1px solid oklch(0.32 0.012 260)',
        }}>stop tour</button>
      )}
    </>
  );
}

export function WalkthroughButton({ onClick, running }: { onClick: () => void; running: boolean }) {
  return (
    <button onClick={onClick} className="mono" disabled={running} style={{
      fontSize:10.5, letterSpacing:'0.06em', padding:'5px 9px', borderRadius:4,
      background: running ? 'var(--bg-3)' : 'var(--bg-2)',
      border:'1px solid var(--line-2)',
      color: running ? 'var(--ink-3)' : 'var(--accent)',
      display:'inline-flex', alignItems:'center', gap:6,
      cursor: running ? 'default' : 'pointer',
    }}>
      <span style={{ width:6, height:6, borderRadius:'50%', background: running ? 'var(--ok)' : 'var(--accent)', animation: running ? 'pulse-dot 1.4s ease-in-out infinite' : 'none' }}/>
      {running ? 'touring…' : '▶ walkthrough'}
    </button>
  );
}
