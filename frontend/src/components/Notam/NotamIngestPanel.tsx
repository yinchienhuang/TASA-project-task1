import { useEffect, useRef, useState } from 'react';
import { ingestNotamText, getLaunchEvents } from '../../api/client';
import type { SatelliteEvent } from '../../api/client';
import { useAppStore } from '../../store/appStore';
import type { TrajectoryZone } from '../../store/appStore';

function zonesFromEvents(events: SatelliteEvent[]): TrajectoryZone[] {
  const zones: TrajectoryZone[] = [];
  for (const ev of events) {
    const raw = (ev as unknown as { trajectory_zones?: unknown[] }).trajectory_zones ?? [];
    for (const z of raw) {
      zones.push(z as TrajectoryZone);
    }
  }
  return zones;
}

function zoneStatus(zone: TrajectoryZone): 'active' | 'past' | 'future' {
  const now = Date.now();
  const start = new Date(zone.active_start).getTime();
  const end = new Date(zone.active_end).getTime();
  if (now >= start && now <= end) return 'active';
  if (now > end) return 'past';
  return 'future';
}

function formatUtc(iso: string): string {
  return iso.replace('T', ' ').replace(':00Z', ' UTC').replace('Z', ' UTC');
}

function zoneCentroid(zone: TrajectoryZone): { lat: number; lon: number } | null {
  if (zone.shape === 'circle' && zone.center_lat != null && zone.center_lon != null) {
    return { lat: zone.center_lat, lon: zone.center_lon };
  }
  if (zone.shape === 'polygon' && zone.vertices && zone.vertices.length > 0) {
    const lats = zone.vertices.map(([lat]) => lat);
    const lons = zone.vertices.map(([, lon]) => lon);
    return {
      lat: lats.reduce((a, b) => a + b, 0) / lats.length,
      lon: lons.reduce((a, b) => a + b, 0) / lons.length,
    };
  }
  return null;
}

const STATUS_COLOR = { active: '#3fb950', past: '#484f58', future: '#e3b341' };
const STATUS_LABEL = { active: 'ACTIVE', past: 'PAST', future: 'UPCOMING' };

export default function NotamIngestPanel() {
  const [text, setText] = useState('');
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState<{ count: number; msg: string; color: string } | null>(null);
  const [events, setEvents] = useState<SatelliteEvent[]>([]);
  const { setNotamZones } = useAppStore();
  const focusRef = useRef<((lat: number, lon: number) => void) | null>(null);

  // Expose a focus callback so EarthView can register itself
  useEffect(() => {
    (window as unknown as Record<string, unknown>).__notamFocusCallback = (lat: number, lon: number) => {
      focusRef.current?.(lat, lon);
    };
  }, []);

  const reload = async () => {
    const evs = await getLaunchEvents();
    setEvents(evs);
    setNotamZones(zonesFromEvents(evs));
  };

  useEffect(() => { reload(); }, []);

  const handleProcess = async () => {
    if (!text.trim()) return;
    setProcessing(true);
    setResult(null);
    try {
      const res = await ingestNotamText(text.trim());
      if (res.count === 0) {
        setResult({ count: 0, msg: 'No new events extracted (may already be stored or not a valid NOTAM)', color: '#e3b341' });
      } else {
        setResult({ count: res.count, msg: `${res.count} event${res.count > 1 ? 's' : ''} extracted and stored`, color: '#3fb950' });
        setText('');
      }
      await reload();
    } catch (e) {
      setResult({ count: 0, msg: `Error: ${(e as Error).message}`, color: '#f78166' });
    }
    setProcessing(false);
  };

  const handleDelete = async (eventId: string) => {
    await fetch(`http://localhost:8000/api/events/${encodeURIComponent(eventId)}`, { method: 'DELETE' });
    await reload();
  };

  const handleFocus = (zone: TrajectoryZone) => {
    const c = zoneCentroid(zone);
    if (!c) return;
    // Signal EarthView via custom event
    window.dispatchEvent(new CustomEvent('notam:focus', { detail: { lat: c.lat, lon: c.lon } }));
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0d1117', color: '#e6edf3', fontSize: 13 }}>
      {/* Input area */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #30363d', flexShrink: 0 }}>
        <div style={{ color: '#484f58', fontSize: 11, fontWeight: 600, letterSpacing: '0.05em', marginBottom: 8 }}>
          NOTAM TEXT INPUT
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={'Paste raw ICAO NOTAM text here…\n\nExample:\nA1801/26 NOTAMN\nQ)ZXXX/QRDCA/IV/BO/W/000/999/2030N10915E020\nA)ZJSA ZGZU B)2605301800 C)2605301826\nE) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:\nN204000E1085600-N205000E1091000-N202100E1093400-N201100E1092100,\nBACK TO START. VERTICAL LIMITS:SFC-UNL.'}
          rows={8}
          style={{
            width: '100%', boxSizing: 'border-box', resize: 'vertical',
            background: '#161b22', border: '1px solid #30363d', borderRadius: 6,
            color: '#e6edf3', fontSize: 12, fontFamily: 'monospace',
            padding: '8px 10px', outline: 'none', lineHeight: 1.5,
          }}
        />
        <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}>
          <button
            onClick={handleProcess}
            disabled={processing || !text.trim()}
            style={{
              background: processing || !text.trim() ? '#21262d' : '#1f6feb',
              border: 'none', borderRadius: 6, color: processing || !text.trim() ? '#484f58' : '#fff',
              cursor: processing || !text.trim() ? 'default' : 'pointer',
              fontSize: 12, fontWeight: 600, padding: '6px 16px',
            }}
          >
            {processing ? 'Processing…' : 'Process NOTAM'}
          </button>
          <button
            onClick={() => { setText(''); setResult(null); }}
            style={{
              background: 'none', border: '1px solid #30363d', borderRadius: 6,
              color: '#8b949e', cursor: 'pointer', fontSize: 12, padding: '6px 12px',
            }}
          >
            Clear
          </button>
          {result && (
            <span style={{ fontSize: 11, color: result.color, marginLeft: 4 }}>{result.msg}</span>
          )}
        </div>
      </div>

      {/* Stored NOTAM events */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>
        <div style={{ color: '#484f58', fontSize: 11, fontWeight: 600, letterSpacing: '0.05em', marginBottom: 10 }}>
          STORED NOTAM EVENTS ({events.length})
        </div>

        {events.length === 0 ? (
          <div style={{ color: '#484f58', fontSize: 12 }}>No NOTAM events stored yet.</div>
        ) : events.map((ev) => {
          const zones = (ev as unknown as { trajectory_zones?: TrajectoryZone[] }).trajectory_zones ?? [];
          const notamIds = (ev as unknown as { notam_ids?: string[] }).notam_ids ?? [];
          const start = (ev as unknown as { launch_time_start?: string }).launch_time_start ?? ev.event_date;
          const end = (ev as unknown as { launch_time_end?: string }).launch_time_end;
          const site = (ev as unknown as { launch_site?: string }).launch_site;

          return (
            <div
              key={ev.id}
              style={{
                background: '#161b22', borderRadius: 8, padding: '10px 12px',
                marginBottom: 10, border: '1px solid #30363d',
              }}
            >
              {/* Header row */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                <div>
                  <span style={{ color: '#e6edf3', fontWeight: 600, fontSize: 13 }}>
                    {notamIds.length > 0 ? notamIds.join(', ') : ev.id}
                  </span>
                  {ev.satellite_label && (
                    <span style={{ color: '#8b949e', fontSize: 11, marginLeft: 8 }}>{ev.satellite_label}</span>
                  )}
                </div>
                <button
                  onClick={() => handleDelete(ev.id)}
                  style={{
                    background: 'none', border: '1px solid #da3633', borderRadius: 4,
                    color: '#f78166', fontSize: 10, cursor: 'pointer', padding: '1px 6px',
                  }}
                >Delete</button>
              </div>

              {/* Time window */}
              <div style={{ color: '#8b949e', fontSize: 11, marginBottom: 4 }}>
                {formatUtc(start)}{end ? ` → ${formatUtc(end)}` : ''}
              </div>

              {/* Launch site */}
              {site && (
                <div style={{ color: '#58a6ff', fontSize: 11, marginBottom: 6 }}>{site}</div>
              )}

              {/* Trajectory zones */}
              {zones.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <div style={{ color: '#484f58', fontSize: 10, fontWeight: 600, marginBottom: 4 }}>RESTRICTED ZONES</div>
                  {zones.map((zone) => {
                    const status = zoneStatus(zone);
                    const statusColor = STATUS_COLOR[status];
                    const centroid = zoneCentroid(zone);
                    return (
                      <div
                        key={zone.notam_id}
                        style={{
                          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                          padding: '4px 8px', marginBottom: 4,
                          background: '#0d1117', borderRadius: 4,
                          border: `1px solid ${statusColor}44`,
                        }}
                      >
                        <div>
                          <span style={{ color: statusColor, fontSize: 10, fontWeight: 600, marginRight: 8 }}>
                            {STATUS_LABEL[status]}
                          </span>
                          <span style={{ color: '#8b949e', fontSize: 11 }}>
                            {zone.notam_id} · {zone.shape === 'circle'
                              ? `Circle r=${zone.radius_km} km`
                              : `Polygon ${zone.vertices?.length ?? 0} pts`}
                          </span>
                        </div>
                        {centroid && (
                          <button
                            onClick={() => handleFocus(zone)}
                            style={{
                              background: 'none', border: '1px solid #30363d', borderRadius: 4,
                              color: '#58a6ff', fontSize: 10, cursor: 'pointer', padding: '1px 8px',
                            }}
                          >
                            Focus
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
