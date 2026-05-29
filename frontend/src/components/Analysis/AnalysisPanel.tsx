import { useState, useRef, useEffect } from 'react';
import { useAppStore } from '../../store/appStore';
import { getFleetEvents, getFleetCoverage, queryAnalysis } from '../../api/client';
import type { SatelliteEvent, FleetCoverageResult, QueryResult } from '../../api/client';

const REGIONS = [
  { id: 'taiwan', label: 'Taiwan' },
  { id: 'south_china_sea', label: 'South China Sea' },
  { id: 'east_china_sea', label: 'East China Sea' },
  { id: 'korean_peninsula', label: 'Korean Peninsula' },
  { id: 'persian_gulf', label: 'Persian Gulf' },
  { id: 'ukraine', label: 'Ukraine' },
];

const STARTER_QUESTIONS = [
  'List all maneuver events in LEO in the past 30 days',
  'Which Chinese satellites pass over Taiwan most often?',
  'Which Chinese satellites pass over Taiwan most? Have any of them maneuvered recently?',
  'What launches have occurred in the past 60 days?',
];

function fmtDate(iso?: string) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); }
  catch { return iso.slice(0, 10); }
}

function sign(n?: number) {
  if (n == null) return '?';
  return n >= 0 ? `+${n}` : `${n}`;
}

// ── Fleet Event Query ─────────────────────────────────────────────────────────

function FleetEventQuery() {
  const { setSelectedSatelliteId } = useAppStore();
  const [eventType, setEventType] = useState<string>('');
  const [regime, setRegime] = useState<string>('');
  const [days, setDays] = useState<number>(30);
  const [events, setEvents] = useState<SatelliteEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const handleSearch = async () => {
    setLoading(true);
    setSearched(true);
    const result = await getFleetEvents({
      type: eventType || undefined,
      regime: regime || undefined,
      days,
    });
    setEvents(result);
    setLoading(false);
  };

  return (
    <div style={{ padding: '10px 12px' }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#8b949e', marginBottom: 8, letterSpacing: '0.05em' }}>
        FLEET EVENT QUERY
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <select value={eventType} onChange={(e) => setEventType(e.target.value)} style={selectStyle}>
          <option value="">All types</option>
          <option value="maneuver">Maneuver</option>
          <option value="launch">Launch</option>
          <option value="photometric_change">Photometric</option>
        </select>
        <select value={regime} onChange={(e) => setRegime(e.target.value)} style={selectStyle}>
          <option value="">All regimes</option>
          <option value="LEO">LEO</option>
          <option value="MEO">MEO</option>
          <option value="GEO">GEO</option>
          <option value="HEO">HEO</option>
        </select>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} style={selectStyle}>
          <option value={7}>Past 7 days</option>
          <option value={30}>Past 30 days</option>
          <option value={90}>Past 90 days</option>
          <option value={365}>Past year</option>
        </select>
        <button onClick={handleSearch} disabled={loading} style={btnStyle}>
          {loading ? 'Searching…' : 'Search'}
        </button>
      </div>

      {searched && !loading && events.length === 0 && (
        <div style={{ fontSize: 11, color: '#484f58', padding: '8px 0' }}>No events matched your filters.</div>
      )}

      {events.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ color: '#484f58', textAlign: 'left' }}>
                <th style={th}>Satellite</th>
                <th style={th}>Date</th>
                <th style={th}>Type</th>
                <th style={th}>Regime</th>
                <th style={th}>Δv / detail</th>
                <th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => (
                <tr key={ev.id} style={{ borderBottom: '1px solid #21262d' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = '#161b22')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td style={td}>{ev.satellite_label || ev.satellite_id}</td>
                  <td style={td}>{fmtDate(ev.event_date)}</td>
                  <td style={td}>
                    <span style={{ color: ev.type === 'launch' ? '#3fb950' : ev.type === 'maneuver' ? '#58a6ff' : '#e3b341' }}>
                      {ev.type}
                    </span>
                    {ev.maneuver_type && <span style={{ color: '#484f58', marginLeft: 4 }}>[{ev.maneuver_type}]</span>}
                  </td>
                  <td style={td}>{ev.regime || '—'}</td>
                  <td style={td}>
                    {ev.type === 'maneuver'
                      ? `${sign(ev.jco_delta_v ?? ev.delta_v)} m/s${ev.discrepancy_flag ? ' ⚠' : ''}`
                      : ev.type === 'launch'
                        ? ev.launch_site || '—'
                        : `${ev.magnitude_change_min}–${ev.magnitude_change_max} mag`
                    }
                  </td>
                  <td style={td}>
                    {ev.satellite_id && (
                      <button onClick={() => setSelectedSatelliteId(ev.satellite_id)} style={{ ...btnSmall, color: '#58a6ff' }}>
                        Focus
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 10, color: '#484f58', marginTop: 4 }}>{events.length} event{events.length !== 1 ? 's' : ''}</div>
        </div>
      )}
    </div>
  );
}

// ── Coverage Query ────────────────────────────────────────────────────────────

function CoverageQuery() {
  const { setSelectedSatelliteId } = useAppStore();
  const [country, setCountry] = useState('china');
  const [region, setRegion] = useState('taiwan');
  const [days, setDays] = useState(30);
  const [results, setResults] = useState<FleetCoverageResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const handleSearch = async () => {
    setLoading(true);
    setSearched(true);
    const data = await getFleetCoverage({ country, region, days });
    setResults(data);
    setLoading(false);
  };

  return (
    <div style={{ padding: '10px 12px', borderTop: '1px solid #21262d' }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#8b949e', marginBottom: 8, letterSpacing: '0.05em' }}>
        COVERAGE ANALYSIS
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <select value={country} onChange={(e) => setCountry(e.target.value)} style={selectStyle}>
          <option value="china">China</option>
        </select>
        <select value={region} onChange={(e) => setRegion(e.target.value)} style={selectStyle}>
          {REGIONS.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
        </select>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} style={selectStyle}>
          <option value={7}>7 days</option>
          <option value={30}>30 days</option>
          <option value={60}>60 days</option>
        </select>
        <button onClick={handleSearch} disabled={loading} style={btnStyle}>
          {loading ? 'Computing…' : 'Analyze'}
        </button>
      </div>

      {searched && !loading && results.length === 0 && (
        <div style={{ fontSize: 11, color: '#484f58' }}>No satellites with TLEs found for this filter.</div>
      )}

      {results.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ color: '#484f58', textAlign: 'left' }}>
                <th style={th}>Satellite</th>
                <th style={th}>Passes / day</th>
                <th style={th}>Avg duration</th>
                <th style={th}>Revisit (h)</th>
                <th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.norad_id} style={{ borderBottom: '1px solid #21262d' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = '#161b22')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td style={td}>{r.label}</td>
                  <td style={td}><span style={{ color: '#58a6ff' }}>{r.summary.avg_passes_per_day}</span></td>
                  <td style={td}>{r.summary.avg_duration_min} min</td>
                  <td style={td}>{r.summary.revisit_interval_hours ?? '—'}</td>
                  <td style={td}>
                    <button onClick={() => setSelectedSatelliteId(r.node_id || r.norad_id)} style={{ ...btnSmall, color: '#58a6ff' }}>
                      Focus
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 10, color: '#484f58', marginTop: 4 }}>{results.length} satellite{results.length !== 1 ? 's' : ''} with TLEs</div>
        </div>
      )}
    </div>
  );
}

// ── Q&A Chat ──────────────────────────────────────────────────────────────────

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  steps?: QueryResult['steps'];
  warning?: string;
}

function QAChat() {
  const { selectedSatelliteId } = useAppStore();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [expandedStep, setExpandedStep] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const send = async (question: string) => {
    if (!question.trim() || loading) return;
    const q = question.trim();
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: q }]);
    setLoading(true);
    try {
      const result = await queryAnalysis(q, selectedSatelliteId ?? undefined);
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: result.answer,
        steps: result.steps,
        warning: result.warning,
      }]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Error: could not reach analysis API.' }]);
    }
    setLoading(false);
  };

  return (
    <div style={{ borderTop: '1px solid #21262d', display: 'flex', flexDirection: 'column', height: 380 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#8b949e', padding: '8px 12px 4px', letterSpacing: '0.05em' }}>
        Q&A ASSISTANT
      </div>

      {/* Message area */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 12px' }}>
        {messages.length === 0 && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 10, color: '#484f58', marginBottom: 6 }}>Suggested questions:</div>
            {STARTER_QUESTIONS.map((q) => (
              <button key={q} onClick={() => send(q)} style={{
                display: 'block', width: '100%', textAlign: 'left',
                background: 'none', border: '1px solid #30363d', borderRadius: 4,
                color: '#58a6ff', fontSize: 11, padding: '4px 8px', marginBottom: 4, cursor: 'pointer',
              }}>
                {q}
              </button>
            ))}
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: 10 }}>
            {msg.role === 'user' ? (
              <div style={{ background: '#1f6feb22', border: '1px solid #1f6feb44', borderRadius: 6, padding: '6px 10px', fontSize: 12, color: '#e6edf3' }}>
                {msg.content}
              </div>
            ) : (
              <div>
                {/* Reasoning trace */}
                {msg.steps && msg.steps.length > 0 && (
                  <div style={{ marginBottom: 6 }}>
                    {msg.steps.map((step, si) => {
                      const key = `${i}-${si}`;
                      const expanded = expandedStep === key;
                      return (
                        <div key={si} style={{ marginBottom: 3 }}>
                          <button onClick={() => setExpandedStep(expanded ? null : key)} style={{
                            background: '#161b22', border: '1px solid #30363d', borderRadius: 4,
                            color: '#8b949e', fontSize: 10, padding: '2px 8px', cursor: 'pointer', width: '100%', textAlign: 'left',
                          }}>
                            {expanded ? '▼' : '▶'} Step {si + 1}: {step.tool}({Object.entries(step.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ')})
                          </button>
                          {expanded && (
                            <pre style={{
                              margin: 0, padding: '6px 8px', background: '#0d1117', borderRadius: '0 0 4px 4px',
                              fontSize: 10, color: '#8b949e', overflowX: 'auto', maxHeight: 200, overflowY: 'auto',
                              border: '1px solid #30363d', borderTop: 'none',
                            }}>
                              {JSON.stringify(step.result, null, 2)}
                            </pre>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
                {/* Answer */}
                <div style={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 6, padding: '8px 10px', fontSize: 12, color: '#e6edf3', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                  {msg.content}
                </div>
                {msg.warning && <div style={{ fontSize: 10, color: '#f0a500', marginTop: 2 }}>⚠ {msg.warning}</div>}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div style={{ color: '#484f58', fontSize: 11, padding: '6px 0' }}>Analyzing…</div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: '6px 12px', borderTop: '1px solid #21262d', display: 'flex', gap: 6 }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') send(input); }}
          placeholder="Ask about satellites, maneuvers, coverage…"
          disabled={loading}
          style={{
            flex: 1, background: '#161b22', border: '1px solid #30363d', borderRadius: 4,
            color: '#e6edf3', fontSize: 11, padding: '5px 8px', outline: 'none',
          }}
        />
        <button onClick={() => send(input)} disabled={loading || !input.trim()} style={btnStyle}>
          Send
        </button>
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function AnalysisPanel() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0d1117', color: '#e6edf3', overflowY: 'auto' }}>
      <FleetEventQuery />
      <CoverageQuery />
      <QAChat />
    </div>
  );
}

// ── Shared styles ─────────────────────────────────────────────────────────────

const selectStyle: React.CSSProperties = {
  background: '#161b22', border: '1px solid #30363d', borderRadius: 4,
  color: '#e6edf3', fontSize: 11, padding: '3px 6px', outline: 'none',
};

const btnStyle: React.CSSProperties = {
  background: '#1f6feb', border: '1px solid #388bfd', borderRadius: 4,
  color: '#fff', fontSize: 11, padding: '3px 10px', cursor: 'pointer',
};

const btnSmall: React.CSSProperties = {
  background: 'none', border: 'none', fontSize: 10, cursor: 'pointer', padding: '1px 4px',
};

const th: React.CSSProperties = { padding: '3px 8px 5px 0', fontWeight: 600, fontSize: 10, whiteSpace: 'nowrap' };
const td: React.CSSProperties = { padding: '4px 8px 4px 0', whiteSpace: 'nowrap' };
