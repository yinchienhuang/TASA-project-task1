import {
  MOCK_SATELLITES,
  MOCK_POSITIONS,
  MOCK_KG_NODES,
  MOCK_KG_EDGES,
  MOCK_THREAT,
  MOCK_REASONING_SUBGRAPH,
} from '../data/mockData';
import type { SatelliteInfo, Position, KGNode, KGEdge, ThreatAssessment } from '../data/mockData';

const API_BASE = 'http://localhost:8000';
const delay = (ms = 400) => new Promise((r) => setTimeout(r, ms));

// ── TLE Cache (preload to avoid lag in SatellitePanel) ─────────────────────────
const tleCache = new Map<string, any>();

export async function getTLEWithCache(noradId: string) {
  if (tleCache.has(noradId)) {
    return tleCache.get(noradId);
  }
  try {
    const res = await fetch(`${API_BASE}/api/propagation/tle/${encodeURIComponent(noradId)}`);
    if (res.ok) {
      const data = await res.json();
      tleCache.set(noradId, data);
      return data;
    }
  } catch (e) {}
  return null;
}

export async function preloadTLEs(noradIds: string[]) {
  // Fetch all TLEs in parallel, but don't wait for all to complete
  // This allows the UI to remain responsive while TLEs are loading
  noradIds.forEach(id => {
    if (!tleCache.has(id)) {
      getTLEWithCache(id).catch(() => {});
    }
  });
}

// ── Orbit positions (real backend, fallback to mock) ─────────────────────────

export interface BackendPosition {
  lat: number;
  lon: number;
  alt: number;
  timestamp: number;
}

async function fetchCachedPositions(noradId: string): Promise<BackendPosition[] | null> {
  try {
    const res = await fetch(`${API_BASE}/api/propagation/positions/cached/${noradId}`, {
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const positions = data.positions ?? null;
    return positions?.length > 0 ? positions : null;
  } catch {
    return null;
  }
}

async function fetchLivePositions(noradId: string): Promise<BackendPosition[] | null> {
  try {
    const now = Date.now();
    const start = new Date(now - 12 * 3600_000).toISOString();
    const end   = new Date(now + 12 * 3600_000).toISOString();
    const url = `${API_BASE}/api/propagation/positions/${noradId}?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&step=60`;
    const res = await fetch(url, { signal: AbortSignal.timeout(15000) });
    if (!res.ok) return null;
    const data: BackendPosition[] = await res.json();
    return data.length > 0 ? data : null;
  } catch {
    return null;
  }
}

export async function getPositions(
  noradId: string
): Promise<{ positions: Position[]; source: 'sgp4' | 'mock' }> {
  // Try pre-computed cache first (fast), fall back to live computation
  const real = (await fetchCachedPositions(noradId)) ?? (await fetchLivePositions(noradId));
  if (real && real.length > 0) {
    return {
      source: 'sgp4',
      positions: real.map((p) => ({ lat: p.lat, lon: p.lon, alt: p.alt, timestamp: p.timestamp })),
    };
  }
  return { source: 'mock', positions: MOCK_POSITIONS[noradId] ?? [] };
}

// ── News ─────────────────────────────────────────────────────────────────────

export interface NewsArticle {
  source_id: string;
  title: string;
  url: string;
  date: string;
  news_site: string;
  related_norad_ids: string[];
  ingested_at?: string;
}

export async function getNews(noradId?: string): Promise<NewsArticle[]> {
  try {
    const url = noradId
      ? `${API_BASE}/api/news/${noradId}`
      : `${API_BASE}/api/news`;
    const res = await fetch(url, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export async function refreshNews(): Promise<{ new_articles: number; total: number } | null> {
  try {
    const res = await fetch(`${API_BASE}/api/news/refresh`, { method: 'POST', signal: AbortSignal.timeout(30000) });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function refreshNewsBySatellite(noradId: string): Promise<{ new_articles: number; total: number } | null> {
  try {
    const res = await fetch(`${API_BASE}/api/news/refresh/${noradId}`, { method: 'POST', signal: AbortSignal.timeout(30000) });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

// ── Propagation ───────────────────────────────────────────────────────────────

export async function getCurrentPosition(noradId: string): Promise<BackendPosition | null> {
  try {
    const res = await fetch(`${API_BASE}/api/propagation/position/${noradId}`, {
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function getProximity(
  sat1: string,
  sat2: string,
  start: string,
  end: string,
  step = 60
): Promise<{ min_distance_km: number; at_time: number } | null> {
  try {
    const url = `${API_BASE}/api/propagation/proximity?sat1=${sat1}&sat2=${sat2}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&step=${step}`;
    const res = await fetch(url, { signal: AbortSignal.timeout(10000) });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

// ── TLE search ───────────────────────────────────────────────────────────────

export interface TLEMatch {
  noradId: string;
  name: string;
  line1: string;
  line2: string;
}

export async function searchTLE(query: string): Promise<TLEMatch[]> {
  try {
    const res = await fetch(`${API_BASE}/api/propagation/tle/search?name=${encodeURIComponent(query)}`, {
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export async function createSatellite(body: {
  noradId: string; name: string; line1: string; line2: string;
  type?: string; newsKeywords?: string;
}): Promise<{ nodeId: string; label: string } | null> {
  try {
    const res = await fetch(`${API_BASE}/api/kg/satellites`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const d = await res.json();
      throw new Error(d.detail ?? 'Failed');
    }
    return res.json();
  } catch (e) {
    throw e;
  }
}

// ── KG satellite list ─────────────────────────────────────────────────────────

export interface KGSatellite {
  /** Graph node ID — always set, used for KG lookups and selectSatellite() */
  nodeId: string;
  /** Real NORAD catalog number (all-digit string), or null if unknown */
  noradId: string | null;
  name: string;
  type: string;
  inferred_types: string[];
  attributes: Record<string, unknown>;
}

function attrValue(val: unknown): unknown {
  if (val && typeof val === 'object' && 'value' in (val as object)) return (val as { value: unknown }).value;
  return val;
}

function parseNoradId(val: unknown): string | null {
  const v = attrValue(val);
  if (!v) return null;
  const s = String(v).trim();
  return /^\d+$/.test(s) ? s : null;
}

export async function getKGSatellites(): Promise<KGSatellite[]> {
  try {
    const res = await fetch(`${API_BASE}/api/kg/full`, { signal: AbortSignal.timeout(5000) });
    if (res.ok) {
      const data = await res.json();
      const nodes: KGNode[] = data.nodes ?? [];
      const sats = nodes.filter((n) => {
        const allTypes = [n.type, ...(n.inferred_types ?? [])];
        return allTypes.some((t) => t === 'Satellite' || t?.endsWith('Satellite'));
      });
      if (sats.length > 0) {
        return sats.map((n) => {
          const attrs = (n.attributes ?? {}) as Record<string, unknown>;
          return {
            nodeId: n.id,
            noradId: parseNoradId(attrs.norad_id),
            name: n.label,
            type: n.type,
            inferred_types: n.inferred_types ?? [],
            attributes: attrs,
          };
        });
      }
    }
  } catch { /* fallback */ }
  return MOCK_SATELLITES.map((s) => ({
    nodeId: s.noradId,
    noradId: s.noradId,
    name: s.name,
    type: 'Satellite',
    inferred_types: ['Satellite'],
    attributes: {},
  }));
}

export async function enrichSatelliteTags(): Promise<{ proposed: number; satellites_checked: number }> {
  const res = await fetch(`${API_BASE}/api/kg/enrich/satellite-tags`, { method: 'POST' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function enrichSatelliteRelations(): Promise<{ proposed: number; edges: number; nodes: number }> {
  const res = await fetch(`${API_BASE}/api/kg/enrich/satellite-relations`, { method: 'POST' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Satellite info (real KG first, mock fallback) ─────────────────────────────

/** identifier may be a real NORAD ID ("42920") or a KG node ID slug ("high_precision_...") */
export async function getSatelliteInfo(identifier: string): Promise<SatelliteInfo | null> {
  // Try KG first
  try {
    const res = await fetch(`${API_BASE}/api/kg/satellite/${encodeURIComponent(identifier)}`, {
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) {
      const d = await res.json();
      // Match mock by the real NORAD ID for image / description fallback
      const mock = MOCK_SATELLITES.find((s) => s.noradId === d.noradId || s.noradId === identifier);
      return {
        nodeId: d.nodeId || '',
        noradId: d.noradId || '',
        notosId: d.notosId || '',
        type: d.type || '',
        name: d.name || mock?.name || identifier,
        launchDate: d.launchDate || mock?.launchDate || 'Unknown',
        manufacturer: d.manufacturer || mock?.manufacturer || 'Unknown',
        operator: d.operator || mock?.operator || 'Unknown',
        mission: d.mission || mock?.mission || 'Unknown',
        imageUrl: mock?.imageUrl || '',
        description: d.description || mock?.description || `${d.type} satellite.`,
        newsKeywords: d.newsKeywords || '',
      };
    }
  } catch { /* backend unreachable */ }

  // Fall back to mock
  return MOCK_SATELLITES.find((s) => s.noradId === identifier) ?? null;
}

export async function getAllSatellites(): Promise<SatelliteInfo[]> {
  try {
    const res = await fetch(`${API_BASE}/api/propagation/satellites`, {
      signal: AbortSignal.timeout(2000),
    });
    if (res.ok) {
      const data: { norad_id: string; name: string }[] = await res.json();
      // Merge backend list with mock metadata
      return data.map((d) => {
        const mock = MOCK_SATELLITES.find((s) => s.noradId === d.norad_id);
        return mock ?? { noradId: d.norad_id, name: d.name, launchDate: '', manufacturer: '', operator: '', mission: '', imageUrl: '' };
      });
    }
  } catch { /* fallback */ }
  await delay();
  return MOCK_SATELLITES;
}

// ── Knowledge graph ──────────────────────────────────────────────────────────

export async function getFullKG(): Promise<{ nodes: KGNode[]; edges: KGEdge[] }> {
  try {
    const res = await fetch(`${API_BASE}/api/kg/full`, { signal: AbortSignal.timeout(5000) });
    if (res.ok) {
      const data = await res.json();
      // If backend KG is populated, use it; otherwise fall back to mock
      if (data.nodes?.length > 0 || data.edges?.length > 0) {
        return {
          nodes: data.nodes as KGNode[],
          edges: data.edges as KGEdge[],
        };
      }
    }
  } catch { /* backend unreachable, use mock */ }
  await delay();
  return { nodes: MOCK_KG_NODES, edges: MOCK_KG_EDGES };
}

export async function getSatelliteSubgraph(
  noradId: string
): Promise<{ nodes: KGNode[]; edges: KGEdge[] }> {
  try {
    const res = await fetch(`${API_BASE}/api/kg/subgraph/${noradId}?hops=1`, { signal: AbortSignal.timeout(5000) });
    if (res.ok) {
      const data = await res.json();
      const nodes = Object.values(data.nodes || {}) as KGNode[];
      const edges = Object.values(data.edges || {}) as KGEdge[];
      if (nodes.length > 0) return { nodes, edges };
    }
  } catch { /* fallback */ }
  await delay();
  const directEdges = MOCK_KG_EDGES.filter(
    (e) => e.source === noradId || e.target === noradId
  );
  const connectedIds = new Set<string>([noradId]);
  directEdges.forEach((e) => { connectedIds.add(e.source); connectedIds.add(e.target); });
  return {
    nodes: MOCK_KG_NODES.filter((n) => connectedIds.has(n.id)),
    edges: directEdges,
  };
}

// ── Reasoning ────────────────────────────────────────────────────────────────

export async function submitReport(
  _file: File
): Promise<{ assessment: ThreatAssessment; subgraphNodeIds: Set<string>; subgraphEdgeIds: Set<string> }> {
  await delay(1500);
  return {
    assessment: MOCK_THREAT,
    subgraphNodeIds: MOCK_REASONING_SUBGRAPH.nodeIds,
    subgraphEdgeIds: MOCK_REASONING_SUBGRAPH.edgeIds,
  };
}

export async function submitQuery(
  query: string
): Promise<{ answer: string; subgraphNodeIds: Set<string>; subgraphEdgeIds: Set<string> }> {
  await delay(1200);
  const answer = query.toLowerCase().includes('noaa')
    ? 'NOAA-20 reported a sensor anomaly on its ATMS instrument in September 2024. The anomaly was assessed as non-critical; backup calibration mode was activated. No conjunction threats are currently flagged for this satellite.'
    : `Based on the current knowledge graph, the most recent relevant event is the ISS maneuver reported in JCO #2024-112. Threat severity was assessed as Medium. No critical threats are active for the queried entities.`;
  return {
    answer,
    subgraphNodeIds: MOCK_REASONING_SUBGRAPH.nodeIds,
    subgraphEdgeIds: MOCK_REASONING_SUBGRAPH.edgeIds,
  };
}

// ── Satellite Events ──────────────────────────────────────────────────────────

export interface SatelliteEvent {
  id: string;
  type: 'maneuver' | 'photometric_change' | 'launch';
  satellite_id: string;
  satellite_label: string;
  event_date: string;
  source_id?: string;
  report_title?: string;
  // maneuver fields (JCO-extracted)
  delta_v?: number;
  period_change?: number;
  apogee_change?: number;
  perigee_change?: number;
  inclination_change?: number;
  jco_delta_v?: number;
  jco_period_change?: number;
  jco_apogee_change?: number;
  jco_perigee_change?: number;
  jco_incl_change?: number;
  // maneuver fields (TLE-computed)
  tle_delta_v_est?: number;
  tle_period_change?: number;
  tle_incl_change?: number;
  tle_pre_period?: number;
  tle_post_period?: number;
  tle_available?: boolean;
  discrepancy_pct?: number;
  discrepancy_flag?: boolean;
  maneuver_type?: string;
  regime?: string;
  // photometric fields
  magnitude_change_min?: number;
  magnitude_change_max?: number;
  magnitude_direction?: string;
  recovery_date?: string;
  associated_satellite_id?: string;
  associated_satellite_label?: string;
  associated_distance_km?: number;
  // shared implication fields (maneuver + photometric + launch)
  verification_status?: 'verified' | 'possible' | 'detected';
  pol_status?: 'within_pol' | 'outside_pol' | 'return_to_pol' | 'unknown';
  analyst_assessment?: string;
  pai_summary?: string;
  // launch fields
  notos_id?: string;
  launch_time_start?: string;
  launch_time_end?: string;
  launch_site?: string;
  launch_site_lat?: number;
  launch_site_lon?: number;
  launch_vehicle?: string;
  orbital_inclination?: number;
  orbital_period?: number;
  notam_ids?: string[];
  trajectory_zones?: Array<{
    notam_id: string;
    shape: 'circle' | 'polygon';
    center_lat?: number;
    center_lon?: number;
    radius_km?: number;
    vertices?: [number, number][];
    active_start: string;
    active_end: string;
  }>;
  created_at?: string;
}

export async function getSatelliteEvents(satelliteId: string): Promise<SatelliteEvent[]> {
  try {
    const res = await fetch(`${API_BASE}/api/events/satellite/${encodeURIComponent(satelliteId)}`, {
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return [];
    return res.json();
  } catch { return []; }
}

export async function extractEventsFromSource(sourceId: string): Promise<{ extracted: number; event_ids: string[] } | null> {
  try {
    const res = await fetch(`${API_BASE}/api/events/extract/${encodeURIComponent(sourceId)}`, {
      method: 'POST',
      signal: AbortSignal.timeout(60000),
    });
    if (!res.ok) return null;
    return res.json();
  } catch { return null; }
}

export async function deleteEvent(eventId: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/events/${encodeURIComponent(eventId)}`, {
      method: 'DELETE',
      signal: AbortSignal.timeout(5000),
    });
    return res.ok;
  } catch { return false; }
}

export interface EventUpdate {
  field: string;
  old: unknown;
  new: unknown;
  type: 'added' | 'updated' | 'removed';
}

export interface EventUpdateHistory {
  timestamp: string;
  changes: EventUpdate[];
  summary: string;
}

export interface EventUpdateInfo {
  event_id: string;
  satellite_label: string;
  type: string;
  created_at: string;
  total_updates: number;
  updates: EventUpdateHistory[];
}

export async function getEventUpdates(eventId: string, limit: number = 10): Promise<EventUpdateInfo | null> {
  try {
    const res = await fetch(
      `${API_BASE}/api/events/${encodeURIComponent(eventId)}/updates?limit=${limit}`,
      { signal: AbortSignal.timeout(5000) }
    );
    if (!res.ok) return null;
    return res.json();
  } catch { return null; }
}

// ── Analysis API ──────────────────────────────────────────────────────────────

export interface FleetCoverageResult {
  norad_id: string;
  label: string;
  node_id: string;
  summary: {
    total_passes: number;
    avg_passes_per_day: number;
    avg_duration_min: number;
    revisit_interval_hours: number | null;
  };
}

export interface QueryResult {
  answer: string;
  steps: Array<{ tool: string; args: Record<string, unknown>; result: unknown }>;
  iterations: number;
  warning?: string;
}

export async function getFleetEvents(params: {
  type?: string;
  regime?: string;
  days?: number;
  satellite_id?: string;
}): Promise<SatelliteEvent[]> {
  try {
    const q = new URLSearchParams();
    if (params.type) q.set('type', params.type);
    if (params.regime) q.set('regime', params.regime);
    if (params.days != null) q.set('days', String(params.days));
    if (params.satellite_id) q.set('satellite_id', params.satellite_id);
    const res = await fetch(`${API_BASE}/api/events?${q}`, { signal: AbortSignal.timeout(10000) });
    if (!res.ok) return [];
    return res.json();
  } catch { return []; }
}

export async function getFleetCoverage(params: {
  country: string;
  region: string;
  days: number;
}): Promise<FleetCoverageResult[]> {
  try {
    const q = new URLSearchParams({
      country: params.country,
      region: params.region,
      days: String(params.days),
    });
    const res = await fetch(`${API_BASE}/api/analysis/coverage/fleet/search?${q}`, {
      signal: AbortSignal.timeout(120000),
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.satellites ?? [];
  } catch { return []; }
}

export async function queryAnalysis(
  question: string,
  satelliteId?: string,
  history?: Array<{ role: 'user' | 'assistant'; content: string }>,
  onToolCall?: (toolName: string, args: Record<string, any>) => void
): Promise<QueryResult> {
  const res = await fetch(`${API_BASE}/api/analysis/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      satellite_id: satelliteId ?? null,
      history: history ?? null,
    }),
    signal: AbortSignal.timeout(120000),
  });
  if (!res.ok) throw new Error(`Query failed: ${res.status}`);

  // Parse Server-Sent Events
  const reader = res.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  let result: QueryResult | null = null;
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');

      // Keep the last incomplete line in buffer
      buffer = lines[lines.length - 1];

      for (const line of lines.slice(0, -1)) {
        if (line.startsWith('data: ')) {
          try {
            const event = JSON.parse(line.substring(6));

            if (event.type === 'tool_call') {
              // Notify about tool call
              if (onToolCall) {
                onToolCall(event.tool, event.args);
              }
            } else if (event.type === 'result') {
              // Final result
              result = event.data;
            }
          } catch (e) {
            // Skip invalid JSON
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  if (!result) {
    throw new Error('No result received from server');
  }

  return result;
}

// ── NOTAM ingest ──────────────────────────────────────────────────────────────

export interface NotamIngestResult {
  count: number;
  events: SatelliteEvent[];
}

export async function ingestNotamText(text: string): Promise<NotamIngestResult> {
  const res = await fetch(`${API_BASE}/api/events/notam/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
    signal: AbortSignal.timeout(60000),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error((d as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function getLaunchEvents(): Promise<SatelliteEvent[]> {
  try {
    const res = await fetch(`${API_BASE}/api/events/notam`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) return [];
    return res.json();
  } catch { return []; }
}

// ── NORAD matching and assignment ─────────────────────────────────────────────

export interface NoradCandidate {
  norad_id: string;
  name: string;
  inclination: number;
  period: number;
  launch_date: string;
  score: number;
}

export async function findNoradCandidates(nodeId: string): Promise<NoradCandidate[]> {
  try {
    const res = await fetch(`${API_BASE}/api/kg/nodes/${encodeURIComponent(nodeId)}/find-norad`, {
      signal: AbortSignal.timeout(15000),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail ?? `HTTP ${res.status}`);
    }
    return res.json();
  } catch (e) {
    throw e;
  }
}

export async function assignNoradId(
  nodeId: string,
  noradId: string,
): Promise<{ tle_found: boolean; positions_computed: number }> {
  const res = await fetch(`${API_BASE}/api/kg/nodes/${encodeURIComponent(nodeId)}/assign-norad`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ norad_id: noradId }),
    signal: AbortSignal.timeout(20000),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}
