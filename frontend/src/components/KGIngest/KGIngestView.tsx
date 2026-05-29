import React, { useEffect, useMemo, useRef, useState } from 'react';

const API = 'http://localhost:8000';

// ── Types ─────────────────────────────────────────────────────────────────────

interface IncomingDoc {
  id: string;
  type: 'url' | 'text';
  title: string;
  content: string;
  url: string;
  status: 'queued' | 'processing' | 'done' | 'error';
  added_at: string;
  processed_at: string | null;
  result: Record<string, unknown> | null;
}

interface PendingItem {
  id: string;
  type: 'node_add' | 'edge_add' | 'attribute_update' | 'conflict' | 'merge';
  status: 'pending' | 'approved' | 'rejected' | 'resolved';
  proposed?: Record<string, unknown>;
  evidence?: { excerpt: string; source: Record<string, unknown> };
  entity_id?: string;
  field?: string;
  old_value?: unknown;
  new_value?: unknown;
  conflict?: Record<string, unknown>;
  merge?: Record<string, unknown>;
  llm_assessment?: string;
  created_at: string;
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchIncoming(): Promise<IncomingDoc[]> {
  try {
    const r = await fetch(`${API}/api/kg/incoming`);
    if (!r.ok) return [];
    const d = await r.json();
    return d.incoming ?? [];
  } catch { return []; }
}

async function addIncoming(type: 'url' | 'text', title: string, content: string, url: string): Promise<IncomingDoc | null> {
  try {
    const r = await fetch(`${API}/api/kg/incoming`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, title, content, url }),
    });
    return r.ok ? r.json() : null;
  } catch { return null; }
}

async function deleteIncoming(id: string): Promise<void> {
  await fetch(`${API}/api/kg/incoming/${id}`, { method: 'DELETE' }).catch(() => {});
}

async function processIncoming(id: string, force = false): Promise<IncomingDoc | null> {
  try {
    const r = await fetch(`${API}/api/kg/incoming/${id}/process?mode=review${force ? '&force=true' : ''}`, { method: 'POST' });
    return r.ok ? r.json() : null;
  } catch { return null; }
}

async function fetchPending(statusFilter: string): Promise<PendingItem[]> {
  try {
    const r = await fetch(`${API}/api/kg/pending?status=${statusFilter}`);
    if (!r.ok) return [];
    const d = await r.json();
    return d.pending ?? [];
  } catch { return []; }
}

async function approvePending(id: string): Promise<boolean> {
  try {
    const r = await fetch(`${API}/api/kg/pending/${id}/approve`, { method: 'POST' });
    return r.ok;
  } catch { return false; }
}

async function rejectPending(id: string): Promise<boolean> {
  try {
    const r = await fetch(`${API}/api/kg/pending/${id}/reject`, { method: 'POST' });
    return r.ok;
  } catch { return false; }
}

async function resolveConflict(id: string, choice: string): Promise<boolean> {
  try {
    const r = await fetch(`${API}/api/kg/pending/${id}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ choice }),
    });
    return r.ok;
  } catch { return false; }
}

async function approveAll(): Promise<number> {
  try {
    const r = await fetch(`${API}/api/kg/pending/approve_all`, { method: 'POST' });
    if (!r.ok) return 0;
    const d = await r.json();
    return d.approved ?? 0;
  } catch { return 0; }
}

async function clearPending(): Promise<number> {
  try {
    const r = await fetch(`${API}/api/kg/pending`, { method: 'DELETE' });
    if (!r.ok) return 0;
    const d = await r.json();
    return d.removed ?? 0;
  } catch { return 0; }
}

interface SchemaNode { type: string; children: SchemaNode[]; }

async function fetchSchemaTree(): Promise<SchemaNode[]> {
  try {
    const r = await fetch(`${API}/api/kg/schema/tree`);
    if (!r.ok) return [];
    const d = await r.json();
    return d.tree ?? [];
  } catch { return []; }
}

async function updatePendingType(id: string, type: string): Promise<boolean> {
  try {
    const r = await fetch(`${API}/api/kg/pending/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type }),
    });
    return r.ok;
  } catch { return false; }
}

async function bulkIngestNews(): Promise<{ ingested: number; skipped: number } | null> {
  try {
    const r = await fetch(`${API}/api/kg/ingest/bulk`, { method: 'POST' });
    return r.ok ? r.json() : null;
  } catch { return null; }
}

async function clearAllIncoming(): Promise<boolean> {
  try {
    const r = await fetch(`${API}/api/kg/incoming`, { method: 'DELETE' });
    return r.ok;
  } catch { return false; }
}

// ── Colours ───────────────────────────────────────────────────────────────────

const TYPE_COLOR: Record<string, string> = {
  node_add: '#3fb950',
  edge_add: '#58a6ff',
  attribute_update: '#e3b341',
  conflict: '#f78166',
  merge: '#bc8cff',
};

const STATUS_COLOR: Record<string, string> = {
  queued: '#8b949e',
  processing: '#e3b341',
  done: '#3fb950',
  error: '#f78166',
};

function fmtDate(iso: string): string {
  try { return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  catch { return iso.slice(0, 16); }
}

// ── Component ─────────────────────────────────────────────────────────────────

async function fetchNodeLabels(): Promise<Map<string, string>> {
  try {
    const r = await fetch(`${API}/api/kg/full`);
    if (!r.ok) return new Map();
    const d = await r.json();
    return new Map((d.nodes ?? []).map((n: { id: string; label: string }) => [n.id, n.label]));
  } catch { return new Map(); }
}

export default function KGIngestView() {
  const [incoming, setIncoming] = useState<IncomingDoc[]>([]);
  const [pending, setPending] = useState<PendingItem[]>([]);
  const [pendingFilter, setPendingFilter] = useState<string>('pending');
  const [loadingPending, setLoadingPending] = useState(false);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [pdfUploading, setPdfUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Add-doc form state
  const [addMode, setAddMode] = useState<'url' | 'text'>('url');
  const [addInput, setAddInput] = useState('');
  const [addTitle, setAddTitle] = useState('');
  const [adding, setAdding] = useState(false);
  const [bulkIngesting, setBulkIngesting] = useState(false);
  const [bulkResult, setBulkResult] = useState<{ ingested: number; skipped: number } | null>(null);
  const [clearing, setClearing] = useState(false);
  const [schemaTree, setSchemaTree] = useState<SchemaNode[]>([]);
  const [nodeLabels, setNodeLabels] = useState<Map<string, string>>(new Map());

  const refreshIncoming = () => fetchIncoming().then(setIncoming);
  const refreshPending = () => {
    setLoadingPending(true);
    fetchPending(pendingFilter).then((d) => { setPending(d); setLoadingPending(false); });
  };

  useEffect(() => {
    refreshIncoming();
    fetchSchemaTree().then(setSchemaTree);
    fetchNodeLabels().then(setNodeLabels);
    // Poll incoming queue every 5s so News Feed additions appear without manual refresh
    const timer = setInterval(refreshIncoming, 5000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => { refreshPending(); }, [pendingFilter]);

  const handleAdd = async () => {
    if (!addInput.trim()) return;
    setAdding(true);
    await addIncoming(addMode, addTitle, addMode === 'text' ? addInput : '', addMode === 'url' ? addInput : '');
    setAddInput(''); setAddTitle('');
    await refreshIncoming();
    setAdding(false);
  };

  const handleProcess = async (id: string, force = false) => {
    setProcessingId(id);
    setIncoming((prev) => prev.map((d) => d.id === id ? { ...d, status: 'processing' } : d));
    const updated = await processIncoming(id, force);
    if (updated) setIncoming((prev) => prev.map((d) => d.id === id ? updated : d));
    else await refreshIncoming();
    setProcessingId(null);
    // Refresh pending after processing
    setTimeout(refreshPending, 500);
  };

  const handleDelete = async (id: string) => {
    await deleteIncoming(id);
    setIncoming((prev) => prev.filter((d) => d.id !== id));
  };

  const handlePdfUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPdfUploading(true);
    const form = new FormData();
    form.append('file', file);
    form.append('title', file.name);
    form.append('mode', 'review');
    try {
      await fetch(`${API}/api/kg/ingest/pdf`, { method: 'POST', body: form });
      setTimeout(refreshPending, 500);
    } catch {}
    setPdfUploading(false);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleApprove = async (id: string) => {
    setPending((prev) => prev.filter((p) => p.id !== id));
    approvePending(id); // fire-and-forget
  };

  const handleReject = async (id: string) => {
    setPending((prev) => prev.filter((p) => p.id !== id));
    rejectPending(id); // fire-and-forget
  };

  const handleResolve = async (id: string, choice: string) => {
    setPending((prev) => prev.filter((p) => p.id !== id));
    resolveConflict(id, choice); // fire-and-forget
  };

  const handleClearQueue = async () => {
    if (!window.confirm('Clear all queued documents? This cannot be undone.')) return;
    setClearing(true);
    await clearAllIncoming();
    setIncoming([]);
    setClearing(false);
  };

  const handleBulkIngest = async () => {
    setBulkIngesting(true);
    setBulkResult(null);
    const result = await bulkIngestNews();
    setBulkResult(result);
    setBulkIngesting(false);
    setTimeout(refreshPending, 800);
  };

  const handleApproveAll = async () => {
    setLoadingPending(true);
    await approveAll();
    await refreshPending();
  };

  const handleClearPending = async () => {
    if (!window.confirm('Discard all pending proposals? This cannot be undone.')) return;
    await clearPending();
    setPending((prev) => prev.filter((p) => p.status !== 'pending'));
  };

  const pendingCount = pending.length;

  // Augment KG node labels with labels from pending node_add proposals so IDs of
  // not-yet-approved nodes resolve to their proposed label instead of showing raw IDs.
  const augmentedNodeLabels = useMemo(() => {
    const m = new Map(nodeLabels);
    for (const item of pending) {
      if (item.type === 'node_add' && item.proposed) {
        const p = item.proposed as Record<string, unknown>;
        if (p.id && p.label) m.set(String(p.id), String(p.label));
      }
    }
    return m;
  }, [nodeLabels, pending]);

  return (
    <div style={{ display: 'flex', height: '100%', background: '#0d1117', color: '#e6edf3', fontFamily: 'inherit', gap: 0 }}>

      {/* ── Left: Incoming Pool ── */}
      <div style={{ width: 340, flexShrink: 0, borderRight: '1px solid #21262d', display: 'flex', flexDirection: 'column' }}>
        <SectionHeader title="Incoming Documents" badge={`${incoming.filter(d => d.status === 'queued').length} queued`} badgeColor="#8b949e">
          <button
            onClick={handleClearQueue}
            disabled={clearing || incoming.length === 0}
            title="Clear all queued documents"
            style={{ background: 'transparent', border: '1px solid #f7816666', color: '#f78166', borderRadius: 4, padding: '2px 8px', fontSize: 11, cursor: 'pointer', opacity: incoming.length === 0 ? 0.4 : 1 }}
          >
            {clearing ? '…' : 'Clear All'}
          </button>
        </SectionHeader>

        {/* Bulk ingest from news cache */}
        <div style={{ padding: '8px 12px', borderBottom: '1px solid #21262d', background: '#0d1117', display: 'flex', alignItems: 'center', gap: 8 }}>
          <button onClick={handleBulkIngest} disabled={bulkIngesting} style={{ ...primaryBtn, fontSize: 11, flex: 1 }}>
            {bulkIngesting ? '⟳ Ingesting news cache…' : '⚡ Bulk Ingest News Cache'}
          </button>
          {bulkResult && (
            <span style={{ fontSize: 10, color: '#8b949e', whiteSpace: 'nowrap' }}>
              <span style={{ color: '#3fb950' }}>{bulkResult.ingested} new</span>
              {bulkResult.skipped > 0 && <span style={{ color: '#484f58' }}> · {bulkResult.skipped} skipped</span>}
            </span>
          )}
        </div>

        {/* Add form */}
        <div style={{ padding: '10px 12px', borderBottom: '1px solid #21262d' }}>
          <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
            {(['url', 'text'] as const).map((m) => (
              <button key={m} onClick={() => setAddMode(m)} style={{
                flex: 1, padding: '4px 0', fontSize: 11, cursor: 'pointer',
                background: addMode === m ? '#1f6feb' : '#21262d',
                border: `1px solid ${addMode === m ? '#388bfd' : '#30363d'}`,
                borderRadius: 4, color: addMode === m ? '#fff' : '#8b949e',
              }}>
                {m === 'url' ? 'URL' : 'Text / Paste'}
              </button>
            ))}
          </div>
          <input
            value={addTitle}
            onChange={(e) => setAddTitle(e.target.value)}
            placeholder="Title (optional)"
            style={inputStyle}
          />
          {addMode === 'url' ? (
            <input
              value={addInput}
              onChange={(e) => setAddInput(e.target.value)}
              placeholder="https://..."
              style={{ ...inputStyle, marginTop: 6 }}
              onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            />
          ) : (
            <textarea
              value={addInput}
              onChange={(e) => setAddInput(e.target.value)}
              placeholder="Paste article text or report content…"
              rows={4}
              style={{ ...inputStyle, marginTop: 6, resize: 'vertical', minHeight: 80 }}
            />
          )}
          <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
            <button onClick={handleAdd} disabled={adding || !addInput.trim()} style={primaryBtn}>
              {adding ? 'Adding…' : '+ Add to Queue'}
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={pdfUploading}
              style={secondaryBtn}
            >
              {pdfUploading ? 'Uploading…' : '↑ PDF'}
            </button>
            <input ref={fileInputRef} type="file" accept=".pdf" style={{ display: 'none' }} onChange={handlePdfUpload} />
          </div>
        </div>

        {/* Document list */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {incoming.length === 0 ? (
            <div style={{ padding: 20, color: '#484f58', fontSize: 12, textAlign: 'center' }}>
              No documents in queue.
            </div>
          ) : incoming.map((doc) => (
            <div key={doc.id} style={{
              padding: '10px 12px', borderBottom: '1px solid #161b22',
              background: doc.status === 'processing' ? '#0d1a26' : 'transparent',
            }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                    <span style={{
                      fontSize: 9, padding: '1px 5px', borderRadius: 3,
                      background: STATUS_COLOR[doc.status] + '22',
                      color: STATUS_COLOR[doc.status],
                      border: `1px solid ${STATUS_COLOR[doc.status]}44`,
                      whiteSpace: 'nowrap',
                    }}>
                      {doc.status === 'processing' ? '⟳ processing' : doc.status}
                    </span>
                    <span style={{ fontSize: 9, color: '#484f58' }}>{doc.type.toUpperCase()}</span>
                  </div>
                  <div style={{
                    fontSize: 12, color: '#e6edf3', lineHeight: 1.4,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {doc.title}
                  </div>
                  <div style={{ fontSize: 10, color: '#484f58', marginTop: 2 }}>{fmtDate(doc.added_at)}</div>
                  {doc.status === 'done' && doc.result && (
                    <>
                      <div style={{ fontSize: 10, color: '#3fb950', marginTop: 3 }}>
                        {(doc.result as any).proposed ?? 0} triplets proposed
                        {(doc.result as any).events_extracted > 0 && ` · ${(doc.result as any).events_extracted} events`}
                      </div>
                      {(doc.result as any).truncated && (
                        <div style={{ fontSize: 10, color: '#d29922', marginTop: 2 }}>
                          ⚠ Input truncated — only first 12k chars sent to LLM (doc was {Math.round((doc.result as any).original_length / 1000)}k chars)
                        </div>
                      )}
                    </>
                  )}
                  {doc.status === 'error' && doc.result && (
                    <div style={{ fontSize: 10, color: '#f78166', marginTop: 3 }}>
                      {String((doc.result as any).error ?? 'Error')}
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flexShrink: 0 }}>
                  {doc.status === 'queued' && (
                    <button
                      onClick={() => handleProcess(doc.id)}
                      disabled={processingId === doc.id}
                      style={{ ...primaryBtn, fontSize: 10, padding: '3px 8px' }}
                    >
                      Process
                    </button>
                  )}
                  {doc.status === 'error' && (
                    <button
                      onClick={() => handleProcess(doc.id)}
                      style={{ ...primaryBtn, fontSize: 10, padding: '3px 8px' }}
                    >
                      Retry
                    </button>
                  )}
                  {doc.status === 'done' && (
                    <button
                      onClick={() => handleProcess(doc.id, true)}
                      disabled={processingId === doc.id}
                      style={{ ...secondaryBtn, fontSize: 10, padding: '3px 8px' }}
                      title="Re-run extraction (bypasses deduplication)"
                    >
                      ↺ Re-run
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(doc.id)}
                    style={{ ...ghostBtn, fontSize: 10, padding: '3px 8px', color: '#f78166' }}
                  >
                    ✕
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Right: Pending Review ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', borderBottom: '1px solid #21262d', background: '#161b22', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: '#e6edf3' }}>Pending Review</span>
            {pendingCount > 0 && (
              <span style={{ background: '#f78166', color: '#0d1117', borderRadius: 10, padding: '1px 7px', fontSize: 10, fontWeight: 600 }}>
                {pendingCount}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {/* Status filter */}
            {['pending', 'approved', 'rejected'].map((s) => (
              <button key={s} onClick={() => setPendingFilter(s)} style={{
                fontSize: 10, padding: '2px 8px', cursor: 'pointer', borderRadius: 4,
                background: pendingFilter === s ? '#21262d' : 'none',
                border: `1px solid ${pendingFilter === s ? '#58a6ff' : '#30363d'}`,
                color: pendingFilter === s ? '#58a6ff' : '#8b949e',
              }}>
                {s}
              </button>
            ))}
            {pendingFilter === 'pending' && pendingCount > 0 && (
              <>
                <button onClick={handleApproveAll} style={{ ...primaryBtn, fontSize: 10, padding: '2px 10px' }}>
                  Approve All
                </button>
                <button onClick={handleClearPending} style={{ background: 'transparent', border: '1px solid #f7816666', color: '#f78166', borderRadius: 4, padding: '2px 10px', fontSize: 10, cursor: 'pointer' }}>
                  Clear All
                </button>
              </>
            )}
            <button onClick={refreshPending} style={{ ...ghostBtn, fontSize: 10 }}>↻</button>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {loadingPending ? (
            <div style={{ padding: 24, textAlign: 'center', color: '#8b949e', fontSize: 12 }}>Loading…</div>
          ) : pending.length === 0 ? (
            <div style={{ padding: 24, textAlign: 'center', color: '#484f58', fontSize: 12 }}>
              {pendingFilter === 'pending' ? 'No items pending review. Process a document to see proposals here.' : `No ${pendingFilter} items.`}
            </div>
          ) : pending.map((item) => (
            <PendingCard
              key={item.id}
              item={item}
              onApprove={() => handleApprove(item.id)}
              onReject={() => handleReject(item.id)}
              onResolve={(choice) => handleResolve(item.id, choice)}
              schemaTree={schemaTree}
              nodeLabels={augmentedNodeLabels}
              onTypeChange={(newType) => {
                updatePendingType(item.id, newType);
                setPending((prev) => prev.map((p) => p.id === item.id && p.proposed
                  ? { ...p, proposed: { ...p.proposed, type: newType } } : p));
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── PendingCard ────────────────────────────────────────────────────────────────

function PendingCard({ item, schemaTree, nodeLabels, onApprove, onReject, onResolve, onTypeChange }: {
  item: PendingItem;
  schemaTree: SchemaNode[];
  nodeLabels: Map<string, string>;
  onApprove: () => void;
  onReject: () => void;
  onResolve: (choice: string) => void;
  onTypeChange: (type: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const typeColor = TYPE_COLOR[item.type] ?? '#8b949e';
  const isConflict = item.type === 'conflict';
  const isMerge = item.type === 'merge';
  const isPending = item.status === 'pending';

  return (
    <div style={{
      borderBottom: '1px solid #161b22',
      padding: '10px 12px',
      background: expanded ? '#0d1117' : 'transparent',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
        <span style={{
          fontSize: 9, padding: '2px 6px', borderRadius: 3, whiteSpace: 'nowrap', flexShrink: 0,
          background: typeColor + '22', color: typeColor, border: `1px solid ${typeColor}44`,
        }}>
          {item.type.replace('_', ' ')}
        </span>

        <div style={{ flex: 1, minWidth: 0 }}>
          <SummaryLine item={item} schemaTree={schemaTree} nodeLabels={nodeLabels} onTypeChange={onTypeChange} />
          <div style={{ fontSize: 10, color: '#484f58', marginTop: 2 }}>{fmtDate(item.created_at)}</div>
        </div>

        <div style={{ display: 'flex', gap: 4, flexShrink: 0, alignItems: 'center' }}>
          <button onClick={() => setExpanded(!expanded)} style={{ ...ghostBtn, fontSize: 10 }}>
            {expanded ? '▲' : '▼'}
          </button>
          {isPending && !isConflict && !isMerge && (
            <>
              <button onClick={onApprove} style={{ ...approveBtn }}>✓</button>
              <button onClick={onReject} style={{ ...rejectBtn }}>✕</button>
            </>
          )}
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div style={{ marginTop: 10 }}>
          {/* Evidence excerpt */}
          {item.evidence?.excerpt && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 3 }}>SOURCE EXCERPT</div>
              <div style={{
                fontSize: 11, color: '#c9d1d9', lineHeight: 1.5,
                background: '#161b22', borderRadius: 4, padding: '6px 8px',
                borderLeft: '2px solid #30363d', fontStyle: 'italic',
              }}>
                "{item.evidence.excerpt}"
              </div>
              {item.evidence.source && (
                <div style={{ fontSize: 10, color: '#484f58', marginTop: 3 }}>
                  {String((item.evidence.source as any).title ?? '')}
                  {(item.evidence.source as any).date ? ` · ${String((item.evidence.source as any).date).slice(0, 10)}` : ''}
                </div>
              )}
            </div>
          )}

          {/* Node attributes */}
          {item.type === 'node_add' && item.proposed?.attributes && (
            <AttributeTable attrs={item.proposed.attributes as Record<string, {value: unknown}>} />
          )}

          {/* Conflict resolution */}
          {isConflict && item.conflict && (
            <ConflictBlock itemId={item.id} conflict={item.conflict} nodeLabels={nodeLabels} isPending={isPending} onResolve={onResolve} />
          )}

          {/* Merge block */}
          {isMerge && item.merge && (
            <MergeBlock merge={item.merge} isPending={isPending} onResolve={onResolve} />
          )}

          {/* LLM assessment */}
          {item.llm_assessment && (
            <div style={{ marginTop: 6, fontSize: 11, color: '#8b949e', background: '#161b22', borderRadius: 4, padding: '6px 8px' }}>
              🤖 {item.llm_assessment}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Flattens schema tree into a list of { type, depth, selectable } for rendering. */
function flattenSchemaTree(nodes: SchemaNode[], depth = 0): { type: string; depth: number; selectable: boolean }[] {
  const result: { type: string; depth: number; selectable: boolean }[] = [];
  for (const node of nodes) {
    result.push({ type: node.type, depth, selectable: node.children.length === 0 });
    if (node.children.length > 0) {
      result.push(...flattenSchemaTree(node.children, depth + 1));
    }
  }
  return result;
}

function SummaryLine({ item, schemaTree, nodeLabels, onTypeChange }: {
  item: PendingItem;
  schemaTree: SchemaNode[];
  nodeLabels: Map<string, string>;
  onTypeChange: (type: string) => void;
}) {
  const proposed = item.proposed as Record<string, unknown> | undefined;
  const allTypes = flattenSchemaTree(schemaTree).map((e) => e.type);
  const label = (id: string) => nodeLabels.get(id) ?? id;

  switch (item.type) {
    case 'node_add':
      return <div style={{ fontSize: 12, color: '#e6edf3', display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <span style={{ color: '#3fb950' }}>{String(proposed?.label ?? '')}</span>
        <span style={{ color: '#484f58' }}>·</span>
        {schemaTree.length > 0 ? (() => {
          const flat = flattenSchemaTree(schemaTree);
          return (
            <select
              value={String(proposed?.type ?? '')}
              onChange={(e) => onTypeChange(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              style={{
                background: '#0d1117', border: '1px solid #30363d', borderRadius: 4,
                color: '#bc8cff', fontSize: 11, padding: '1px 4px', cursor: 'pointer',
                outline: 'none',
              }}
            >
              {!allTypes.includes(String(proposed?.type ?? '')) && (
                <option value={String(proposed?.type ?? '')}>{String(proposed?.type ?? '')} (proposed)</option>
              )}
              {flat.map(({ type, depth, selectable }) => {
                const indent = '\u00a0\u00a0\u00a0\u00a0'.repeat(depth);
                return selectable
                  ? <option key={type} value={type}>{indent + type}</option>
                  : <option key={type} value={type} disabled style={{ color: '#484f58', fontWeight: 600 }}>{indent + '— ' + type}</option>;
              })}
            </select>
          );
        })() : (
          <span style={{ color: '#bc8cff' }}>{String(proposed?.type ?? '')}</span>
        )}
      </div>;
    case 'edge_add': {
      const src = String(proposed?.source ?? '');
      const tgt = String(proposed?.target ?? '');
      return <div style={{ fontSize: 12, color: '#e6edf3' }}>
        <span style={{ color: '#8b949e' }}>{label(src)} </span>
        <span style={{ color: '#58a6ff' }}>—[{String(proposed?.label ?? '')}]→ </span>
        <span style={{ color: '#8b949e' }}>{label(tgt)}</span>
      </div>;
    }
    case 'attribute_update': {
      const eid = item.entity_id ?? '';
      return <div style={{ fontSize: 12, color: '#e6edf3' }}>
        <span style={{ color: '#8b949e' }}>{label(eid)} · </span>
        <span style={{ color: '#e3b341' }}>{item.field}</span>
        <span style={{ color: '#8b949e' }}> {String(item.old_value ?? '?')} → {String(item.new_value ?? '?')}</span>
      </div>;
    }
    case 'conflict':
      return <div style={{ fontSize: 12, color: '#f78166' }}>Conflict detected — review required</div>;
    case 'merge':
      return <div style={{ fontSize: 12, color: '#bc8cff' }}>Possible duplicate entities — review required</div>;
    default:
      return <div style={{ fontSize: 12, color: '#8b949e' }}>{item.type}</div>;
  }
}

function AttributeTable({ attrs }: { attrs: Record<string, { value: unknown } | unknown> }) {
  const entries = Object.entries(attrs).filter(([, v]) => {
    const val = (v as any)?.value ?? v;
    return val !== null && val !== undefined;
  });
  if (!entries.length) return null;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 4 }}>ATTRIBUTES</div>
      <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '2px 8px' }}>
        {entries.map(([key, v]) => {
          const val = (v as any)?.value ?? v;
          return (
            <>
              <span key={key + 'k'} style={{ fontSize: 11, color: '#8b949e' }}>{key}</span>
              <span key={key + 'v'} style={{ fontSize: 11, color: '#e6edf3', wordBreak: 'break-word' }}>{String(val)}</span>
            </>
          );
        })}
      </div>
    </div>
  );
}

function ConflictBlock({ itemId, conflict, nodeLabels, isPending, onResolve }: {
  itemId: string;
  conflict: Record<string, unknown>;
  nodeLabels: Map<string, string>;
  isPending: boolean;
  onResolve: (choice: string) => void;
}) {
  const optA = conflict.option_a as Record<string, unknown> | undefined;
  const optB = conflict.option_b as Record<string, unknown> | undefined;
  const assessment = conflict.llm_assessment as string | undefined;
  const field = conflict.field as string | undefined;
  const entityId = conflict.entity_id as string | undefined;
  const entityLabel = entityId ? (nodeLabels.get(entityId) ?? entityId) : undefined;

  // Edge conflict — resolve entity label from edge source
  const edgeA = optA?.edge as Record<string, unknown> | undefined;
  const edgeSrcLabel = edgeA ? (nodeLabels.get(String(edgeA.source ?? '')) ?? String(edgeA.source ?? '')) : undefined;
  const edgeTgtLabelA = edgeA ? (nodeLabels.get(String(edgeA.target ?? '')) ?? String(edgeA.target ?? '')) : undefined;
  const edgeB = optB?.edge as Record<string, unknown> | undefined;
  const edgeTgtLabelB = edgeB ? (nodeLabels.get(String(edgeB.target ?? '')) ?? String(edgeB.target ?? '')) : undefined;

  const [instruction, setInstruction] = useState('');
  const [asking, setAsking] = useState(false);
  const [aiSuggestion, setAiSuggestion] = useState<{ choice: string; reasoning: string } | null>(null);

  const askAI = async () => {
    if (!instruction.trim()) return;
    setAsking(true);
    setAiSuggestion(null);
    try {
      const r = await fetch(`${API}/api/kg/pending/${itemId}/ai_resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instruction: instruction.trim() }),
      });
      if (r.ok) setAiSuggestion(await r.json());
    } finally { setAsking(false); }
  };

  const choiceLabel: Record<string, string> = { option_a: 'Option A', option_b: 'Option B', keep_both: 'Keep Both' };

  return (
    <div>
      {/* Entity / relationship being conflicted */}
      {entityLabel && field && (
        <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 6 }}>
          ENTITY: <span style={{ color: '#e6edf3' }}>{entityLabel}</span>
          <span style={{ color: '#484f58' }}> · </span>
          FIELD: <span style={{ color: '#e3b341' }}>{field}</span>
        </div>
      )}
      {edgeSrcLabel && !field && (
        <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 6 }}>
          RELATIONSHIP ON: <span style={{ color: '#e6edf3' }}>{edgeSrcLabel}</span>
          <span style={{ color: '#484f58' }}> —[{String(edgeA?.label ?? '')}]→ </span>
          <span style={{ color: '#e6edf3' }}>{edgeTgtLabelA}</span>
          {edgeTgtLabelB && edgeTgtLabelB !== edgeTgtLabelA && (
            <span style={{ color: '#484f58' }}> vs <span style={{ color: '#e6edf3' }}>{edgeTgtLabelB}</span></span>
          )}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
        {[['option_a', optA], ['option_b', optB]].map(([key, opt]) => {
          const o = opt as Record<string, unknown> | undefined;
          const isAISuggested = aiSuggestion?.choice === key;
          return (
            <div key={String(key)} style={{
              background: isAISuggested ? '#1a2a1a' : '#161b22', borderRadius: 4, padding: '8px 10px',
              border: `1px solid ${isAISuggested ? '#3fb950' : '#30363d'}`,
            }}>
              <div style={{ fontSize: 10, color: isAISuggested ? '#3fb950' : '#8b949e', marginBottom: 4 }}>
                {key === 'option_a' ? 'Option A' : 'Option B'}{isAISuggested ? ' ← AI suggests' : ''}
              </div>
              {o?.value !== undefined && <div style={{ fontSize: 12, color: '#e6edf3', marginBottom: 4 }}>{String(o.value)}</div>}
              {o?.edge && <div style={{ fontSize: 11, color: '#58a6ff' }}>
                {nodeLabels.get(String((o.edge as any).source ?? '')) ?? String((o.edge as any).source ?? '')}
                {' →[' + String((o.edge as any).label ?? '') + ']→ '}
                {nodeLabels.get(String((o.edge as any).target ?? '')) ?? String((o.edge as any).target ?? '')}
              </div>}
              {o?.excerpt && <div style={{ fontSize: 10, color: '#8b949e', fontStyle: 'italic', marginTop: 4 }}>"{String(o.excerpt)}"</div>}
              {(o?.source as Record<string, unknown>)?.title && (
                <div style={{ fontSize: 10, color: '#484f58', marginTop: 3 }}>{String((o.source as any).title)}</div>
              )}
            </div>
          );
        })}
      </div>

      {assessment && <div style={{ fontSize: 11, color: '#8b949e', background: '#161b22', borderRadius: 4, padding: '6px 8px', marginBottom: 8 }}>🤖 {assessment}</div>}

      {/* AI suggestion result */}
      {aiSuggestion && (
        <div style={{ background: '#0d1a0d', border: '1px solid #3fb950', borderRadius: 4, padding: '8px 10px', marginBottom: 8 }}>
          <div style={{ fontSize: 10, color: '#3fb950', marginBottom: 4 }}>
            🤖 AI suggests: <strong>{choiceLabel[aiSuggestion.choice] ?? aiSuggestion.choice}</strong>
          </div>
          <div style={{ fontSize: 11, color: '#8b949e', lineHeight: 1.5 }}>{aiSuggestion.reasoning}</div>
        </div>
      )}

      {isPending && (
        <>
          {/* AI instruction input */}
          <div style={{ marginBottom: 8 }}>
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && askAI()}
                placeholder="Tell AI how to resolve… e.g. use the more recent source"
                style={{ ...inputStyle, flex: 1, fontSize: 11 }}
              />
              <button onClick={askAI} disabled={asking || !instruction.trim()} style={{
                ...secondaryBtn, fontSize: 11, padding: '4px 10px',
                color: asking ? '#484f58' : '#e3b341', borderColor: asking ? '#30363d' : '#e3b34144',
              }}>
                {asking ? '…' : '🤖 Ask'}
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={() => onResolve('option_a')} style={{ ...approveBtn, fontSize: 11 }}>Use A</button>
            <button onClick={() => onResolve('option_b')} style={{ ...approveBtn, fontSize: 11, background: '#1f6feb22', borderColor: '#388bfd' }}>Use B</button>
            <button onClick={() => onResolve('keep_both')} style={{ ...secondaryBtn, fontSize: 11 }}>Keep Both</button>
            {aiSuggestion && aiSuggestion.choice !== 'keep_both' && (
              <button
                onClick={() => onResolve(aiSuggestion.choice)}
                style={{ ...approveBtn, fontSize: 11, background: '#1a3a2a', borderColor: '#3fb950' }}
              >Apply AI ({choiceLabel[aiSuggestion.choice]})</button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function MergeBlock({ merge, isPending, onResolve }: {
  merge: Record<string, unknown>;
  isPending: boolean;
  onResolve: (choice: string) => void;
}) {
  const nodeA = merge.node_a as Record<string, unknown> | undefined;
  const nodeB = merge.node_b as Record<string, unknown> | undefined;
  const similarity = merge.similarity as number | undefined;

  const NodeCard = ({ node, tag }: { node: Record<string, unknown>; tag: string }) => (
    <div style={{ flex: 1, background: '#161b22', borderRadius: 4, padding: '8px 10px', border: '1px solid #30363d' }}>
      <div style={{ fontSize: 12, color: '#e6edf3', fontWeight: 600, marginBottom: 2 }}>
        {node.label as string ?? node.id as string}
      </div>
      <div style={{ fontSize: 10, color: '#8b949e' }}>
        {node.type as string ?? ''}
        <span style={{ marginLeft: 6, color: '#484f58' }}>{tag}</span>
      </div>
    </div>
  );

  return (
    <div>
      <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
        POTENTIAL DUPLICATE
        {similarity !== undefined && similarity > 0 && (
          <span style={{ color: '#bc8cff' }}>{(similarity * 100).toFixed(0)}% similar</span>
        )}
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        {nodeA && <NodeCard node={nodeA} tag="existing" />}
        <span style={{ color: '#8b949e', fontSize: 14, flexShrink: 0 }}>≡?</span>
        {nodeB && <NodeCard node={nodeB} tag="new" />}
      </div>
      {merge.reason && <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 8 }}>🤖 {String(merge.reason)}</div>}
      {isPending && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button onClick={() => onResolve('option_a')} style={approveBtn}>Use A (existing)</button>
          <button onClick={() => onResolve('option_b')} style={{ ...approveBtn, background: '#1f6feb22', borderColor: '#388bfd' }}>Use B (new)</button>
          <button onClick={() => onResolve('keep_both')} style={secondaryBtn}>Different entities</button>
        </div>
      )}
    </div>
  );
}

function SectionHeader({ title, badge, badgeColor, children }: { title: string; badge: string; badgeColor: string; children?: React.ReactNode }) {
  return (
    <div style={{ padding: '8px 12px', borderBottom: '1px solid #21262d', background: '#161b22', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
      <span style={{ fontSize: 12, fontWeight: 600, color: '#e6edf3' }}>{title}</span>
      <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 10, background: badgeColor + '22', color: badgeColor, border: `1px solid ${badgeColor}44` }}>
        {badge}
      </span>
      {children && <div style={{ marginLeft: 'auto' }}>{children}</div>}
    </div>
  );
}

// ── Shared styles ─────────────────────────────────────────────────────────────

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
  color: '#8b949e', cursor: 'pointer', fontSize: 12, padding: '5px 10px',
};

const ghostBtn: React.CSSProperties = {
  background: 'none', border: '1px solid #30363d', borderRadius: 4,
  color: '#8b949e', cursor: 'pointer', fontSize: 12, padding: '3px 8px',
};

const approveBtn: React.CSSProperties = {
  background: '#1a3a1a', border: '1px solid #3fb950', borderRadius: 4,
  color: '#3fb950', cursor: 'pointer', fontSize: 12, padding: '4px 10px',
};

const rejectBtn: React.CSSProperties = {
  background: '#3a1a1a', border: '1px solid #f78166', borderRadius: 4,
  color: '#f78166', cursor: 'pointer', fontSize: 12, padding: '4px 10px',
};
