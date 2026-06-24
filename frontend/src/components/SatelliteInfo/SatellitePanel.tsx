import { useEffect, useState } from 'react';
import { useAppStore } from '../../store/appStore';
import {
  getSatelliteInfo, getSatelliteEvents, deleteEvent,
  findNoradCandidates, assignNoradId, getTLEWithCache,
} from '../../api/client';
import type { SatelliteInfo } from '../../data/mockData';
import type { SatelliteEvent, NoradCandidate } from '../../api/client';

const API = 'http://localhost:8000';

interface SchemaNode { type: string; children: SchemaNode[]; }

async function fetchSchemaTree(): Promise<SchemaNode[]> {
  try {
    const r = await fetch(`${API}/api/kg/schema/tree`);
    return r.ok ? (await r.json()).tree ?? [] : [];
  } catch { return []; }
}

function flattenTypes(nodes: SchemaNode[], depth = 0): { type: string; depth: number }[] {
  const out: { type: string; depth: number }[] = [];
  for (const n of nodes) {
    out.push({ type: n.type, depth });
    out.push(...flattenTypes(n.children, depth + 1));
  }
  return out;
}

export default function SatellitePanel() {
  const { selectedSatelliteId, selectSatellite, visibleSatelliteIds, toggleSatelliteVisibility } = useAppStore();
  const [info, setInfo] = useState<SatelliteInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [schemaTypes, setSchemaTypes] = useState<{ type: string; depth: number }[]>([]);

  useEffect(() => {
    fetchSchemaTree().then((tree) => setSchemaTypes(flattenTypes(tree)));
  }, []);

  useEffect(() => {
    if (!selectedSatelliteId) { setInfo(null); return; }
    setLoading(true);
    getSatelliteInfo(selectedSatelliteId).then((data) => {
      setInfo(data);
      setLoading(false);
    });
  }, [selectedSatelliteId]);

  if (!selectedSatelliteId) return null;

  return (
    <div style={{
      position: 'fixed', right: 0, top: 0, bottom: 0, width: 320,
      background: '#161b22', borderLeft: '1px solid #30363d',
      zIndex: 100, display: 'flex', flexDirection: 'column',
      boxShadow: '-4px 0 16px rgba(0,0,0,0.5)',
    }}>
      {/* Header */}
      <div style={{
        padding: '12px 16px', borderBottom: '1px solid #30363d',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <span style={{ color: '#58a6ff', fontWeight: 600, fontSize: 14 }}>Satellite Info</span>
        <button
          onClick={() => selectSatellite(null)}
          style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 18, lineHeight: 1 }}
        >×</button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {loading ? (
          <div style={{ color: '#8b949e', textAlign: 'center', marginTop: 40 }}>Loading…</div>
        ) : info ? (
          <>
            {info.imageUrl ? <SatelliteImage src={info.imageUrl} alt={info.name} /> : <ImagePlaceholder name={info.name} />}

            <h2 style={{ color: '#e6edf3', margin: '0 0 4px', fontSize: 16 }}>{info.name}</h2>
            {info.noradId ? (
              <p style={{ color: '#8b949e', margin: '0 0 8px', fontSize: 12 }}>NORAD ID: {info.noradId}</p>
            ) : (info as any).notosId ? (
              <p style={{ color: '#d29922', margin: '0 0 8px', fontSize: 12 }}>
                NOTOS ID: {(info as any).notosId} <span style={{ color: '#8b949e' }}>(provisional)</span>
              </p>
            ) : (
              <p style={{ color: '#484f58', margin: '0 0 8px', fontSize: 12 }}>No tracking ID</p>
            )}

            {info.noradId && (() => {
              const isVisible = visibleSatelliteIds.has(info.noradId!);
              return (
                <button
                  onClick={() => toggleSatelliteVisibility(info.noradId!)}
                  style={{
                    width: '100%', marginBottom: 16, padding: '5px 0', fontSize: 12,
                    background: isVisible ? '#1f6feb' : '#21262d',
                    border: `1px solid ${isVisible ? '#388bfd' : '#30363d'}`,
                    borderRadius: 4, color: isVisible ? '#fff' : '#8b949e',
                    cursor: 'pointer',
                  }}
                >
                  {isVisible ? '🌐 Hide from Globe' : '🌐 Show on Globe'}
                </button>
              );
            })()}

            <InfoRow label="Launch Date" value={info.launchDate} />
            <InfoRow label="Manufacturer" value={info.manufacturer} />
            <InfoRow label="Operator" value={info.operator} />
            <InfoRow label="Mission" value={info.mission} />

            {info.description && (
              <div style={{ marginTop: 16, padding: 12, background: '#0d1117', borderRadius: 6 }}>
                <p style={{ color: '#8b949e', fontSize: 12, margin: 0, lineHeight: 1.6 }}>{info.description}</p>
              </div>
            )}

            {info.noradId && <TLEViewer noradId={info.noradId} />}

            {/* NORAD finder — only when no NORAD ID yet */}
            {!info.noradId && info.nodeId && (
              <NoradFinderWidget
                nodeId={info.nodeId}
                notosId={(info as any).notosId || ''}
                onAssigned={(noradId) => setInfo((prev) => prev ? { ...prev, noradId } : prev)}
              />
            )}

            {info.nodeId && <EventTimeline satelliteId={info.nodeId} />}

            {/* Node editor — label, type, delete */}
            {info.nodeId && (
              <NodeEditor
                nodeId={info.nodeId}
                currentLabel={info.name}
                currentType={(info as any).type ?? ''}
                schemaTypes={schemaTypes}
                onSaved={(label, type) => setInfo((prev) => prev ? { ...prev, name: label, type } : prev)}
                onDeleted={() => selectSatellite(null)}
              />
            )}

            {/* News Keywords editor — only shown for KG-backed satellites */}
            {info.nodeId && (
              <KeywordsEditor
                nodeId={info.nodeId}
                noradId={info.noradId}
                initial={info.newsKeywords ?? ''}
                onSaved={(kw) => setInfo((prev) => prev ? { ...prev, newsKeywords: kw } : prev)}
              />
            )}
          </>
        ) : (
          <div style={{ color: '#f78166', textAlign: 'center', marginTop: 40 }}>Not found</div>
        )}
      </div>
    </div>
  );
}

function NodeEditor({ nodeId, currentLabel, currentType, schemaTypes, onSaved, onDeleted }: {
  nodeId: string;
  currentLabel: string;
  currentType: string;
  schemaTypes: { type: string; depth: number }[];
  onSaved: (label: string, type: string) => void;
  onDeleted: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(currentLabel);
  const [type, setType] = useState(currentType);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/kg/nodes/${encodeURIComponent(nodeId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: label.trim(), type: type.trim() }),
      });
      if (r.ok) { onSaved(label.trim(), type.trim()); setEditing(false); }
    } finally { setSaving(false); }
  };

  const deleteNode = async () => {
    setDeleting(true);
    try {
      const r = await fetch(`${API}/api/kg/nodes/${encodeURIComponent(nodeId)}`, { method: 'DELETE' });
      if (r.ok) onDeleted();
    } finally { setDeleting(false); setConfirmDelete(false); }
  };

  return (
    <div style={{ marginTop: 20, borderTop: '1px solid #21262d', paddingTop: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ color: '#8b949e', fontSize: 11 }}>NODE</span>
        {!editing && (
          <div style={{ display: 'flex', gap: 8 }}>
            {confirmDelete ? (
              <>
                <button onClick={deleteNode} disabled={deleting}
                  style={{ background: 'none', border: 'none', color: '#f78166', cursor: 'pointer', fontSize: 11, padding: 0 }}>
                  {deleting ? 'Deleting…' : 'Confirm delete'}
                </button>
                <button onClick={() => setConfirmDelete(false)}
                  style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 11, padding: 0 }}>
                  Cancel
                </button>
              </>
            ) : (
              <>
                <button onClick={() => setConfirmDelete(true)}
                  style={{ background: 'none', border: 'none', color: '#484f58', cursor: 'pointer', fontSize: 11, padding: 0 }}>
                  Delete
                </button>
                <button onClick={() => { setLabel(currentLabel); setType(currentType); setEditing(true); }}
                  style={{ background: 'none', border: 'none', color: '#58a6ff', cursor: 'pointer', fontSize: 11, padding: 0 }}>
                  Edit
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {editing ? (
        <>
          <div style={{ marginBottom: 8 }}>
            <div style={{ color: '#484f58', fontSize: 10, marginBottom: 3 }}>LABEL</div>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              style={{
                width: '100%', boxSizing: 'border-box',
                background: '#0d1117', border: '1px solid #388bfd',
                borderRadius: 4, color: '#e6edf3', fontSize: 12, padding: '4px 8px',
              }}
            />
          </div>
          <div style={{ marginBottom: 8 }}>
            <div style={{ color: '#484f58', fontSize: 10, marginBottom: 3 }}>TYPE</div>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              style={{
                width: '100%', background: '#0d1117', border: '1px solid #388bfd',
                borderRadius: 4, color: '#e6edf3', fontSize: 12, padding: '4px 8px',
              }}
            >
              {schemaTypes.map(({ type: t, depth }) => (
                <option key={t} value={t}>{'  '.repeat(depth)}{t}</option>
              ))}
            </select>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={save} disabled={saving} style={{
              flex: 1, background: '#1f6feb', border: 'none', borderRadius: 4,
              color: '#fff', cursor: saving ? 'default' : 'pointer', padding: '4px 0', fontSize: 12,
            }}>
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button onClick={() => setEditing(false)} style={{
              flex: 1, background: 'none', border: '1px solid #30363d', borderRadius: 4,
              color: '#8b949e', cursor: 'pointer', padding: '4px 0', fontSize: 12,
            }}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <div style={{ fontSize: 12, color: '#8b949e' }}>
          <span style={{ color: '#e6edf3' }}>{currentLabel}</span>
          <span style={{ margin: '0 6px' }}>·</span>
          <span style={{ color: '#bc8cff' }}>{currentType || '—'}</span>
        </div>
      )}
    </div>
  );
}

function KeywordsEditor({ nodeId, noradId, initial, onSaved }: {
  nodeId: string;
  noradId: string;
  initial: string;
  onSaved: (kw: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetResult, setResetResult] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/kg/nodes/${encodeURIComponent(nodeId)}/attribute`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'news_keywords', value: value.trim() }),
      });
      if (r.ok) { onSaved(value.trim()); setEditing(false); }
    } finally { setSaving(false); }
  };

  const resetAndRefetch = async () => {
    if (!noradId) return;
    setResetting(true);
    setResetResult(null);
    try {
      const r = await fetch(`${API}/api/news/reset/${encodeURIComponent(noradId)}`, { method: 'POST' });
      if (r.ok) {
        const d = await r.json();
        setResetResult(`−${d.removed} old, +${d.fetched} new`);
        setTimeout(() => setResetResult(null), 4000);
      } else {
        const d = await r.json();
        setResetResult(d.detail || 'Error');
        setTimeout(() => setResetResult(null), 4000);
      }
    } finally { setResetting(false); }
  };

  return (
    <div style={{ marginTop: 20, borderTop: '1px solid #21262d', paddingTop: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ color: '#8b949e', fontSize: 11 }}>NEWS KEYWORDS</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {resetResult && (
            <span style={{ fontSize: 10, color: '#3fb950' }}>{resetResult}</span>
          )}
          {!editing && noradId && (
            <button
              onClick={resetAndRefetch}
              disabled={resetting || !initial}
              title="Clear old articles and re-fetch with current keywords"
              style={{
                background: 'none', border: 'none',
                color: resetting || !initial ? '#484f58' : '#e3b341',
                cursor: resetting || !initial ? 'default' : 'pointer', fontSize: 11, padding: 0,
              }}
            >
              {resetting ? 'Fetching…' : '↻ Refetch'}
            </button>
          )}
          {!editing && (
            <button
              onClick={() => { setValue(initial); setEditing(true); }}
              style={{ background: 'none', border: 'none', color: '#58a6ff', cursor: 'pointer', fontSize: 11, padding: 0 }}
            >
              Edit
            </button>
          )}
        </div>
      </div>

      {editing ? (
        <>
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="e.g. ISS, International Space Station&#10;Or Chinese: 遥感三十号, 遥感-30"
            rows={3}
            style={{
              width: '100%', boxSizing: 'border-box',
              background: '#0d1117', border: '1px solid #388bfd',
              borderRadius: 4, color: '#e6edf3', fontSize: 12,
              padding: '6px 8px', resize: 'vertical', fontFamily: 'inherit',
            }}
          />
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <button
              onClick={save}
              disabled={saving}
              style={{
                flex: 1, background: '#1f6feb', border: 'none', borderRadius: 4,
                color: '#fff', cursor: saving ? 'default' : 'pointer',
                padding: '4px 0', fontSize: 12,
              }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              onClick={() => setEditing(false)}
              style={{
                flex: 1, background: 'none', border: '1px solid #30363d', borderRadius: 4,
                color: '#8b949e', cursor: 'pointer', padding: '4px 0', fontSize: 12,
              }}
            >
              Cancel
            </button>
          </div>
          <p style={{ color: '#484f58', fontSize: 10, margin: '6px 0 0' }}>
            Comma-separated. After saving, use ↻ Refetch to apply new keywords to the news cache.
          </p>
        </>
      ) : (
        <div style={{ color: initial ? '#e6edf3' : '#484f58', fontSize: 12, lineHeight: 1.6, wordBreak: 'break-word' }}>
          {initial || 'Not set — satellite excluded from news fetch'}
        </div>
      )}
    </div>
  );
}

function SatelliteImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <ImagePlaceholder name={alt} />;
  return (
    <img
      src={src} alt={alt} referrerPolicy="no-referrer"
      style={{ width: '100%', borderRadius: 8, marginBottom: 16, objectFit: 'cover', maxHeight: 180 }}
      onError={() => setFailed(true)}
    />
  );
}

function ImagePlaceholder({ name }: { name: string }) {
  return (
    <div style={{
      width: '100%', height: 120, borderRadius: 8, marginBottom: 16,
      background: '#21262d', border: '1px solid #30363d',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 6,
    }}>
      <span style={{ fontSize: 32 }}>🛰</span>
      <span style={{ color: '#484f58', fontSize: 11 }}>{name}</span>
    </div>
  );
}

function TLEViewer({ noradId }: { noradId: string }) {
  const [tle, setTle] = useState<{ name: string; line1: string; line2: string } | null>(null);
  const [status, setStatus] = useState<'loading' | 'ok' | 'none'>('loading');
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState('');

  const loadTle = async () => {
    setStatus('loading');
    setTle(null);
    const d = await getTLEWithCache(noradId);
    if (d?.line1 && d?.line2) { setTle(d); setStatus('ok'); }
    else setStatus('none');
  };

  useEffect(() => {
    loadTle();
  }, [noradId]);

  const handleRefresh = async () => {
    setRefreshing(true);
    setRefreshMsg('');
    try {
      const r = await fetch(`${API}/api/propagation/tle/${encodeURIComponent(noradId)}/refresh`, {
        method: 'POST',
      });
      if (r.ok) {
        const data = await r.json();
        setTle(data);
        setStatus('ok');
        setRefreshMsg('✓ Updated from Space-Track');
        setTimeout(() => setRefreshMsg(''), 3000);
      } else {
        setRefreshMsg('Failed to refresh');
      }
    } catch (e) {
      setRefreshMsg('Error refreshing TLE');
    } finally {
      setRefreshing(false);
    }
  };

  const epoch = tle?.line1
    ? (() => {
        const yr2 = parseInt(tle.line1.slice(18, 20), 10);
        const yr = yr2 >= 57 ? 1900 + yr2 : 2000 + yr2;
        const day = parseFloat(tle.line1.slice(20, 32));
        const d = new Date(Date.UTC(yr, 0, 1));
        d.setUTCDate(d.getUTCDate() + Math.floor(day) - 1);
        return `${yr}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
      })()
    : null;

  return (
    <div style={{ marginTop: 20, borderTop: '1px solid #21262d', paddingTop: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ color: '#8b949e', fontSize: 11 }}>TLE</span>
        <button
          onClick={handleRefresh}
          disabled={refreshing || status === 'loading'}
          style={{
            background: 'none', border: 'none', color: '#58a6ff', cursor: 'pointer',
            fontSize: 11, padding: 0, opacity: refreshing ? 0.6 : 1,
          }}
        >
          {refreshing ? '⟳ Updating…' : '⟳ Fetch Latest'}
        </button>
      </div>
      {refreshMsg && <div style={{ color: '#3fb950', fontSize: 10, marginBottom: 6 }}>{refreshMsg}</div>}
      {status === 'loading' && <div style={{ color: '#484f58', fontSize: 11 }}>Loading…</div>}
      {status === 'none' && <div style={{ color: '#484f58', fontSize: 11 }}>No TLE registered</div>}
      {status === 'ok' && tle && (
        <>
          {epoch && <div style={{ color: '#8b949e', fontSize: 10, marginBottom: 6 }}>Epoch: {epoch}</div>}
          <pre style={{
            margin: 0, padding: '8px 10px', background: '#0d1117', borderRadius: 4,
            fontSize: 10, color: '#3fb950', fontFamily: 'monospace', overflowX: 'auto',
            lineHeight: 1.7, whiteSpace: 'pre',
          }}>
            {tle.line1}{'\n'}{tle.line2}
          </pre>
        </>
      )}
    </div>
  );
}

function EventTimeline({ satelliteId }: { satelliteId: string }) {
  const [events, setEvents] = useState<SatelliteEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'launch' | 'maneuver' | 'photometric_change'>('all');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setEvents([]);
    setExpandedId(null);
    getSatelliteEvents(satelliteId).then((evts) => {
      setEvents(evts);
      setLoading(false);
    });
  }, [satelliteId]);

  const handleDelete = async (id: string) => {
    if (!window.confirm('Delete this event?')) return;
    if (await deleteEvent(id)) setEvents((prev) => prev.filter((e) => e.id !== id));
  };

  const filtered = filter === 'all' ? events : events.filter((e) => e.type === filter);

  // Group by YYYY-MM
  const grouped = new Map<string, SatelliteEvent[]>();
  for (const ev of filtered) {
    const key = ev.event_date?.slice(0, 7) ?? 'Unknown';
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(ev);
  }
  const sortedKeys = [...grouped.keys()].sort().reverse();

  const fmtDate = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleDateString('en-US', { day: '2-digit', month: 'short', year: 'numeric' });
    } catch { return iso.slice(0, 10); }
  };

  const fmtMonthKey = (key: string) => {
    try {
      const [yr, mo] = key.split('-');
      return new Date(+yr, +mo - 1, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    } catch { return key; }
  };

  const sign = (n?: number) => n == null ? '?' : (n >= 0 ? `+${n}` : `${n}`);

  const maneuvers = events.filter((e) => e.type === 'maneuver');
  const totalDv = maneuvers.reduce((sum, e) => sum + (Math.abs(e.delta_v ?? 0)), 0);

  return (
    <div style={{ marginTop: 20, borderTop: '1px solid #21262d', paddingTop: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ color: '#8b949e', fontSize: 11 }}>EVENTS</span>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {(['all', 'launch', 'maneuver', 'photometric_change'] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)} style={{
              padding: '1px 7px', fontSize: 10, borderRadius: 10, cursor: 'pointer',
              background: filter === f ? (f === 'launch' ? '#238636' : '#1f6feb') : 'transparent',
              border: `1px solid ${filter === f ? (f === 'launch' ? '#3fb950' : '#388bfd') : '#30363d'}`,
              color: filter === f ? '#fff' : '#8b949e',
            }}>
              {f === 'all' ? 'All' : f === 'launch' ? 'Launch' : f === 'maneuver' ? 'Maneuver' : 'Photometric'}
            </button>
          ))}
        </div>
      </div>

      {!loading && maneuvers.length > 0 && (
        <div style={{
          display: 'flex', gap: 16, marginBottom: 10, padding: '6px 10px',
          background: '#161b22', borderRadius: 6, border: '1px solid #21262d', fontSize: 11,
        }}>
          <span style={{ color: '#8b949e' }}>
            Total ΔV consumed:&nbsp;
            <span style={{ color: '#58a6ff', fontWeight: 600 }}>
              {totalDv.toFixed(2)} m/s
            </span>
          </span>
          <span style={{ color: '#484f58' }}>from {maneuvers.length} maneuver{maneuvers.length !== 1 ? 's' : ''}</span>
        </div>
      )}

      {loading && <div style={{ color: '#484f58', fontSize: 11 }}>Loading…</div>}

      {!loading && filtered.length === 0 && (
        <div style={{ color: '#484f58', fontSize: 11 }}>
          No events recorded. Process a JCO report to populate.
        </div>
      )}

      {!loading && sortedKeys.map((key) => (
        <div key={key} style={{ marginBottom: 10 }}>
          <div style={{ color: '#484f58', fontSize: 10, fontWeight: 600, marginBottom: 4 }}>
            {fmtMonthKey(key)}
          </div>
          {grouped.get(key)!.map((ev) => {
            const isManeuver = ev.type === 'maneuver';
            const isLaunch = ev.type === 'launch';
            const expanded = expandedId === ev.id;
            const accentColor = isLaunch ? '#3fb950' : isManeuver ? '#58a6ff' : '#e3b341';
            const borderColor = expanded
              ? (isLaunch ? '#3fb95044' : isManeuver ? '#1f6feb44' : '#e3b34144')
              : '#21262d';
            return (
              <div key={ev.id} style={{
                marginBottom: 4, borderRadius: 4,
                border: `1px solid ${borderColor}`,
                background: expanded ? '#0d1117' : 'transparent',
                overflow: 'hidden',
              }}>
                {/* Summary row */}
                <div
                  onClick={() => setExpandedId(expanded ? null : ev.id)}
                  style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '5px 8px', cursor: 'pointer' }}
                >
                  <span style={{ fontSize: 12, flexShrink: 0, marginTop: 1, color: accentColor }}>
                    {isLaunch ? '⬆' : isManeuver ? '●' : '◈'}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11, color: '#e6edf3' }}>
                      {fmtDate(ev.event_date)}
                      <span style={{ color: accentColor, marginLeft: 6 }}>
                        {isLaunch ? 'Launch' : isManeuver ? 'Maneuver' : 'Photometric Chg'}
                      </span>
                    </div>
                    <div style={{ fontSize: 10, color: '#8b949e', marginTop: 1 }}>
                      {isLaunch
                        ? [ev.launch_site, ev.launch_vehicle].filter(Boolean).join('  ·  ')
                        : isManeuver
                          ? (() => {
                              const jcoDv = ev.jco_delta_v ?? ev.delta_v;
                              const tleDv = ev.tle_delta_v_est;
                              const dvStr = jcoDv != null
                                ? `JCO: ${sign(jcoDv)} m/s${tleDv != null ? `  TLE: ${tleDv.toFixed(2)} m/s` : ''}`
                                : `${sign(ev.delta_v)} m/s`;
                              const typeStr = ev.maneuver_type ? `[${ev.maneuver_type}]  ` : '';
                              return typeStr + dvStr;
                            })()
                          : `${ev.magnitude_change_min ?? '?'}–${ev.magnitude_change_max ?? '?'} mag ${ev.magnitude_direction ?? ''}`
                      }
                    </div>
                    {isManeuver && ev.discrepancy_flag && (
                      <div style={{ fontSize: 9, color: '#f0a500', marginTop: 2 }}>
                        ⚠ {((ev.discrepancy_pct ?? 0) * 100).toFixed(0)}% JCO/TLE discrepancy
                      </div>
                    )}
                  </div>
                  <span style={{ color: '#484f58', fontSize: 10, flexShrink: 0 }}>{expanded ? '▲' : '▼'}</span>
                </div>

                {/* Detail expand */}
                {expanded && (
                  <div style={{ padding: '0 8px 8px 28px', borderTop: '1px solid #21262d' }}>
                    {isLaunch ? (
                      <table style={{ fontSize: 11, borderCollapse: 'collapse', width: '100%' }}>
                        <tbody>
                          {ev.launch_time_start && ev.launch_time_end && (
                            <tr>
                              <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 3, whiteSpace: 'nowrap' }}>window</td>
                              <td style={{ color: '#e6edf3' }}>
                                {ev.launch_time_start.slice(11, 16)} – {ev.launch_time_end.slice(11, 16)} UTC
                              </td>
                            </tr>
                          )}
                          {ev.launch_site && (
                            <tr>
                              <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 3, whiteSpace: 'nowrap' }}>site</td>
                              <td style={{ color: '#e6edf3' }}>
                                {ev.launch_site}
                                {ev.launch_site_lat != null && ev.launch_site_lon != null && (
                                  <span style={{ color: '#8b949e' }}>
                                    {' '}{ev.launch_site_lat.toFixed(2)}°N {ev.launch_site_lon.toFixed(2)}°E
                                  </span>
                                )}
                              </td>
                            </tr>
                          )}
                          {ev.launch_vehicle && (
                            <tr>
                              <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 3, whiteSpace: 'nowrap' }}>vehicle</td>
                              <td style={{ color: '#e6edf3' }}>{ev.launch_vehicle}</td>
                            </tr>
                          )}
                          {(ev.orbital_inclination != null || ev.orbital_period != null) && (
                            <tr>
                              <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 3, whiteSpace: 'nowrap' }}>orbit</td>
                              <td style={{ color: '#e6edf3' }}>
                                {ev.orbital_inclination != null && `${ev.orbital_inclination}° incl`}
                                {ev.orbital_inclination != null && ev.orbital_period != null && '  ·  '}
                                {ev.orbital_period != null && `${ev.orbital_period.toFixed(1)} min`}
                              </td>
                            </tr>
                          )}
                          {ev.notam_ids && ev.notam_ids.length > 0 && (
                            <tr>
                              <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 3, whiteSpace: 'nowrap' }}>NOTAMs</td>
                              <td style={{ color: '#e6edf3' }}>{ev.notam_ids.join(' · ')}</td>
                            </tr>
                          )}
                          {ev.trajectory_zones && ev.trajectory_zones.length > 0 && (
                            <tr>
                              <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 3, whiteSpace: 'nowrap' }}>trajectory</td>
                              <td style={{ color: '#e6edf3' }}>{ev.trajectory_zones.length} zones</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    ) : isManeuver ? (
                      <table style={{ fontSize: 11, borderCollapse: 'collapse', width: '100%' }}>
                        <tbody>
                          {ev.maneuver_type && (
                            <tr>
                              <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 3, whiteSpace: 'nowrap' }}>type</td>
                              <td style={{ color: '#e6edf3' }}>{ev.maneuver_type}</td>
                            </tr>
                          )}
                          {ev.regime && (
                            <tr>
                              <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 3, whiteSpace: 'nowrap' }}>regime</td>
                              <td style={{ color: '#e6edf3' }}>{ev.regime}</td>
                            </tr>
                          )}
                          <tr>
                            <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 6, whiteSpace: 'nowrap', fontWeight: 600 }} colSpan={2}>JCO report</td>
                          </tr>
                          {[
                            ['delta_v', ev.jco_delta_v ?? ev.delta_v, 'm/s'],
                            ['period_change', ev.jco_period_change ?? ev.period_change, 'sec'],
                            ['apogee_change', ev.jco_apogee_change ?? ev.apogee_change, 'km'],
                            ['perigee_change', ev.jco_perigee_change ?? ev.perigee_change, 'km'],
                            ['incl_change', ev.jco_incl_change ?? ev.inclination_change, 'deg'],
                          ].map(([k, v, unit]) => v != null && (
                            <tr key={String(k)}>
                              <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 3, whiteSpace: 'nowrap', paddingLeft: 8 }}>{k}</td>
                              <td style={{ color: '#e6edf3' }}>{sign(v as number)} {unit}</td>
                            </tr>
                          ))}
                          {ev.tle_available && (
                            <>
                              <tr>
                                <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 6, whiteSpace: 'nowrap', fontWeight: 600 }} colSpan={2}>TLE computed</td>
                              </tr>
                              {[
                                ['delta_v_est', ev.tle_delta_v_est, 'm/s'],
                                ['period_change', ev.tle_period_change, 'min'],
                                ['incl_change', ev.tle_incl_change, 'deg'],
                              ].map(([k, v, unit]) => v != null && (
                                <tr key={`tle_${k}`}>
                                  <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 3, whiteSpace: 'nowrap', paddingLeft: 8 }}>{k}</td>
                                  <td style={{ color: '#e6edf3' }}>{sign(v as number)} {unit}</td>
                                </tr>
                              ))}
                              {ev.discrepancy_flag && (
                                <tr>
                                  <td style={{ color: '#f0a500', paddingTop: 4, paddingLeft: 8 }} colSpan={2}>
                                    ⚠ {((ev.discrepancy_pct ?? 0) * 100).toFixed(0)}% discrepancy — possible unreported component or TLE update lag
                                  </td>
                                </tr>
                              )}
                            </>
                          )}
                          {ev.tle_available === false && (
                            <tr>
                              <td style={{ color: '#484f58', paddingTop: 4, fontStyle: 'italic', paddingLeft: 8 }} colSpan={2}>TLE not yet updated</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    ) : (
                      <table style={{ fontSize: 11, borderCollapse: 'collapse', width: '100%' }}>
                        <tbody>
                          <tr>
                            <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 3 }}>magnitude</td>
                            <td style={{ color: '#e6edf3' }}>
                              {ev.magnitude_change_min}–{ev.magnitude_change_max} ({ev.magnitude_direction})
                            </td>
                          </tr>
                          {ev.recovery_date && (
                            <tr>
                              <td style={{ color: '#484f58', paddingRight: 10, paddingTop: 3 }}>recovered</td>
                              <td style={{ color: '#e6edf3' }}>{ev.recovery_date}</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    )}

                    {/* Source link */}
                    {(ev.report_title || ev.source_id) && (
                      <div style={{ marginTop: 6, fontSize: 10, color: '#484f58' }}>
                        Source:{' '}
                        <SourceLink sourceId={ev.source_id} title={ev.report_title} />
                      </div>
                    )}

                    <button onClick={() => handleDelete(ev.id)} style={{
                      marginTop: 6, background: 'none', border: 'none',
                      color: '#484f58', fontSize: 10, cursor: 'pointer', padding: 0,
                    }}>
                      Delete event
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function SourceLink({ sourceId, title }: { sourceId?: string; title?: string }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!sourceId) return;
    fetch(`http://localhost:8000/api/kg/sources/${encodeURIComponent(sourceId)}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.url) setUrl(d.url); })
      .catch(() => {});
  }, [sourceId]);

  const label = title || sourceId || 'Source';
  if (url) {
    return <a href={url} target="_blank" rel="noreferrer" style={{ color: '#58a6ff' }}>{label} →</a>;
  }
  return <span style={{ color: '#8b949e' }}>{label}</span>;
}

function NoradFinderWidget({ nodeId, notosId, onAssigned }: {
  nodeId: string;
  notosId: string;
  onAssigned: (noradId: string) => void;
}) {
  const [candidates, setCandidates] = useState<NoradCandidate[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [manualInput, setManualInput] = useState('');
  const [assigning, setAssigning] = useState<string | null>(null);
  const [assignResult, setAssignResult] = useState<{ tle_found: boolean; positions_computed: number } | null>(null);
  const [assignError, setAssignError] = useState<string | null>(null);

  const search = async () => {
    setSearching(true);
    setSearchError(null);
    setCandidates(null);
    try {
      const results = await findNoradCandidates(nodeId);
      setCandidates(results);
    } catch (e: any) {
      setSearchError(e.message ?? 'Search failed');
    } finally {
      setSearching(false);
    }
  };

  const assign = async (noradId: string) => {
    if (!noradId.trim() || !/^\d+$/.test(noradId.trim())) {
      setAssignError('NORAD ID must be numeric');
      return;
    }
    setAssigning(noradId);
    setAssignError(null);
    setAssignResult(null);
    try {
      const result = await assignNoradId(nodeId, noradId.trim());
      setAssignResult(result);
      onAssigned(noradId.trim());
    } catch (e: any) {
      setAssignError(e.message ?? 'Assignment failed');
    } finally {
      setAssigning(null);
    }
  };

  return (
    <div style={{ marginTop: 16, padding: '10px 12px', background: '#0d1117', borderRadius: 6, border: '1px solid #21262d' }}>
      <div style={{ color: '#8b949e', fontSize: 11, marginBottom: 8, fontWeight: 600 }}>NORAD ID</div>

      {assignResult && (
        <div style={{ marginBottom: 8, fontSize: 11, color: '#3fb950' }}>
          Assigned. TLE: {assignResult.tle_found ? `found (${assignResult.positions_computed} positions)` : 'not yet available'}
        </div>
      )}
      {assignError && (
        <div style={{ marginBottom: 8, fontSize: 11, color: '#f78166' }}>{assignError}</div>
      )}

      {/* Search button */}
      {candidates === null && (
        <button
          onClick={search}
          disabled={searching}
          style={{
            width: '100%', padding: '5px 0', fontSize: 12,
            background: '#21262d', border: '1px solid #30363d', borderRadius: 4,
            color: searching ? '#484f58' : '#e6edf3', cursor: searching ? 'default' : 'pointer',
            marginBottom: 8,
          }}
        >
          {searching ? 'Searching CelesTrak…' : 'Find NORAD ID'}
        </button>
      )}
      {searchError && (
        <div style={{ fontSize: 11, color: '#d29922', marginBottom: 8 }}>{searchError}</div>
      )}

      {/* Candidate results */}
      {candidates !== null && (
        <div style={{ marginBottom: 8 }}>
          {candidates.length === 0 ? (
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 6 }}>No close matches found in CelesTrak.</div>
          ) : (
            <div style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 10, color: '#484f58', marginBottom: 4 }}>NORAD CANDIDATES</div>
              {candidates.map((c) => (
                <div key={c.norad_id} style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '4px 0', borderBottom: '1px solid #21262d',
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11, color: '#e6edf3', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {c.norad_id} · {c.name}
                    </div>
                    <div style={{ fontSize: 10, color: '#8b949e' }}>
                      {c.inclination.toFixed(1)}°  {c.period.toFixed(1)} min  {c.launch_date}
                      <span style={{ color: '#3fb950', marginLeft: 6 }}>score {(c.score * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                  <button
                    onClick={() => assign(c.norad_id)}
                    disabled={!!assigning}
                    style={{
                      padding: '2px 8px', fontSize: 10, borderRadius: 4,
                      background: '#238636', border: 'none',
                      color: assigning === c.norad_id ? '#484f58' : '#fff',
                      cursor: assigning ? 'default' : 'pointer', flexShrink: 0,
                    }}
                  >
                    {assigning === c.norad_id ? '…' : 'Assign'}
                  </button>
                </div>
              ))}
            </div>
          )}
          <button
            onClick={search}
            disabled={searching}
            style={{ fontSize: 10, background: 'none', border: 'none', color: '#58a6ff', cursor: 'pointer', padding: 0 }}
          >
            {searching ? 'Searching…' : '↻ Search again'}
          </button>
        </div>
      )}

      {/* Manual entry */}
      <div style={{ fontSize: 10, color: '#484f58', marginBottom: 4 }}>
        {candidates !== null ? 'No match? Enter manually:' : 'Or enter directly:'}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          value={manualInput}
          onChange={(e) => setManualInput(e.target.value)}
          placeholder="e.g. 65853"
          style={{
            flex: 1, background: '#161b22', border: '1px solid #30363d',
            borderRadius: 4, color: '#e6edf3', fontSize: 12, padding: '4px 8px',
          }}
        />
        <button
          onClick={() => assign(manualInput)}
          disabled={!!assigning || !manualInput.trim()}
          style={{
            padding: '4px 10px', fontSize: 12, borderRadius: 4,
            background: '#1f6feb', border: 'none',
            color: !manualInput.trim() ? '#484f58' : '#fff',
            cursor: assigning || !manualInput.trim() ? 'default' : 'pointer',
          }}
        >
          {assigning === manualInput.trim() ? '…' : 'Assign'}
        </button>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ color: '#8b949e', fontSize: 11, marginBottom: 2 }}>{label}</div>
      <div style={{ color: '#e6edf3', fontSize: 13 }}>{value || '—'}</div>
    </div>
  );
}
