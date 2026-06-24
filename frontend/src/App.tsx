import { useEffect, useState, useMemo, useCallback, Component, ReactNode } from 'react';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import EarthView from './components/EarthView/EarthView';
import KGView from './components/KGView/KGView';
import SatellitePanel from './components/SatelliteInfo/SatellitePanel';
import ReportViewer from './components/ReasoningPanel/ReportViewer';
import QueryBox from './components/ReasoningPanel/QueryBox';
import NewsFeed from './components/NewsFeed/NewsFeed';
import KGIngestView from './components/KGIngest/KGIngestView';
import WikiView from './components/Wiki/WikiView';
import AnalysisPanel from './components/Analysis/AnalysisPanel';
import NotamIngestPanel from './components/Notam/NotamIngestPanel';
import AddSatelliteModal from './components/AddSatelliteModal/AddSatelliteModal';
import { useAppStore } from './store/appStore';
import { getKGSatellites, getFleetEvents, enrichSatelliteTags, enrichSatelliteRelations, preloadTLEs } from './api/client';
import type { KGSatellite } from './api/client';

type BottomTab = 'kg' | 'reasoning' | 'news' | 'ingest' | 'wiki' | 'analysis' | 'notam' | 'conjunction';

const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';

export default function App() {
  const [bottomTab, setBottomTab] = useState<BottomTab>('kg');
  const { activeReasoning, selectedSatelliteId } = useAppStore();

  return (
    <div style={{ height: '100vh', background: '#0d1117', fontFamily: FONT, overflow: 'hidden' }}>
      <PanelGroup direction="vertical" style={{ height: '100%' }}>

        {/* ── Top row ── */}
        <Panel defaultSize={50} minSize={20}>
          <PanelGroup direction="horizontal" style={{ height: '100%' }}>

            {/* Earth View */}
            <Panel defaultSize={75} minSize={30}>
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                <PanelHeader title="Earth Orbit View" accent="#58a6ff" />
                <div style={{ flex: 1, overflow: 'hidden' }}>
                  <ErrorBoundaryComponent>
                    <EarthView />
                  </ErrorBoundaryComponent>
                </div>
              </div>
            </Panel>

            <ResizeBar direction="vertical" />

            {/* Satellite Info */}
            <Panel defaultSize={25} minSize={15}>
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%', borderLeft: '1px solid #30363d' }}>
                <PanelHeader title="Satellite Information" accent="#bc8cff" />
                <div style={{ flex: 1, overflowY: 'auto' }}>
                  <SatelliteInfoStatic selected={selectedSatelliteId} />
                </div>
              </div>
            </Panel>

          </PanelGroup>
        </Panel>

        <ResizeBar direction="horizontal" />

        {/* ── Bottom row ── */}
        <Panel defaultSize={50} minSize={20}>
          <PanelGroup direction="horizontal" style={{ height: '100%' }}>

            {/* KG / Reasoning */}
            <Panel defaultSize={75} minSize={30}>
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%', borderTop: '1px solid #30363d' }}>
                <div style={{ display: 'flex', borderBottom: '1px solid #30363d', background: '#161b22' }}>
                  <TabButton active={bottomTab === 'kg'} onClick={() => setBottomTab('kg')}>
                    Knowledge Graph
                  </TabButton>
                  <TabButton active={bottomTab === 'news'} onClick={() => setBottomTab('news')}>
                    News Feed
                  </TabButton>
                  <TabButton active={bottomTab === 'reasoning'} onClick={() => setBottomTab('reasoning')}>
                    <>
                      Reasoning
                      {activeReasoning && (
                        <span style={{ background: '#f78166', color: '#0d1117', borderRadius: 10, padding: '0 6px', fontSize: 10, marginLeft: 6 }}>!</span>
                      )}
                    </>
                  </TabButton>
                  <TabButton active={bottomTab === 'ingest'} onClick={() => setBottomTab('ingest')}>
                    KG Ingest
                  </TabButton>
                  <TabButton active={bottomTab === 'wiki'} onClick={() => setBottomTab('wiki')}>
                    Wikipedia
                  </TabButton>
                  <TabButton active={bottomTab === 'analysis'} onClick={() => setBottomTab('analysis')}>
                    Analysis
                  </TabButton>
                  <TabButton active={bottomTab === 'notam'} onClick={() => setBottomTab('notam')}>
                    NOTAM
                  </TabButton>
                  <TabButton active={bottomTab === 'conjunction'} onClick={() => setBottomTab('conjunction')}>
                    Conjunctions
                  </TabButton>
                </div>
                <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
                  <div style={{ position: 'absolute', inset: 0, display: bottomTab === 'kg' ? 'block' : 'none' }}>
                    <KGView />
                  </div>
                  <div style={{ position: 'absolute', inset: 0, display: bottomTab === 'news' ? 'block' : 'none' }}>
                    <NewsFeed />
                  </div>
                  <div style={{ position: 'absolute', inset: 0, display: bottomTab === 'reasoning' ? 'flex' : 'none', flexDirection: 'column', overflowY: 'auto', background: '#161b22' }}>
                    <ReportViewer />
                  </div>
                  <div style={{ position: 'absolute', inset: 0, display: bottomTab === 'ingest' ? 'flex' : 'none' }}>
                    <KGIngestView />
                  </div>
                  <div style={{ position: 'absolute', inset: 0, display: bottomTab === 'wiki' ? 'flex' : 'none' }}>
                    <WikiView />
                  </div>
                  <div style={{ position: 'absolute', inset: 0, display: bottomTab === 'analysis' ? 'flex' : 'none', flexDirection: 'column', overflowY: 'auto' }}>
                    <AnalysisPanel />
                  </div>
                  <div style={{ position: 'absolute', inset: 0, display: bottomTab === 'notam' ? 'flex' : 'none', flexDirection: 'column' }}>
                    <NotamIngestPanel />
                  </div>
                  <div style={{ position: 'absolute', inset: 0, display: bottomTab === 'conjunction' ? 'flex' : 'none', flexDirection: 'column' }}>
                    <ConjunctionMonitor />
                  </div>
                </div>
              </div>
            </Panel>

            <ResizeBar direction="vertical" />

            {/* QA Assistant */}
            <Panel defaultSize={25} minSize={15}>
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%', borderTop: '1px solid #30363d', borderLeft: '1px solid #30363d' }}>
                <PanelHeader title="QA Assistant" accent="#bc8cff" />
                <QueryBox />
              </div>
            </Panel>

          </PanelGroup>
        </Panel>

      </PanelGroup>

      <SatellitePanel />
    </div>
  );
}

// ── Drag handle ──────────────────────────────────────────────────────────────

function ResizeBar({ direction }: { direction: 'horizontal' | 'vertical' }) {
  const isH = direction === 'horizontal';
  return (
    <PanelResizeHandle style={{
      background: '#21262d',
      flexShrink: 0,
      width: isH ? '100%' : 5,
      height: isH ? 5 : '100%',
      cursor: isH ? 'row-resize' : 'col-resize',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      transition: 'background 0.15s',
    }}
    >
      {/* Grip dots */}
      {isH
        ? <div style={{ width: 32, height: 3, borderRadius: 2, background: '#484f58' }} />
        : <div style={{ width: 3, height: 32, borderRadius: 2, background: '#484f58' }} />
      }
    </PanelResizeHandle>
  );
}

// ── Shared sub-components ────────────────────────────────────────────────────

function PanelHeader({ title, accent }: { title: string; accent: string }) {
  return (
    <div style={{
      height: 36, padding: '0 16px', display: 'flex', alignItems: 'center',
      background: '#161b22', borderBottom: '1px solid #30363d', flexShrink: 0,
    }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: accent, marginRight: 8, display: 'inline-block' }} />
      <span style={{ color: '#e6edf3', fontSize: 13, fontWeight: 600 }}>{title}</span>
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} style={{
      background: 'none', border: 'none', cursor: 'pointer',
      padding: '8px 16px', fontSize: 13,
      color: active ? '#58a6ff' : '#8b949e',
      borderBottom: active ? '2px solid #58a6ff' : '2px solid transparent',
      display: 'flex', alignItems: 'center',
    }}>
      {children}
    </button>
  );
}

const SAT_TYPE_COLOR: Record<string, string> = {
  CivilSatellite: '#58a6ff',
  MilitarySatellite: '#f78166',
  CommercialSatellite: '#3fb950',
  Satellite: '#8b949e',
};

function satColor(type: string, inferred: string[]): string {
  for (const t of [type, ...inferred]) {
    if (SAT_TYPE_COLOR[t]) return SAT_TYPE_COLOR[t];
  }
  return '#8b949e';
}

function getSatTypeTag(sat: KGSatellite): 'Military' | 'Civil' | 'Commercial' | null {
  const all = [sat.type, ...sat.inferred_types];
  if (all.some((t) => t === 'MilitarySatellite')) return 'Military';
  if (all.some((t) => t === 'CivilSatellite')) return 'Civil';
  if (all.some((t) => t === 'CommercialSatellite')) return 'Commercial';
  return null;
}

function normalizeCountryName(country: string): string {
  // Normalize common country name variants
  const normalized: Record<string, string> = {
    'usa': 'USA',
    'u.s.a': 'USA',
    'united states': 'USA',
    'united states of america': 'USA',
    'ussr': 'Russia',
    'soviet union': 'Russia',
  };
  const key = country.toLowerCase().trim();
  return normalized[key] || country;
}

function getSatCountry(sat: KGSatellite): string | null {
  for (const key of ['country', 'operator_country', 'country_of_operator']) {
    const raw = sat.attributes[key];
    if (!raw) continue;
    const val = typeof raw === 'object' && raw !== null && 'value' in raw
      ? (raw as { value: unknown }).value : raw;
    if (val && String(val).trim()) return normalizeCountryName(String(val).trim());
  }
  return null;
}

function SatelliteInfoStatic({ selected }: { selected: string | null }) {
  const { selectSatellite } = useAppStore();
  const [satellites, setSatellites] = useState<KGSatellite[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<{ text: string; color: string } | null>(null);
  const [enriching, setEnriching] = useState(false);
  const [enrichingRel, setEnrichingRel] = useState(false);
  const [activeFilter, setActiveFilter] = useState<string | null>(null);
  const [recentActivity, setRecentActivity] = useState<Map<string, { date: string; type: string }>>(new Map());

  const reload = () => {
    setLoading(true);
    getKGSatellites().then((sats) => {
      setSatellites(sats);
      setLoading(false);
      // Optional: Preload TLE data for all satellites in background
      // Uncomment the lines below to enable TLE preloading on startup
      // const noradIds = sats.filter(s => s.noradId).map(s => s.noradId as string);
      // if (noradIds.length > 0) {
      //   preloadTLEs(noradIds);
      // }
    });
  };

  const fetchActivity = () => {
    getFleetEvents({ days: 30 }).then((events) => {
      const map = new Map<string, { date: string; type: string }>();
      const sorted = [...events].sort((a, b) => b.event_date.localeCompare(a.event_date));
      for (const ev of sorted) {
        if (!map.has(ev.satellite_id)) map.set(ev.satellite_id, { date: ev.event_date, type: ev.type });
      }
      setRecentActivity(map);
    });
  };

  const handleRefreshTLEs = async () => {
    setRefreshing(true);
    setRefreshMsg({ text: 'Fetching TLEs…', color: '#e3b341' });
    try {
      const r = await fetch('http://localhost:8000/api/propagation/tle/refresh-all', { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      const updated = data.results.filter((x: { status: string }) => x.status === 'updated').length;
      const errors = data.results.filter((x: { status: string }) => x.status === 'error').length;
      if (errors > 0) {
        setRefreshMsg({ text: `${updated} updated, ${errors} failed`, color: '#e3b341' });
      } else {
        setRefreshMsg({ text: `${updated}/${data.results.length} TLEs updated`, color: '#3fb950' });
      }
    } catch {
      setRefreshMsg({ text: 'Refresh failed', color: '#f78166' });
    }
    setRefreshing(false);
    reload();
    setTimeout(() => setRefreshMsg(null), 4000);
  };

  const handleEnrichTags = async () => {
    setEnriching(true);
    setRefreshMsg({ text: 'Enriching tags…', color: '#e3b341' });
    try {
      const result = await enrichSatelliteTags();
      if (result.proposed === 0) {
        setRefreshMsg({ text: 'All tags already complete', color: '#3fb950' });
      } else {
        setRefreshMsg({ text: `${result.proposed} proposals added to Pending Review`, color: '#3fb950' });
      }
    } catch {
      setRefreshMsg({ text: 'Enrichment failed', color: '#f78166' });
    }
    setEnriching(false);
    setTimeout(() => setRefreshMsg(null), 5000);
  };

  const handleEnrichRelations = async () => {
    setEnrichingRel(true);
    setRefreshMsg({ text: 'Building relations…', color: '#e3b341' });
    try {
      const result = await enrichSatelliteRelations();
      if (result.proposed === 0) {
        setRefreshMsg({ text: 'All relations already complete', color: '#3fb950' });
      } else {
        setRefreshMsg({ text: `${result.edges} edges · ${result.nodes} nodes → Pending Review`, color: '#3fb950' });
      }
    } catch {
      setRefreshMsg({ text: 'Relation enrichment failed', color: '#f78166' });
    }
    setEnrichingRel(false);
    setTimeout(() => setRefreshMsg(null), 5000);
  };

  useEffect(() => { reload(); fetchActivity(); }, []);

  // Derive filter chip sets from actual data
  const { typeChips, countryChips } = useMemo(() => {
    const types = new Set<string>();
    const countries = new Set<string>();
    for (const sat of satellites) {
      const t = getSatTypeTag(sat);
      if (t) types.add(t);
      const c = getSatCountry(sat);
      if (c) countries.add(c);
    }
    return {
      typeChips: (['Military', 'Civil', 'Commercial'] as const).filter((t) => types.has(t)),
      countryChips: Array.from(countries).sort(),
    };
  }, [satellites]);

  // Filtered + sorted list — active event first, then by recency
  const displaySats = useMemo(() => {
    let sats = satellites;
    if (activeFilter) {
      sats = sats.filter((sat) =>
        getSatTypeTag(sat) === activeFilter || getSatCountry(sat) === activeFilter
      );
    }
    return [...sats].sort((a, b) => {
      const aAct = recentActivity.get(a.nodeId);
      const bAct = recentActivity.get(b.nodeId);
      if (aAct && !bAct) return -1;
      if (!aAct && bAct) return 1;
      if (aAct && bAct) return bAct.date.localeCompare(aAct.date);
      return a.name.localeCompare(b.name);
    });
  }, [satellites, activeFilter, recentActivity]);

  const TYPE_CHIP_COLOR: Record<string, string> = {
    Military: '#f78166',
    Civil: '#58a6ff',
    Commercial: '#3fb950',
  };

  return (
    <div style={{ padding: 12, color: '#8b949e', fontSize: 13 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ color: '#484f58', fontSize: 11, letterSpacing: '0.05em' }}>
          KG SATELLITES {!loading && (
            <span style={{ color: '#30363d' }}>
              ({displaySats.length}{activeFilter ? `/${satellites.length}` : ''})
            </span>
          )}
        </span>
        <button
          onClick={() => setShowAddModal(true)}
          style={{
            background: 'none', border: '1px solid #30363d', borderRadius: 4,
            color: '#58a6ff', cursor: 'pointer', fontSize: 11, padding: '2px 8px',
          }}
        >+ Add</button>
      </div>

      {/* TLE refresh + auto-fill tags */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
        <button
          onClick={handleRefreshTLEs}
          disabled={refreshing}
          style={{
            flex: 1, background: 'none',
            border: '1px solid #30363d', borderRadius: 4,
            color: refreshing ? '#484f58' : '#8b949e', cursor: refreshing ? 'default' : 'pointer',
            fontSize: 11, padding: '4px 8px', textAlign: 'left',
          }}
        >
          {refreshing ? '⟳ …' : '⟳ Refresh TLEs'}
        </button>
        <button
          onClick={handleEnrichTags}
          disabled={enriching}
          title="Auto-fill missing type/country tags using UCS database and KG relationships"
          style={{
            flex: 1, background: 'none',
            border: '1px solid #30363d', borderRadius: 4,
            color: enriching ? '#484f58' : '#e3b341', cursor: enriching ? 'default' : 'pointer',
            fontSize: 11, padding: '4px 8px', textAlign: 'left',
          }}
        >
          {enriching ? '✦ …' : '✦ Tags'}
        </button>
        <button
          onClick={handleEnrichRelations}
          disabled={enrichingRel}
          title="Auto-propose missing launchedFrom / operatedBy / manufacturedBy edges from UCS database"
          style={{
            flex: 1, background: 'none',
            border: '1px solid #30363d', borderRadius: 4,
            color: enrichingRel ? '#484f58' : '#bc8cff', cursor: enrichingRel ? 'default' : 'pointer',
            fontSize: 11, padding: '4px 8px', textAlign: 'left',
          }}
        >
          {enrichingRel ? '⟢ …' : '⟢ Relations'}
        </button>
        <button
          onClick={async () => {
            setEnriching(true);
            setRefreshMsg({ text: 'Normalizing country names…', color: '#e3b341' });
            try {
              const r = await fetch('http://localhost:8000/api/kg/normalize/country-names', { method: 'POST' });
              const data = await r.json();
              setRefreshMsg({ text: `${data.count} nodes normalized`, color: '#3fb950' });
              reload();
            } catch {
              setRefreshMsg({ text: 'Normalization failed', color: '#f78166' });
            }
            setEnriching(false);
            setTimeout(() => setRefreshMsg(null), 3000);
          }}
          disabled={enriching}
          title="Normalize country name variants (USA ↔ United States, etc.)"
          style={{
            flex: 1, background: 'none',
            border: '1px solid #30363d', borderRadius: 4,
            color: enriching ? '#484f58' : '#bc8cff', cursor: enriching ? 'default' : 'pointer',
            fontSize: 11, padding: '4px 8px', textAlign: 'left',
          }}
        >
          {enriching ? '± …' : '± Countries'}
        </button>
      </div>
      {refreshMsg && (
        <div style={{ fontSize: 11, color: refreshMsg.color, marginBottom: 6 }}>{refreshMsg.text}</div>
      )}

      {/* Filter chips */}
      {(typeChips.length > 0 || countryChips.length > 0) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
          {[...typeChips, ...countryChips].map((chip) => {
            const active = activeFilter === chip;
            const color = TYPE_CHIP_COLOR[chip] ?? '#8b949e';
            return (
              <button
                key={chip}
                onClick={() => setActiveFilter(active ? null : chip)}
                style={{
                  background: active ? color + '22' : 'none',
                  border: `1px solid ${active ? color : '#30363d'}`,
                  borderRadius: 10, padding: '1px 8px', fontSize: 10,
                  color: active ? color : '#8b949e',
                  cursor: 'pointer', fontFamily: 'inherit', fontWeight: active ? 600 : 400,
                }}
              >
                {chip}
              </button>
            );
          })}
          {activeFilter && (
            <button
              onClick={() => setActiveFilter(null)}
              style={{
                background: 'none', border: '1px solid #30363d', borderRadius: 10,
                padding: '1px 6px', fontSize: 10, color: '#484f58',
                cursor: 'pointer', fontFamily: 'inherit',
              }}
            >✕</button>
          )}
        </div>
      )}

      {showAddModal && (
        <AddSatelliteModal onClose={() => setShowAddModal(false)} onAdded={reload} />
      )}

      {/* Satellite list */}
      {loading ? (
        <div style={{ color: '#484f58', fontSize: 12, padding: '8px 0' }}>Loading…</div>
      ) : displaySats.length === 0 ? (
        <div style={{ color: '#484f58', fontSize: 12 }}>
          {activeFilter ? 'No satellites match filter.' : 'No satellites in KG yet. Approve satellite nodes in KG Ingest.'}
        </div>
      ) : displaySats.map((sat) => {
        const color = satColor(sat.type, sat.inferred_types);
        const isSelected = selected === sat.noradId || selected === sat.nodeId;
        const activity = recentActivity.get(sat.nodeId);
        const daysAgo = activity
          ? Math.floor((Date.now() - new Date(activity.date).getTime()) / 86_400_000)
          : null;
        return (
          <div
            key={sat.nodeId}
            onClick={() => selectSatellite(isSelected ? null : (sat.noradId ?? sat.nodeId))}
            style={{
              background: isSelected ? '#0d2133' : '#0d1117',
              borderRadius: 6, padding: '8px 10px', marginBottom: 6,
              border: `1px solid ${isSelected ? color : color + '44'}`,
              cursor: 'pointer', transition: 'background 0.1s',
              display: 'flex', alignItems: 'center', gap: 8,
            }}
            onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = '#161b22'; }}
            onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.background = '#0d1117'; }}
          >
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ color: '#e6edf3', fontSize: 12, fontWeight: isSelected ? 600 : 400, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {sat.name}
              </div>
              <div style={{ color: '#484f58', fontSize: 10, marginTop: 1 }}>
                {sat.noradId ? `${sat.noradId} · ${sat.type}` : sat.type}
              </div>
            </div>
            {activity && (
              <div style={{ flexShrink: 0, textAlign: 'right' }}>
                <span style={{
                  display: 'inline-block',
                  background: activity.type === 'maneuver' ? '#e3b34122' : '#bc8cff22',
                  border: `1px solid ${activity.type === 'maneuver' ? '#e3b341' : '#bc8cff'}`,
                  borderRadius: 3, padding: '0 4px', fontSize: 9,
                  color: activity.type === 'maneuver' ? '#e3b341' : '#bc8cff',
                }}>
                  {activity.type === 'maneuver' ? 'M' : 'Δ'}
                </span>
                <div style={{ fontSize: 9, color: '#484f58', marginTop: 1 }}>
                  {daysAgo === 0 ? 'today' : `${daysAgo}d ago`}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

interface Conjunction {
  primary_sat?: string;
  norad_id_2?: string;
  tca: string;
  min_distance_km: number;
  probability?: number;
}

interface TaiwanSat {
  norad_id: string;
  label: string;
  node_id: string;
}

class ErrorBoundaryComponent extends Component<{ children: ReactNode }, { hasError: boolean; error?: Error }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error) {
    console.error('[ErrorBoundary] EarthView error:', error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          height: '100%', background: '#0d1117', color: '#8b949e', fontSize: 12,
          flexDirection: 'column', gap: 8,
        }}>
          <div>🛰️ Earth View crashed</div>
          <div style={{ fontSize: 11, color: '#484f58' }}>Check console for details</div>
          <button
            onClick={() => window.location.reload()}
            style={{
              background: '#238636', border: 'none', borderRadius: 4,
              color: '#fff', padding: '4px 12px', cursor: 'pointer', fontSize: 11,
            }}
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function ConjunctionMonitor() {
  const [conjunctions, setConjunctions] = useState<Conjunction[]>([]);
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState(30);
  const [minDistance, setMinDistance] = useState(100);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [taiwanSats, setTaiwanSats] = useState<TaiwanSat[]>([]);
  const [selectedSat, setSelectedSat] = useState<string>('all-satellites');
  const [manualNoradId, setManualNoradId] = useState<string>('');

  // Load list of all satellites with NORAD IDs
  useEffect(() => {
    const loadSats = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/analysis/conjunction/satellites', { signal: AbortSignal.timeout(5000) });
        if (res.ok) {
          const data = await res.json();
          setTaiwanSats(data.satellites || []);
        }
      } catch (e) {
        console.error('Failed to load satellites:', e);
      }
    };
    loadSats();
  }, []);

  const loadConjunctions = useCallback(async () => {
    setLoading(true);
    try {
      let url: string;

      // Use manual NORAD ID if provided, otherwise use dropdown selection
      if (manualNoradId.trim()) {
        url = `http://localhost:8000/api/analysis/conjunction/nearby?norad_id=${manualNoradId}&days=${days}&min_distance_km=${minDistance}`;
      } else if (selectedSat === 'all-satellites') {
        url = `http://localhost:8000/api/analysis/conjunction/all-satellites?days=${days}&min_distance_km=${minDistance}`;
      } else if (selectedSat === 'system-satellites') {
        url = `http://localhost:8000/api/analysis/conjunction/system-satellites?days=${days}&min_distance_km=${minDistance}`;
      } else if (selectedSat === 'taiwan-fleet') {
        url = `http://localhost:8000/api/analysis/conjunction/taiwan-fleet?days=${days}&min_distance_km=${minDistance}`;
      } else {
        url = `http://localhost:8000/api/analysis/conjunction/nearby?norad_id=${selectedSat}&days=${days}&min_distance_km=${minDistance}`;
      }

      const res = await fetch(url, { signal: AbortSignal.timeout(15000) });
      if (res.ok) {
        const data = await res.json();
        setConjunctions(data.conjunctions || []);
        setLastRefresh(new Date().toLocaleTimeString());
      }
    } catch (e) {
      console.error('Conjunction fetch error:', e);
    }
    setLoading(false);
  }, [days, minDistance, selectedSat, manualNoradId]);

  const getRiskLevel = (minDist: number, prob?: number): { level: string; color: string } => {
    if (minDist < 10) return { level: 'Critical', color: '#f85149' };
    if (minDist < 50) return { level: 'High', color: '#fb8500' };
    if (minDist < 100) return { level: 'Medium', color: '#e3b341' };
    return { level: 'Low', color: '#3fb950' };
  };

  const formatDate = (iso: string) => {
    try {
      // Always display in UTC, never use local timezone
      const date = new Date(iso);
      const month = date.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
      const day = date.toLocaleString('en-US', { day: 'numeric', timeZone: 'UTC' });
      const hour = String(date.getUTCHours()).padStart(2, '0');
      const minute = String(date.getUTCMinutes()).padStart(2, '0');
      return `${month} ${day}, ${hour}:${minute} UTC`;
    } catch {
      return iso.slice(0, 16) + ' UTC';
    }
  };

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column' }}>
      {/* Header + Controls */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ color: '#484f58', fontSize: 11, marginBottom: 8, fontWeight: 600, letterSpacing: '0.05em' }}>
          CONJUNCTION MONITOR ({taiwanSats.length} satellites)
        </div>

        {/* Satellite Selection */}
        <div style={{ marginBottom: 8, fontSize: 11 }}>
          <label style={{ color: '#8b949e', display: 'block', marginBottom: 4 }}>Satellite:</label>
          <div style={{ display: 'flex', gap: 6 }}>
            <select
              value={selectedSat}
              onChange={(e) => { setSelectedSat(e.target.value); setManualNoradId(''); }}
              style={{
                background: '#161b22', border: '1px solid #30363d', borderRadius: 4, color: '#e6edf3',
                padding: '4px 6px', outline: 'none', cursor: 'pointer', fontSize: 11, flex: 1,
              }}
            >
              <option value="all-satellites">All Satellites (Global)</option>
              <option value="system-satellites">System Satellites Only</option>
              <option value="taiwan-fleet">Taiwan Fleet</option>
              <optgroup label="Individual">
                {taiwanSats.map(sat => (
                  <option key={sat.norad_id} value={sat.norad_id}>
                    {sat.label} ({sat.norad_id})
                  </option>
                ))}
              </optgroup>
            </select>
            <input
              type="number"
              value={manualNoradId}
              onChange={(e) => { setManualNoradId(e.target.value); setSelectedSat('all-satellites'); }}
              placeholder="Or NORAD ID"
              style={{
                background: '#161b22', border: '1px solid #30363d', borderRadius: 4, color: '#e6edf3',
                padding: '4px 6px', outline: 'none', fontSize: 11, width: 90,
              }}
            />
          </div>
        </div>

        {/* Other Controls */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8, fontSize: 11 }}>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            style={{
              background: '#161b22', border: '1px solid #30363d', borderRadius: 4, color: '#e6edf3',
              padding: '3px 6px', outline: 'none', cursor: 'pointer',
            }}
          >
            <option value={7}>Next 7 days</option>
            <option value={30}>Next 30 days</option>
            <option value={60}>Next 60 days</option>
          </select>
          <input
            type="number"
            min={1}
            max={500}
            value={minDistance}
            onChange={(e) => setMinDistance(Number(e.target.value))}
            placeholder="Max distance (km)"
            style={{
              background: '#161b22', border: '1px solid #30363d', borderRadius: 4, color: '#e6edf3',
              padding: '3px 6px', outline: 'none', width: 100,
            }}
          />
          <button
            onClick={loadConjunctions}
            disabled={loading}
            style={{
              background: '#1f6feb', border: '1px solid #388bfd', borderRadius: 4,
              color: '#fff', padding: '3px 10px', cursor: 'pointer', fontSize: 11,
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
        {lastRefresh && (
          <div style={{ fontSize: 9, color: '#484f58' }}>Last updated: {lastRefresh}</div>
        )}
      </div>

      {/* Conjunctions List */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {conjunctions.length === 0 ? (
          <div style={{ color: '#484f58', fontSize: 11, textAlign: 'center', marginTop: 20 }}>
            {loading ? 'Loading from Space-Track…' : 'No close approaches found in selected range'}
          </div>
        ) : (
          conjunctions.map((conj, i) => {
            const risk = getRiskLevel(conj.min_distance_km, conj.probability);
            return (
              <div
                key={i}
                style={{
                  background: '#0d1117', borderRadius: 8, padding: 12, marginBottom: 10,
                  border: `1px solid ${risk.color}44`,
                }}
              >
                <div style={{ color: '#e6edf3', fontSize: 12, marginBottom: 4, fontWeight: 500 }}>
                  <div>{conj.norad_id_1} ↔ {conj.norad_id_2}</div>
                  <div style={{ fontSize: 10, color: '#8b949e', marginTop: 2, fontWeight: 'normal' }}>
                    {conj.name_1} ↔ {conj.name_2}
                  </div>
                </div>
                <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 6 }}>
                  {formatDate(conj.tca)}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#8b949e', fontSize: 11 }}>
                    Min dist: <strong style={{ color: '#e6edf3' }}>{conj.min_distance_km.toFixed(1)} km</strong>
                  </span>
                  <span
                    style={{
                      background: risk.color + '22', color: risk.color, border: `1px solid ${risk.color}`,
                      borderRadius: 10, padding: '2px 8px', fontSize: 10,
                    }}
                  >
                    {risk.level}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
