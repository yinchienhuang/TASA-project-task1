import { useEffect, useRef, useState } from 'react';
import { useAppStore } from '../../store/appStore';

interface Props {
  positionCount: number;
  startTimestamp: number; // unix ms of index 0
  stepMs: number;          // ms per index step (60_000 for 1-min steps)
  nowIndex: number;        // index corresponding to real "now"
}

// Each step = 1 minute = 60 s of simulated time.
// stepsPerSec = simulated-minutes-per-real-second.
const SPEEDS = [
  { label: '1×',   stepsPerSec: 1 / 60   }, // real time
  { label: '5×',   stepsPerSec: 5 / 60   }, // 5× faster
  { label: '30×',  stepsPerSec: 30 / 60  }, // 1 sim-min per 2 real-sec
  { label: '300×', stepsPerSec: 300 / 60 }, // 5 sim-min per real-sec
];

export default function Timeline({ positionCount, startTimestamp, stepMs, nowIndex }: Props) {
  const { currentTimeIndex, setTimeIndex } = useAppStore();
  const [playing, setPlaying] = useState(false);
  const [speedIdx, setSpeedIdx] = useState(0); // default 1× = real time
  const [fracMs, setFracMs] = useState(0);     // fractional ms within current step
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const accRef = useRef(0);

  // Playback interval
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (!playing) { setFracMs(0); return; }

    const stepsPerSec = SPEEDS[speedIdx].stepsPerSec;
    const msPerTick = 100;
    const stepsPerTick = stepsPerSec * msPerTick / 1000;
    accRef.current = 0;

    intervalRef.current = setInterval(() => {
      accRef.current += stepsPerTick;
      const whole = Math.floor(accRef.current);
      if (whole > 0) {
        accRef.current -= whole;
        useAppStore.setState((s) => {
          const next = s.currentTimeIndex + whole;
          return { currentTimeIndex: next >= positionCount ? 0 : next };
        });
      }
      setFracMs(accRef.current * stepMs);
    }, msPerTick);

    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [playing, speedIdx, positionCount, stepMs]);

  // Compute UTC label — interpolate seconds within current step
  const tsMs = startTimestamp + currentTimeIndex * stepMs + (playing ? fracMs : 0);
  const label = new Date(tsMs).toUTCString().replace(' GMT', ' UTC');

  // Recompute where "now" sits on the scrubber every render
  const liveNowIndex = Math.max(0, Math.min(positionCount - 1, Math.round((Date.now() - startTimestamp) / stepMs)));
  const nowPct = positionCount > 1 ? (liveNowIndex / (positionCount - 1)) * 100 : 50;

  return (
    <div style={{
      background: '#0d1117',
      padding: '6px 12px',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      borderTop: '1px solid #30363d',
      height: '100%',
    }}>
      {/* Play / Pause */}
      <button
        onClick={() => setPlaying(p => !p)}
        title={playing ? 'Pause' : 'Play'}
        style={{
          background: playing ? '#238636' : '#21262d',
          border: `1px solid ${playing ? '#2ea043' : '#30363d'}`,
          borderRadius: 6, color: '#e6edf3', cursor: 'pointer',
          padding: '2px 10px', fontSize: 14, lineHeight: 1.6, flexShrink: 0,
        }}
      >
        {playing ? '⏸' : '▶'}
      </button>

      {/* Speed buttons */}
      <div style={{ display: 'flex', gap: 2, flexShrink: 0 }}>
        {SPEEDS.map((s, i) => (
          <button key={s.label} onClick={() => setSpeedIdx(i)} style={{
            background: speedIdx === i ? '#1f6feb' : '#21262d',
            border: `1px solid ${speedIdx === i ? '#388bfd' : '#30363d'}`,
            borderRadius: 4, color: speedIdx === i ? '#fff' : '#8b949e',
            cursor: 'pointer', padding: '1px 7px', fontSize: 11,
          }}>
            {s.label}
          </button>
        ))}
      </div>

      {/* NOW button */}
      <button
        onClick={() => {
          setPlaying(false);
          const liveIdx = Math.round((Date.now() - startTimestamp) / stepMs);
          setTimeIndex(Math.max(0, Math.min(positionCount - 1, liveIdx)));
        }}
        title="Jump to now"
        style={{
          background: '#21262d', border: '1px solid #30363d',
          borderRadius: 4, color: '#f78166', cursor: 'pointer',
          padding: '1px 7px', fontSize: 11, flexShrink: 0,
        }}
      >
        NOW
      </button>

      <span style={{ color: '#8b949e', fontSize: 10, whiteSpace: 'nowrap', flexShrink: 0 }}>-12h</span>

      {/* Scrubber */}
      <div style={{ flex: 1, position: 'relative', minWidth: 0 }}>
        <input
          type="range" min={0} max={positionCount - 1} value={currentTimeIndex}
          onChange={(e) => { setPlaying(false); setTimeIndex(Number(e.target.value)); }}
          style={{ width: '100%', accentColor: '#58a6ff', display: 'block' }}
        />
        {/* "NOW" marker at real current time position */}
        <div style={{
          position: 'absolute', left: `${nowPct}%`, top: -2,
          width: 2, height: 6, background: '#f78166',
          transform: 'translateX(-50%)', pointerEvents: 'none',
        }} />
      </div>

      <span style={{ color: '#8b949e', fontSize: 10, whiteSpace: 'nowrap', flexShrink: 0 }}>+12h</span>

      {/* Timestamp */}
      <span style={{
        color: '#e6edf3', fontSize: 10, fontFamily: 'monospace',
        whiteSpace: 'nowrap', flexShrink: 0, minWidth: 200,
      }}>
        {label}
      </span>
    </div>
  );
}
