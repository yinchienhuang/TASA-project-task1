import { useState } from 'react';

const API = 'http://localhost:8000';

// ── Types ─────────────────────────────────────────────────────────────────────

interface WikiSearchResult {
  title: string;
  description: string;
  url: string;
}

interface WikiPage {
  title: string;
  lang: string;
  page_type: string;
  description: string;
  extract: string;
  infobox: Record<string, string>;
  categories: string[];
  wikidata_id: string;
  last_modified: string;
  url: string;
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function searchWiki(q: string, lang: string): Promise<WikiSearchResult[]> {
  try {
    const r = await fetch(`${API}/api/wiki/search?q=${encodeURIComponent(q)}&lang=${lang}&limit=12`);
    return r.ok ? r.json() : [];
  } catch { return []; }
}

async function fetchWikiPage(title: string, lang: string): Promise<WikiPage | null> {
  try {
    const r = await fetch(`${API}/api/wiki/page?title=${encodeURIComponent(title)}&lang=${lang}`);
    return r.ok ? r.json() : null;
  } catch { return null; }
}

async function ingestWikiPage(title: string, lang: string, mode: 'review' | 'auto'): Promise<Record<string, unknown> | null> {
  try {
    const r = await fetch(`${API}/api/wiki/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, lang, mode }),
    });
    return r.ok ? r.json() : null;
  } catch { return null; }
}

// ── Language options ──────────────────────────────────────────────────────────

const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'zh', label: 'Chinese (中文)' },
  { code: 'ja', label: 'Japanese (日本語)' },
  { code: 'ko', label: 'Korean (한국어)' },
  { code: 'fr', label: 'French (Français)' },
  { code: 'de', label: 'German (Deutsch)' },
  { code: 'ru', label: 'Russian (Русский)' },
  { code: 'ar', label: 'Arabic (العربية)' },
  { code: 'es', label: 'Spanish (Español)' },
];

// ── Main component ─────────────────────────────────────────────────────────────

export default function WikiView() {
  const [lang, setLang]             = useState('en');
  const [query, setQuery]           = useState('');
  const [searching, setSearching]   = useState(false);
  const [results, setResults]       = useState<WikiSearchResult[]>([]);
  const [page, setPage]             = useState<WikiPage | null>(null);
  const [fetching, setFetching]     = useState(false);
  const [ingesting, setIngesting]   = useState(false);
  const [ingestMsg, setIngestMsg]   = useState<{ text: string; color: string } | null>(null);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setResults([]);
    setPage(null);
    setIngestMsg(null);
    const res = await searchWiki(query.trim(), lang);
    setResults(res);
    setSearching(false);
  };

  const handleFetch = async (title: string) => {
    setFetching(true);
    setPage(null);
    setIngestMsg(null);
    const p = await fetchWikiPage(title, lang);
    setPage(p);
    setFetching(false);
  };

  const handleIngest = async (mode: 'review' | 'auto') => {
    if (!page) return;
    setIngesting(true);
    setIngestMsg({ text: 'Sending to KG pipeline…', color: '#e3b341' });
    const res = await ingestWikiPage(page.title, lang, mode);
    if (!res) {
      setIngestMsg({ text: 'Ingest failed — check backend logs', color: '#f78166' });
    } else if (res.status === 'already_ingested') {
      setIngestMsg({ text: 'Already ingested (no LLM calls made)', color: '#8b949e' });
    } else if (mode === 'auto') {
      setIngestMsg({ text: 'Auto-applied to KG', color: '#3fb950' });
    } else {
      setIngestMsg({ text: `${res.proposed ?? 0} proposals queued for review`, color: '#3fb950' });
    }
    setIngesting(false);
  };

  return (
    <div style={{ display: 'flex', height: '100%', background: '#0d1117', color: '#e6edf3', fontFamily: 'inherit' }}>

      {/* ── Left: Search panel ── */}
      <div style={{ width: 340, flexShrink: 0, borderRight: '1px solid #21262d', display: 'flex', flexDirection: 'column' }}>

        {/* Header */}
        <div style={{ padding: '8px 12px', borderBottom: '1px solid #21262d', background: '#161b22', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: '#e6edf3' }}>Wikipedia Search</span>
          <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 10, background: '#58a6ff22', color: '#58a6ff', border: '1px solid #58a6ff44' }}>
            {results.length > 0 ? `${results.length} results` : 'no results'}
          </span>
        </div>

        {/* Language + search form */}
        <div style={{ padding: '10px 12px', borderBottom: '1px solid #21262d', flexShrink: 0 }}>
          <div style={{ fontSize: 10, color: '#484f58', marginBottom: 4 }}>LANGUAGE</div>
          <select
            value={lang}
            onChange={(e) => setLang(e.target.value)}
            style={{ ...inputStyle, marginBottom: 8 }}
          >
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>{l.label}</option>
            ))}
          </select>

          <div style={{ fontSize: 10, color: '#484f58', marginBottom: 4 }}>SEARCH</div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="e.g. FORMOSAT-7, ISS, Starlink"
              style={{ ...inputStyle, flex: 1 }}
            />
            <button
              onClick={handleSearch}
              disabled={searching || !query.trim()}
              style={{ ...primaryBtn, opacity: (searching || !query.trim()) ? 0.6 : 1 }}
            >
              {searching ? '…' : 'Search'}
            </button>
          </div>
        </div>

        {/* Results list */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {results.length === 0 && !searching && (
            <div style={{ padding: 20, color: '#484f58', fontSize: 12, textAlign: 'center' }}>
              Search to find Wikipedia articles.
            </div>
          )}
          {results.map((r) => (
            <div key={r.title} style={{
              padding: '10px 12px', borderBottom: '1px solid #161b22',
              background: page?.title === r.title ? '#0d1a26' : 'transparent',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'flex-start' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: 12, color: '#e6edf3', fontWeight: 500,
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                    marginBottom: 3,
                  }}>{r.title}</div>
                  {r.description && (
                    <div style={{ fontSize: 11, color: '#8b949e', lineHeight: 1.4 }}>
                      {r.description.length > 90 ? r.description.slice(0, 90) + '…' : r.description}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => handleFetch(r.title)}
                  disabled={fetching}
                  style={{ ...secondaryBtn, fontSize: 10, padding: '3px 8px', flexShrink: 0 }}
                >
                  → Fetch
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Right: Article detail ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflowY: 'auto' }}>
        {fetching ? (
          <div style={{ padding: 40, color: '#8b949e', fontSize: 13, textAlign: 'center' }}>
            Fetching article…
          </div>
        ) : !page ? (
          <div style={{ padding: 40, color: '#484f58', fontSize: 13, textAlign: 'center' }}>
            Select a search result to preview the article.
          </div>
        ) : (
          <div style={{ padding: 20 }}>

            {/* Title row */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
              <h2 style={{ margin: 0, fontSize: 18, color: '#e6edf3', fontWeight: 600 }}>{page.title}</h2>
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 10,
                background: '#58a6ff22', color: '#58a6ff', border: '1px solid #58a6ff44',
                flexShrink: 0,
              }}>
                {LANGUAGES.find((l) => l.code === page.lang)?.label ?? page.lang}
              </span>
              {page.page_type === 'disambiguation' && (
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 10,
                  background: '#e3b34122', color: '#e3b341', border: '1px solid #e3b34144',
                }}>
                  disambiguation
                </span>
              )}
              <a
                href={page.url}
                target="_blank"
                rel="noreferrer"
                style={{ fontSize: 11, color: '#58a6ff', textDecoration: 'none', marginLeft: 'auto', flexShrink: 0 }}
              >
                ↗ Wikipedia
              </a>
            </div>

            {/* Metadata row */}
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 16, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              {page.last_modified && <span>Last modified: {page.last_modified}</span>}
              {page.wikidata_id && <span>Wikidata: <span style={{ color: '#484f58' }}>{page.wikidata_id}</span></span>}
            </div>

            {/* Description */}
            {page.description && (
              <p style={{ margin: '0 0 16px', fontSize: 13, color: '#c9d1d9', lineHeight: 1.5 }}>
                {page.description}
              </p>
            )}

            {/* Infobox */}
            {Object.keys(page.infobox).length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 6, letterSpacing: '0.05em' }}>INFOBOX</div>
                <div style={{
                  background: '#161b22', borderRadius: 6, border: '1px solid #21262d',
                  padding: '10px 12px',
                  display: 'grid', gridTemplateColumns: '160px 1fr', gap: '4px 12px',
                }}>
                  {Object.entries(page.infobox).map(([k, v]) => (
                    <>
                      <span key={k + '_k'} style={{ fontSize: 11, color: '#8b949e', paddingTop: 1 }}>{k}</span>
                      <span key={k + '_v'} style={{ fontSize: 11, color: '#e6edf3', wordBreak: 'break-word' }}>{v}</span>
                    </>
                  ))}
                </div>
              </div>
            )}

            {/* Categories */}
            {page.categories.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 6, letterSpacing: '0.05em' }}>CATEGORIES</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {page.categories.map((cat) => (
                    <span key={cat} style={{
                      fontSize: 10, padding: '2px 8px', borderRadius: 10,
                      background: '#21262d', border: '1px solid #30363d', color: '#8b949e',
                    }}>
                      {cat}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Article extract */}
            {page.extract && (
              <div style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 6, letterSpacing: '0.05em' }}>ARTICLE EXTRACT</div>
                <div style={{
                  fontSize: 12, color: '#c9d1d9', lineHeight: 1.6,
                  background: '#161b22', borderRadius: 6, padding: '10px 12px',
                  borderLeft: '3px solid #30363d',
                  maxHeight: 200, overflowY: 'auto',
                }}>
                  {page.extract.length > 800 ? page.extract.slice(0, 800) + '…' : page.extract}
                </div>
              </div>
            )}

            {/* Ingest actions */}
            <div style={{ borderTop: '1px solid #21262d', paddingTop: 16 }}>
              <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 8, letterSpacing: '0.05em' }}>INGEST TO KNOWLEDGE GRAPH</div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  onClick={() => handleIngest('review')}
                  disabled={ingesting}
                  style={{ ...primaryBtn, opacity: ingesting ? 0.6 : 1 }}
                >
                  {ingesting ? 'Ingesting…' : 'Ingest (Review)'}
                </button>
                <button
                  onClick={() => handleIngest('auto')}
                  disabled={ingesting}
                  style={{ ...secondaryBtn, opacity: ingesting ? 0.6 : 1 }}
                >
                  Ingest (Auto-apply)
                </button>
                {ingestMsg && (
                  <span style={{ fontSize: 12, color: ingestMsg.color }}>{ingestMsg.text}</span>
                )}
              </div>
            </div>

          </div>
        )}
      </div>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  width: '100%', background: '#0d1117', border: '1px solid #30363d', borderRadius: 4,
  color: '#e6edf3', fontSize: 12, padding: '5px 8px', boxSizing: 'border-box', outline: 'none',
};

const primaryBtn: React.CSSProperties = {
  background: '#1f6feb', border: '1px solid #388bfd', borderRadius: 4,
  color: '#fff', cursor: 'pointer', fontSize: 12, padding: '5px 12px', whiteSpace: 'nowrap',
};

const secondaryBtn: React.CSSProperties = {
  background: '#21262d', border: '1px solid #30363d', borderRadius: 4,
  color: '#8b949e', cursor: 'pointer', fontSize: 12, padding: '5px 10px', whiteSpace: 'nowrap',
};
