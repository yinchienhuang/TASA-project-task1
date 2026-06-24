import { useState, useEffect } from 'react';
import { useAppStore } from '../../store/appStore';
import { getFleetEvents, getFleetCoverage } from '../../api/client';
import type { SatelliteEvent, FleetCoverageResult } from '../../api/client';

const REGIONS = [
  { id: 'taiwan', label: 'Taiwan' },
  { id: 'south_china_sea', label: 'South China Sea' },
  { id: 'east_china_sea', label: 'East China Sea' },
  { id: 'korean_peninsula', label: 'Korean Peninsula' },
  { id: 'persian_gulf', label: 'Persian Gulf' },
  { id: 'ukraine', label: 'Ukraine' },
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

const POL_COLOR: Record<string, string> = {
  within_pol: '#3fb950',
  outside_pol: '#f78166',
  return_to_pol: '#58a6ff',
  unknown: '#484f58',
};
const POL_LABEL: Record<string, string> = {
  within_pol: 'Within POL',
  outside_pol: 'Outside POL',
  return_to_pol: 'Return to POL',
  unknown: 'POL unknown',
};
const VERIF_COLOR: Record<string, string> = {
  verified: '#3fb950',
  possible: '#e3b341',
  detected: '#8b949e',
};

function FleetEventQuery() {
  const { setSelectedSatelliteId } = useAppStore();
  const [eventType, setEventType] = useState<string>('');
  const [regime, setRegime] = useState<string>('');
  const [days, setDays] = useState<number>(30);
  const [events, setEvents] = useState<SatelliteEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

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
                <th style={th}>POL</th>
                <th style={th}>Δv / detail</th>
                <th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => {
                const isExpanded = expandedId === ev.id;
                const hasContext = ev.analyst_assessment || ev.pai_summary ||
                  ev.associated_satellite_label || ev.verification_status;
                return (
                  <>
                    <tr key={ev.id}
                      style={{ borderBottom: isExpanded ? 'none' : '1px solid #21262d', cursor: hasContext ? 'pointer' : 'default' }}
                      onClick={() => hasContext && setExpandedId(isExpanded ? null : ev.id)}
                      onMouseEnter={(e) => (e.currentTarget.style.background = '#161b22')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                    >
                      <td style={td}>
                        <span style={{ marginRight: 4, color: '#484f58', fontSize: 9 }}>
                          {hasContext ? (isExpanded ? '▼' : '▶') : ''}
                        </span>
                        {ev.satellite_label || ev.satellite_id}
                        {ev.verification_status && ev.verification_status !== 'verified' && (
                          <span style={{ marginLeft: 5, fontSize: 9, color: VERIF_COLOR[ev.verification_status] }}>
                            [{ev.verification_status}]
                          </span>
                        )}
                      </td>
                      <td style={td}>{fmtDate(ev.event_date)}</td>
                      <td style={td}>
                        <span style={{ color: ev.type === 'launch' ? '#3fb950' : ev.type === 'maneuver' ? '#58a6ff' : '#e3b341' }}>
                          {ev.type}
                        </span>
                        {ev.maneuver_type && <span style={{ color: '#484f58', marginLeft: 4 }}>[{ev.maneuver_type}]</span>}
                      </td>
                      <td style={td}>
                        {ev.pol_status ? (
                          <span style={{ fontSize: 10, color: POL_COLOR[ev.pol_status] }}>
                            {POL_LABEL[ev.pol_status]}
                          </span>
                        ) : '—'}
                      </td>
                      <td style={td}>
                        {ev.type === 'maneuver' ? (
                          <span>
                            {sign(ev.jco_delta_v ?? ev.delta_v)} m/s
                            {ev.discrepancy_flag && <span style={{ color: '#f78166', marginLeft: 4 }}>⚠ TLE discrepancy</span>}
                          </span>
                        ) : ev.type === 'launch' ? (
                          <span>
                            {ev.launch_site && <span style={{ color: '#3fb950' }}>{ev.launch_site}</span>}
                            {ev.launch_vehicle && <span style={{ color: '#8b949e', marginLeft: 6 }}>· {ev.launch_vehicle}</span>}
                            {ev.orbital_inclination != null && (
                              <span style={{ color: '#8b949e', marginLeft: 6 }}>· {ev.orbital_inclination}° / {ev.orbital_period} min</span>
                            )}
                            {!ev.launch_site && !ev.satellite_label && <span style={{ color: '#484f58' }}>NOTAM zone only</span>}
                          </span>
                        ) : (
                          <span>
                            <span style={{ color: ev.magnitude_direction === 'dimmer' ? '#f78166' : '#3fb950', fontWeight: 600, marginRight: 4 }}>
                              {ev.magnitude_direction === 'dimmer' ? '▼' : ev.magnitude_direction === 'brighter' ? '▲' : ''}
                              {ev.magnitude_direction}
                            </span>
                            {(ev.magnitude_change_min != null || ev.magnitude_change_max != null) && (
                              <span style={{ color: '#8b949e' }}>
                                {ev.magnitude_change_min != null && ev.magnitude_change_max != null
                                  ? `${ev.magnitude_change_min}–${ev.magnitude_change_max}`
                                  : ev.magnitude_change_min ?? ev.magnitude_change_max} mag
                              </span>
                            )}
                            {ev.recovery_date && (
                              <span style={{ color: '#3fb950', marginLeft: 6, fontSize: 10 }}>recovered {ev.recovery_date.slice(0, 10)}</span>
                            )}
                          </span>
                        )}
                      </td>
                      <td style={td}>
                        {ev.satellite_id && (
                          <button onClick={(e) => { e.stopPropagation(); setSelectedSatelliteId(ev.satellite_id); }}
                            style={{ ...btnSmall, color: '#58a6ff' }}>
                            Focus
                          </button>
                        )}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr key={ev.id + '_detail'} style={{ borderBottom: '1px solid #21262d' }}>
                        <td colSpan={6} style={{ padding: '0 8px 10px 20px' }}>
                          <div style={{ background: '#0d1117', borderRadius: 4, padding: '8px 10px', fontSize: 11 }}>
                            {ev.analyst_assessment && (
                              <div style={{ marginBottom: 6 }}>
                                <span style={{ color: '#484f58', fontSize: 10, fontWeight: 600, marginRight: 6 }}>ASSESSMENT</span>
                                <span style={{ color: '#c9d1d9', lineHeight: 1.5 }}>{ev.analyst_assessment}</span>
                              </div>
                            )}
                            {ev.associated_satellite_label && (
                              <div style={{ marginBottom: 6 }}>
                                <span style={{ color: '#484f58', fontSize: 10, fontWeight: 600, marginRight: 6 }}>NEARBY SAT</span>
                                <span style={{ color: '#e3b341' }}>{ev.associated_satellite_label}</span>
                                {ev.associated_satellite_id && (
                                  <span style={{ color: '#484f58', marginLeft: 4 }}>({ev.associated_satellite_id})</span>
                                )}
                                {ev.associated_distance_km != null && (
                                  <span style={{ color: '#8b949e', marginLeft: 6 }}>at {ev.associated_distance_km} km</span>
                                )}
                              </div>
                            )}
                            {ev.pai_summary && (
                              <div>
                                <span style={{ color: '#484f58', fontSize: 10, fontWeight: 600, marginRight: 6 }}>PAI</span>
                                <span style={{ color: '#8b949e', lineHeight: 1.5 }}>{ev.pai_summary}</span>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
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

// ── Main panel ────────────────────────────────────────────────────────────────

export default function AnalysisPanel() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0d1117', color: '#e6edf3', overflowY: 'auto' }}>
      <FleetEventQuery />
      <CoverageQuery />
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
