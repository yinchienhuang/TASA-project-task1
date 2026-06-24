import { useState } from 'react';
import { searchTLE, createSatellite } from '../../api/client';
import type { TLEMatch } from '../../api/client';

interface Props {
  onClose: () => void;
  onAdded: () => void;
}

export default function AddSatelliteModal({ onClose, onAdded }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<TLEMatch[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<TLEMatch | null>(null);
  const [nodeType, setNodeType] = useState('Satellite');
  const [keywords, setKeywords] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [mode, setMode] = useState<'search' | 'manual'>('search');
  const [manualTle, setManualTle] = useState({ name: '', noradId: '', line1: '', line2: '' });

  const search = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setResults([]);
    setSelected(null);
    setError('');
    const res = await searchTLE(query.trim());
    setResults(res);
    if (res.length === 0) setError('No satellites found. Try a different name.');
    setSearching(false);
  };

  const add = async () => {
    if (!selected) return;
    setSaving(true);
    setError('');
    try {
      await createSatellite({
        noradId: selected.noradId,
        name: selected.name,
        line1: selected.line1,
        line2: selected.line2,
        type: nodeType,
        newsKeywords: keywords,
      });
      onAdded();
      onClose();
    } catch (e: any) {
      setError(e.message ?? 'Failed to add satellite');
      setSaving(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 300,
      background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{
        background: '#161b22', border: '1px solid #30363d', borderRadius: 8,
        width: 480, maxHeight: '80vh', display: 'flex', flexDirection: 'column',
        boxShadow: '0 16px 48px rgba(0,0,0,0.6)',
      }}>
        {/* Header */}
        <div style={{
          padding: '12px 16px', borderBottom: '1px solid #30363d',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span style={{ color: '#58a6ff', fontWeight: 600, fontSize: 14 }}>Add Satellite</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 18 }}>×</button>
        </div>

        <div style={{ padding: 16, overflowY: 'auto', flex: 1 }}>
          {/* Search */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ color: '#484f58', fontSize: 10, marginBottom: 4 }}>SATELLITE NAME</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && search()}
                placeholder="e.g. Hubble, NOAA-20, Sentinel-2A"
                style={{
                  flex: 1, background: '#0d1117', border: '1px solid #30363d',
                  borderRadius: 4, color: '#e6edf3', fontSize: 12, padding: '6px 8px',
                }}
              />
              <button
                onClick={search}
                disabled={searching || !query.trim()}
                style={{
                  background: '#1f6feb', border: 'none', borderRadius: 4,
                  color: '#fff', cursor: searching ? 'default' : 'pointer',
                  padding: '0 14px', fontSize: 12, opacity: searching ? 0.6 : 1,
                }}
              >
                {searching ? 'Searching…' : 'Search'}
              </button>
            </div>
          </div>

          {/* Results */}
          {results.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ color: '#484f58', fontSize: 10, marginBottom: 4 }}>
                SELECT SATELLITE ({results.length} results)
              </div>
              <div style={{
                maxHeight: 180, overflowY: 'auto',
                border: '1px solid #21262d', borderRadius: 4,
              }}>
                {results.map((r) => (
                  <div
                    key={r.noradId}
                    onClick={() => setSelected(r)}
                    style={{
                      padding: '7px 10px', cursor: 'pointer', fontSize: 12,
                      background: selected?.noradId === r.noradId ? '#1f3a5f' : 'transparent',
                      borderBottom: '1px solid #21262d',
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    }}
                  >
                    <span style={{ color: '#e6edf3' }}>{r.name}</span>
                    <span style={{ color: '#484f58', fontSize: 10 }}>#{r.noradId}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Selected details */}
          {selected && (
            <>
              <div style={{ marginBottom: 10, padding: 10, background: '#0d1117', borderRadius: 4 }}>
                <div style={{ color: '#8b949e', fontSize: 10, marginBottom: 4 }}>TLE</div>
                <pre style={{ color: '#484f58', fontSize: 10, margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
                  {selected.line1}{'\n'}{selected.line2}
                </pre>
              </div>

              <div style={{ marginBottom: 10 }}>
                <div style={{ color: '#484f58', fontSize: 10, marginBottom: 4 }}>NODE TYPE</div>
                <input
                  value={nodeType}
                  onChange={(e) => setNodeType(e.target.value)}
                  placeholder="Satellite, CivilSatellite, MilitarySatellite…"
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    background: '#0d1117', border: '1px solid #30363d',
                    borderRadius: 4, color: '#e6edf3', fontSize: 12, padding: '5px 8px',
                  }}
                />
              </div>

              <div style={{ marginBottom: 10 }}>
                <div style={{ color: '#484f58', fontSize: 10, marginBottom: 4 }}>NEWS KEYWORDS (optional)</div>
                <input
                  value={keywords}
                  onChange={(e) => setKeywords(e.target.value)}
                  placeholder="comma-separated, e.g. Hubble, Hubble Space Telescope"
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    background: '#0d1117', border: '1px solid #30363d',
                    borderRadius: 4, color: '#e6edf3', fontSize: 12, padding: '5px 8px',
                  }}
                />
              </div>
            </>
          )}

          {error && (
            <div style={{ color: '#f78166', fontSize: 12, marginBottom: 8 }}>{error}</div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '10px 16px', borderTop: '1px solid #30363d',
          display: 'flex', gap: 8, justifyContent: 'flex-end',
        }}>
          <button onClick={onClose} style={{
            background: 'none', border: '1px solid #30363d', borderRadius: 4,
            color: '#8b949e', cursor: 'pointer', padding: '5px 16px', fontSize: 12,
          }}>Cancel</button>
          <button
            onClick={add}
            disabled={!selected || saving}
            style={{
              background: selected ? '#238636' : '#21262d',
              border: `1px solid ${selected ? '#2ea043' : '#30363d'}`,
              borderRadius: 4, color: selected ? '#fff' : '#484f58',
              cursor: selected && !saving ? 'pointer' : 'default',
              padding: '5px 16px', fontSize: 12,
            }}
          >
            {saving ? 'Adding…' : 'Add Satellite'}
          </button>
        </div>
      </div>
    </div>
  );
}
