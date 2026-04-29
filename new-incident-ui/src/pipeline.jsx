/* Swim-lane pipeline — the centerpiece */

function Pipeline({ incident, activeStage }) {
  const agents = ['handler','qa','dev','human'];
  const stages = [
    { agent:'handler', label:'Analyse crash',  detail: 'fingerprint + dedupe', t:'19:01:21', dur:'0.3s' },
    { agent:'qa',      label:'Generate test',  detail: 'reproduces failure',   t:'19:01:22', dur:'5.1s' },
    { agent:'dev',     label:'Author fix',     detail: 'TDD iterate 1/3',      t:'19:01:27', dur:'1m 22s' },
    { agent:'dev',     label:'Open PR',        detail: 'helix/fix/7e5ebf67-1', t:'19:02:49', dur:'' },
    { agent:'human',   label:'Approve',        detail: 'waiting',              t:'—',        dur:'' },
  ];

  const ACTIVE = activeStage ?? incident.currentStage ?? 0;

  return (
    <section style={{
      background: 'var(--bg-2)',
      border: '1px solid var(--line)',
      borderRadius: 8,
      padding: 0,
      overflow: 'hidden',
    }}>
      <Header />
      <div style={{ position:'relative', padding: '18px 22px 22px' }}>
        <Lanes stages={stages} agents={agents} active={ACTIVE} />
      </div>
    </section>
  );

  function Header(){
    return (
      <div style={{
        display:'flex', alignItems:'center', justifyContent:'space-between',
        padding: '10px 14px', borderBottom: '1px solid var(--line)',
        background: 'var(--bg)',
      }}>
        <div style={{ display:'flex', alignItems:'center', gap: 10 }}>
          <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.1em', color:'var(--ink-3)', textTransform:'uppercase' }}>
            Pipeline
          </span>
          <span style={{ width: 3, height: 3, borderRadius: '50%', background: 'var(--ink-3)' }} />
          <span className="mono" style={{ fontSize: 11, color:'var(--ink-2)' }}>
            crash → test → fix → pr → approval
          </span>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap: 8 }}>
          <span className="mono" style={{ fontSize: 10.5, color:'var(--ink-3)' }}>started 19:01:21</span>
          <span style={{ width: 3, height: 3, borderRadius: '50%', background: 'var(--ink-3)' }} />
          <span className="mono" style={{ fontSize: 10.5, color:'var(--ink-2)' }}>elapsed 1m 28s</span>
          <LiveDot />
        </div>
      </div>
    );
  }
}

function LiveDot(){
  return (
    <span style={{ display:'inline-flex', alignItems:'center', gap:5 }}>
      <span style={{
        width:7, height:7, borderRadius:'50%', background:'var(--ok)',
        animation:'pulse-dot 1.6s ease-in-out infinite',
      }}/>
      <span className="mono" style={{ fontSize:10, color:'var(--ok)', letterSpacing:'0.08em', textTransform:'uppercase' }}>live</span>
    </span>
  );
}

function Lanes({ stages, agents, active }) {
  // Layout: each agent owns a horizontal lane. Stages sit on their agent's lane at stage columns.
  const COLS = stages.length;

  return (
    <div style={{ position:'relative' }}>
      {/* Column rail (timestamps at top) */}
      <div style={{
        display:'grid', gridTemplateColumns: `120px repeat(${COLS}, 1fr)`,
        gap: 0, marginBottom: 10,
      }}>
        <div />
        {stages.map((s, i) => (
          <div key={i} style={{ padding: '0 6px' }}>
            <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.06em' }}>
              {String(i+1).padStart(2,'0')} · {s.t}
            </div>
          </div>
        ))}
      </div>

      {agents.map(agentId => {
        const a = window.AGENTS[agentId];
        const laneStages = stages.map((s, i) => ({...s, i})).filter(s => s.agent === agentId);
        return (
          <div key={agentId} style={{
            display:'grid', gridTemplateColumns: `120px repeat(${COLS}, 1fr)`,
            alignItems:'center', position:'relative',
            height: 64,
          }}>
            {/* Lane label */}
            <div style={{
              display:'flex', flexDirection:'column', gap: 2,
              borderRight: '1px dashed var(--line-2)',
              paddingRight: 10, height: '100%', justifyContent:'center',
            }}>
              <AgentChip id={agentId} size="md" />
              <span className="mono" style={{ fontSize: 10, color:'var(--ink-3)' }}>{a.name}</span>
            </div>

            {/* Lane track background */}
            <div style={{
              gridColumn: `2 / span ${COLS}`, gridRow: 1,
              height: 1, background: 'var(--line)',
              alignSelf: 'center', marginLeft: 6, marginRight: 6,
            }}/>

            {/* Stage nodes */}
            {laneStages.map(s => (
              <StageNode key={s.i} stage={s} activeIdx={active} col={s.i + 2} agent={a} />
            ))}
          </div>
        );
      })}

      {/* Flow connectors between stages */}
      <FlowConnectors stages={stages} agents={agents} active={active} cols={stages.length} />
    </div>
  );
}

function StageNode({ stage, activeIdx, col, agent }) {
  const i = stage.i;
  const state = i < activeIdx ? 'done' : i === activeIdx ? 'active' : 'pending';
  const c = agent.color;

  return (
    <div style={{
      gridColumn: col, position:'relative', display:'flex', flexDirection:'column', alignItems:'flex-start',
      gap: 3, padding: '0 6px',
    }}>
      <div style={{
        width: 28, height: 28, borderRadius: 6,
        display:'inline-flex', alignItems:'center', justifyContent:'center',
        background: state === 'pending' ? 'var(--bg-2)' : `color-mix(in oklch, ${c} 14%, transparent)`,
        border: `1.5px solid ${state === 'pending' ? 'var(--line-2)' : c}`,
        color: state === 'pending' ? 'var(--ink-3)' : c,
        fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 700,
        boxShadow: state === 'active' ? `0 0 0 6px color-mix(in oklch, ${c} 12%, transparent)` : 'none',
        animation: state === 'active' ? 'pulse-dot 1.8s ease-in-out infinite' : 'none',
      }}>
        {state === 'done' ? <Icon.check size={13} /> : (i+1)}
      </div>
      <div style={{ marginTop: 2 }}>
        <div className="mono" style={{ fontSize: 11, color: state === 'pending' ? 'var(--ink-3)' : 'var(--ink)', fontWeight: 600 }}>
          {stage.label}
        </div>
        <div className="mono" style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 1 }}>
          {stage.detail}{stage.dur ? ` · ${stage.dur}` : ''}
        </div>
      </div>
    </div>
  );
}

function FlowConnectors({ stages, agents, active, cols }) {
  // We draw SVG connectors between consecutive stages, curving between lanes
  const LANE_H = 64;
  const laneIndex = id => agents.indexOf(id);
  const stageX = (i) => `calc(120px + ${ (i + 0.5) } * ((100% - 120px) / ${cols}) )`;

  return (
    <svg
      aria-hidden
      style={{ position:'absolute', inset: 0, width:'100%', height: `${LANE_H * agents.length}px`, pointerEvents:'none', overflow: 'visible' }}
    >
      <defs>
        <linearGradient id="flow-done" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="var(--ink-2)" stopOpacity="0.35"/>
          <stop offset="100%" stopColor="var(--ink-2)" stopOpacity="0.8"/>
        </linearGradient>
      </defs>
      {stages.slice(0, -1).map((s, i) => {
        const next = stages[i+1];
        const y1 = laneIndex(s.agent) * LANE_H + 14;
        const y2 = laneIndex(next.agent) * LANE_H + 14;
        const state = i < active - 1 ? 'done' : i < active ? 'active' : 'pending';
        const stroke = state === 'done' ? 'url(#flow-done)' : state === 'active'
          ? window.AGENTS[next.agent].color
          : 'var(--line-2)';
        const dash = state === 'pending' ? '3 4' : (state === 'active' ? '0' : '0');
        return (
          <g key={i}>
            <path
              d={`M ${"" /* svg coords via calc won't work; use %*/} `}
              style={{ display:'none' }}
            />
            {/* Use a foreignObject-free approach: draw with percentages via viewBox trick. */}
          </g>
        );
      })}
      {/* Fallback: draw connectors with CSS absolute divs instead */}
      <FlowDivs stages={stages} agents={agents} active={active} cols={cols} />
    </svg>
  );
}

function FlowDivs({ stages, agents, active, cols }) {
  // Position div-based connectors absolutely over the lanes grid.
  // Using container queries would be nicer; we approximate with left/top % offsets.
  const LANE_H = 64;
  const laneIndex = id => agents.indexOf(id);

  return (
    <foreignObject x="0" y="0" width="100%" height={LANE_H * agents.length} style={{ overflow: 'visible' }}>
      <div xmlns="http://www.w3.org/1999/xhtml" style={{ position:'relative', width:'100%', height: LANE_H * agents.length }}>
        {stages.slice(0, -1).map((s, i) => {
          const next = stages[i+1];
          const y1 = laneIndex(s.agent) * LANE_H + 14;
          const y2 = laneIndex(next.agent) * LANE_H + 14;
          const state = i < active - 1 ? 'done' : i < active ? 'active' : 'pending';
          const color = state === 'done'
            ? 'var(--ink-3)'
            : state === 'active'
              ? window.AGENTS[next.agent].color
              : 'var(--line-2)';
          const dashed = state === 'pending';
          const leftPct = `calc(120px + ${(i + 0.5)} * ((100% - 120px) / ${cols}))`;
          const widthPct = `calc(((100% - 120px) / ${cols}))`;
          const top = Math.min(y1, y2);
          const h = Math.abs(y2 - y1);

          if (y1 === y2) {
            return (
              <div key={i} style={{
                position:'absolute', left: leftPct, width: widthPct, top: y1,
                height: 0, borderTop: `1.5px ${dashed ? 'dashed' : 'solid'} ${color}`,
                transform:'translateY(0px)',
              }}/>
            );
          }
          // L-bend: horizontal half, then vertical, then horizontal
          const midLeft = `calc(120px + ${(i + 0.95)} * ((100% - 120px) / ${cols}))`;
          return (
            <React.Fragment key={i}>
              <div style={{
                position:'absolute', left: leftPct, top: y1,
                width: `calc(0.45 * ((100% - 120px) / ${cols}))`, height: 0,
                borderTop: `1.5px ${dashed ? 'dashed' : 'solid'} ${color}`,
              }}/>
              <div style={{
                position:'absolute', left: midLeft, top: top, height: h, width: 0,
                borderLeft: `1.5px ${dashed ? 'dashed' : 'solid'} ${color}`,
              }}/>
              <div style={{
                position:'absolute', left: midLeft, top: y2,
                width: `calc(0.55 * ((100% - 120px) / ${cols}))`, height: 0,
                borderTop: `1.5px ${dashed ? 'dashed' : 'solid'} ${color}`,
              }}/>
            </React.Fragment>
          );
        })}
      </div>
    </foreignObject>
  );
}

Object.assign(window, { Pipeline });
