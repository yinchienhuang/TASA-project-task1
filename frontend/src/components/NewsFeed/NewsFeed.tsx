import { useEffect, useState } from 'react';
import { useAppStore } from '../../store/appStore';
import { getNews, refreshNews, refreshNewsBySatellite, getKGSatellites } from '../../api/client';
import type { NewsArticle } from '../../api/client';

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  } catch { return iso.slice(0, 10); }
}

const API = 'http://localhost:8000';

async function addToQueue(article: NewsArticle): Promise<boolean> {
  try {
    const r = await fetch(`${API}/api/kg/incoming`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'url',
        title: article.title,
        url: article.url,
        content: '',
      }),
    });
    return r.ok;
  } catch { return false; }
}

// Stable tag colors by index (cycles for unknown satellites)
const TAG_COLORS = [
  { bg: '#0d2133', fg: '#58a6ff', border: '#388bfd44' },
  { bg: '#0d2a1a', fg: '#3fb950', border: '#2ea04344' },
  { bg: '#3d1a1a', fg: '#e8163c', border: '#e8163c44' },
  { bg: '#2d2000', fg: '#f0a500', border: '#f0a50044' },
  { bg: '#1a1a3a', fg: '#bc8cff', border: '#8b5cf644' },
  { bg: '#1a2d2d', fg: '#39d0d0', border: '#1a9a9a44' },
];

export default function NewsFeed() {
  const { selectedSatelliteId } = useAppStore();
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastTotal, setLastTotal] = useState<number | null>(null);
  const [queued, setQueued] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  // noradId → name map built from KG satellite list
  const [satNames, setSatNames] = useState<Record<string, string>>({});

  useEffect(() => {
    getKGSatellites().then((sats) => {
      const map: Record<string, string> = {};
      for (const s of sats) {
        if (s.noradId) map[s.noradId] = s.name;
      }
      setSatNames(map);
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getNews(selectedSatelliteId ?? undefined).then((data) => {
      if (!cancelled) { setArticles(data); setLoading(false); }
    });
    return () => { cancelled = true; };
  }, [selectedSatelliteId]);

  const handleRefresh = async () => {
    setRefreshing(true);
    const result = selectedSatelliteId
      ? await refreshNewsBySatellite(selectedSatelliteId)
      : await refreshNews();
    if (result) {
      setLastTotal(result.new_articles > 0 ? result.total : lastTotal);
      const data = await getNews(selectedSatelliteId ?? undefined);
      setArticles(data);
    }
    setRefreshing(false);
  };

  const filterLabel = selectedSatelliteId
    ? (satNames[selectedSatelliteId] ?? selectedSatelliteId)
    : 'All satellites';

  const q = search.trim().toLowerCase();
  const filteredArticles = q
    ? articles.filter((a) => {
        if (a.title.toLowerCase().includes(q)) return true;
        if (a.news_site.toLowerCase().includes(q)) return true;
        if ((a.related_norad_ids ?? []).some((id) => (satNames[id] ?? id).toLowerCase().includes(q))) return true;
        return false;
      })
    : articles;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0d1117', color: '#e6edf3' }}>
      {/* Header */}
      <div style={{
        padding: '8px 12px', borderBottom: '1px solid #21262d',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: '#e6edf3' }}>Spaceflight News</span>
          <span style={{
            fontSize: 10, padding: '1px 6px', borderRadius: 10,
            background: selectedSatelliteId ? '#1f6feb' : '#21262d',
            color: selectedSatelliteId ? '#fff' : '#8b949e',
            border: `1px solid ${selectedSatelliteId ? '#388bfd' : '#30363d'}`,
          }}>
            {filterLabel}
          </span>
          {lastTotal !== null && (
            <span style={{ fontSize: 10, color: '#8b949e' }}>{lastTotal} total</span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            title={selectedSatelliteId ? `Re-fetch news for ${filterLabel}` : 'Re-fetch all KG satellites'}
            style={{
              background: 'none', border: '1px solid #30363d', borderRadius: 4,
              color: refreshing ? '#8b949e' : '#58a6ff', cursor: refreshing ? 'default' : 'pointer',
              padding: '2px 8px', fontSize: 11,
            }}
          >
            {refreshing ? 'Fetching…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {/* Search bar */}
      <div style={{ padding: '6px 12px', borderBottom: '1px solid #21262d', flexShrink: 0 }}>
        <input
          type="text"
          placeholder="Search title, source, satellite…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            width: '100%', boxSizing: 'border-box',
            background: '#161b22', border: '1px solid #30363d', borderRadius: 4,
            color: '#e6edf3', fontSize: 11, padding: '4px 8px', outline: 'none',
          }}
        />
      </div>

      {/* Article list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
        {loading ? (
          <div style={{ padding: 20, textAlign: 'center', color: '#8b949e', fontSize: 12 }}>Loading…</div>
        ) : filteredArticles.length === 0 ? (
          <div style={{ padding: 20, textAlign: 'center', color: '#8b949e', fontSize: 12 }}>
            {q ? `No results for "${search}".` : (selectedSatelliteId ? 'No articles found. Try "All satellites" or click Refresh.' : 'No articles found. Click Refresh to fetch.')}
          </div>
        ) : filteredArticles.map((a) => (
          <div key={a.source_id} style={{
            padding: '10px 12px', borderBottom: '1px solid #161b22',
            transition: 'background 0.1s',
          }}
            onMouseEnter={(e) => (e.currentTarget.style.background = '#161b22')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          >
            {/* Source + date row */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, flexWrap: 'wrap' }}>
              <span style={{
                fontSize: 10, padding: '0 5px', borderRadius: 3,
                background: '#21262d', color: '#8b949e', border: '1px solid #30363d',
                whiteSpace: 'nowrap',
              }}>
                {a.news_site}
              </span>
              <span style={{ fontSize: 10, color: '#6e7681' }}>{formatDate(a.date)}</span>
              {/* Satellite tags — derived from KG satellite names */}
              {(a.related_norad_ids ?? []).map((id, idx) => {
                const c = TAG_COLORS[idx % TAG_COLORS.length];
                return (
                  <span key={id} style={{
                    fontSize: 9, padding: '0 4px', borderRadius: 3,
                    background: c.bg, color: c.fg, border: `1px solid ${c.border}`,
                  }}>
                    {satNames[id] ?? id}
                  </span>
                );
              })}
            </div>
            {/* Title */}
            <a
              href={a.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontSize: 12, fontWeight: 600, color: '#e6edf3', textDecoration: 'none', lineHeight: 1.4, display: 'block', marginBottom: 4 }}
              onMouseEnter={(e) => ((e.target as HTMLElement).style.color = '#58a6ff')}
              onMouseLeave={(e) => ((e.target as HTMLElement).style.color = '#e6edf3')}
            >
              {a.title}
            </a>
            {/* Queue button */}
            <div style={{ marginTop: 6 }}>
              <button
                onClick={async (e) => {
                  e.preventDefault();
                  const ok = await addToQueue(a);
                  if (ok) setQueued((prev) => new Set(prev).add(a.source_id));
                }}
                disabled={queued.has(a.source_id)}
                style={{
                  fontSize: 10, padding: '2px 7px', borderRadius: 3, cursor: queued.has(a.id) ? 'default' : 'pointer',
                  background: queued.has(a.id) ? '#1a3a1a' : '#161b22',
                  color: queued.has(a.id) ? '#3fb950' : '#8b949e',
                  border: `1px solid ${queued.has(a.source_id) ? '#2ea04344' : '#30363d'}`,
                }}
              >
                {queued.has(a.source_id) ? '✓ Queued' : '+ Queue'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
