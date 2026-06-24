import { useEffect, useState, useRef } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import type Cytoscape from 'cytoscape';
import { getFullKG } from '../../api/client';
import type { KGNode, KGEdge, KGAttrValue, ArticleSource } from '../../data/mockData';
import { useAppStore } from '../../store/appStore';

const API = 'http://localhost:8000';

const NODE_COLORS: Record<string, string> = {
  satellite: '#58a6ff',
  company: '#3fb950',
  report: '#f78166',
  mission: '#bc8cff',
  Satellite: '#58a6ff',
  CivilSatellite: '#58a6ff',
  MilitarySatellite: '#f0a500',
  CommercialSatellite: '#79c0ff',
  SatelliteConstellation: '#a5d6ff',
  SatelliteSeries: '#79c0ff',
  Organization: '#3fb950',
  SpaceAgency: '#3fb950',
  Company: '#3fb950',
  MilitaryUnit: '#e8163c',
  LaunchVehicle: '#ff7b72',
  Mission: '#bc8cff',
  CargoMission: '#bc8cff',
  CrewMission: '#d2a8ff',
  ScienceMission: '#a5d6ff',
  Document: '#f78166',
  JCOReport: '#f78166',
  NewsArticle: '#f78166',
  Person: '#e3b341',
  Astronaut: '#e3b341',
  Official: '#e3b341',
  Country: '#e6924a',
};

function nodeColor(type: string, inferred_types?: string[]): string {
  if (NODE_COLORS[type]) return NODE_COLORS[type];
  for (const ancestor of (inferred_types ?? [])) {
    if (NODE_COLORS[ancestor]) return NODE_COLORS[ancestor];
  }
  return '#6e7681';
}

function buildLegendEntries(nodes: KGNode[]): { type: string; color: string }[] {
  const seen = new Map<string, string>();
  for (const n of nodes) {
    const color = nodeColor(n.type, n.inferred_types);
    if (!seen.has(n.type)) seen.set(n.type, color);
  }
  return Array.from(seen.entries()).map(([type, color]) => ({ type, color }));
}

interface EdgeTooltip { x: number; y: number; article: ArticleSource; label: string; }

type PanelItem =
  | { kind: 'node'; data: KGNode }
  | { kind: 'edge'; data: KGEdge; sourceLabel: string; targetLabel: string };

function buildElements(
  nodes: KGNode[], edges: KGEdge[],
  colorHighlightIds: Set<string>, dimHighlightIds: Set<string>,
  highlightEdgeIds: Set<string>, selectedId: string | null
) {
  const els: Cytoscape.ElementDefinition[] = [];
  nodes.forEach((n) => {
    const isHighlighted = colorHighlightIds.size > 0 && colorHighlightIds.has(n.id);
    const dimmed = dimHighlightIds.size > 0 && !dimHighlightIds.has(n.id);
    const rawNorad = (n.attributes?.norad_id as KGAttrValue | undefined)?.value
      ?? (n.attributes?.norad_id as unknown);
    const noradId = rawNorad != null && rawNorad !== '' ? String(rawNorad) : null;
    const validNorad = noradId && /^\d+$/.test(noradId) ? noradId : null;
    els.push({
      data: { id: n.id, label: n.label, type: n.type, inferred_types: n.inferred_types ?? [], norad_id: validNorad },
      style: {
        'background-color': isHighlighted ? '#f78166' : nodeColor(n.type, n.inferred_types),
        opacity: dimmed ? 0.3 : 1,
        'border-width': n.id === selectedId ? 3 : 0,
        'border-color': '#ffffff',
      },
    });
  });
  const nodeIds = new Set(nodes.map((n) => n.id));
  edges.forEach((e) => {
    if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) return;
    const dimmed = highlightEdgeIds.size > 0 && !highlightEdgeIds.has(e.id);
    const hasSources = (e.sources?.length ?? 0) > 0;
    els.push({
      data: { id: e.id, source: e.source, target: e.target, label: e.label },
      style: {
        'line-color': highlightEdgeIds.has(e.id) ? '#f78166' : (hasSources ? '#6e7681' : '#444c56'),
        opacity: dimmed ? 0.2 : 0.8,
        width: highlightEdgeIds.has(e.id) ? 3 : (hasSources ? 2 : 1.5),
        'line-style': hasSources ? 'solid' : 'dashed',
      },
    });
  });
  return els;
}

export default function KGView() {
  const [nodes, setNodes] = useState<KGNode[]>([]);
  const [edges, setEdges] = useState<KGEdge[]>([]);
  const [tooltip, setTooltip] = useState<EdgeTooltip | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [panelItem, setPanelItem] = useState<PanelItem | null>(null);
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());
  const [hopFilterNodeId, setHopFilterNodeId] = useState<string | null>(null);
  const legendEntries = buildLegendEntries(nodes);
  const cyRef = useRef<Cytoscape.Core | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const { selectedSatelliteId, activeReasoningSubgraphIds, selectSatellite } = useAppStore();

  const loadKG = () => {
    setRefreshing(true);
    getFullKG().then(({ nodes, edges }) => { setNodes(nodes); setEdges(edges); setRefreshing(false); });
  };

  useEffect(() => { loadKG(); }, []);

  useEffect(() => {
    if (cyRef.current && selectedSatelliteId) {
      const el = cyRef.current.$(`#${selectedSatelliteId}`);
      if (el.length) cyRef.current.animate({ fit: { eles: el, padding: 80 }, duration: 400 });
    }
  }, [selectedSatelliteId]);

  // Apply display:none/element to nodes based on typeFilter and hopFilter whenever either changes.
  // This preserves positions — nodes stay where they were laid out.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const hopNodeIds = hopFilterNodeId ? getHopFilterNodeIds(hopFilterNodeId) : null;

    cy.batch(() => {
      cy.nodes().forEach(n => {
        const nodeId = n.id();
        const t = n.data('type') as string;
        const inferred = (n.data('inferred_types') as string[]) ?? [];

        // Check type filter
        const typeHidden = typeFilter.size > 0 && !typeFilter.has(t) && !inferred.some(i => typeFilter.has(i));

        // Check hop filter
        const hopHidden = hopNodeIds && !hopNodeIds.has(nodeId);

        const hidden = typeHidden || hopHidden;
        n.style('display', hidden ? 'none' : 'element');
      });
      cy.edges().forEach(e => {
        const srcHidden = e.source().style('display') === 'none';
        const tgtHidden = e.target().style('display') === 'none';
        e.style('display', srcHidden || tgtHidden ? 'none' : 'element');
      });
    });
  }, [typeFilter, hopFilterNodeId]);

  const nodeById = (id: string) => nodes.find((n) => n.id === id);
  const edgeById = (id: string) => edges.find((e) => e.id === id);

  // Calculate 1-hop neighbors (including the center node)
  const getHopFilterNodeIds = (centerId: string): Set<string> => {
    const result = new Set<string>([centerId]);
    // Find all edges connected to center node
    edges.forEach(e => {
      if (e.source === centerId) result.add(e.target);
      if (e.target === centerId) result.add(e.source);
    });
    return result;
  };

  // Hidden node IDs: matches type filter exclusion (nodes NOT in the selected types)
  let hiddenNodeIds = typeFilter.size > 0
    ? new Set(nodes.filter(n => !typeFilter.has(n.type) && !(n.inferred_types ?? []).some(t => typeFilter.has(t))).map(n => n.id))
    : new Set<string>();

  // Apply 1-hop filter if active
  if (hopFilterNodeId) {
    const hopNodeIds = getHopFilterNodeIds(hopFilterNodeId);
    const hopHidden = new Set(nodes.filter(n => !hopNodeIds.has(n.id)).map(n => n.id));
    hiddenNodeIds = new Set([...hiddenNodeIds, ...hopHidden]);
  }

  // Visible node count for the counter badge
  const visibleNodes = nodes.filter(n => !hiddenNodeIds.has(n.id));

  // Reasoning subgraph dims non-highlighted nodes (separate from type filter)
  const dimHighlightIds = activeReasoningSubgraphIds;

  // Always pass ALL nodes/edges — use display:none via style to preserve positions
  const elements = buildElements(nodes, edges, activeReasoningSubgraphIds, dimHighlightIds, new Set(), selectedSatelliteId);

  const stylesheet: Cytoscape.StylesheetCSS[] = [
    {
      selector: 'node',
      css: {
        label: 'data(label)', 'font-size': 11, color: '#e6edf3',
        'text-valign': 'bottom', 'text-margin-y': 4, width: 28, height: 28,
        'text-outline-color': '#0d1117', 'text-outline-width': 2,
      },
    },
    {
      selector: 'edge',
      css: {
        label: 'data(label)', 'font-size': 9, color: '#8b949e',
        'curve-style': 'bezier', 'target-arrow-shape': 'triangle',
        'target-arrow-color': '#444c56', 'arrow-scale': 0.8,
        'text-outline-color': '#0d1117', 'text-outline-width': 1,
      },
    },
  ];

  const panelWidth = panelItem ? 300 : 0;

  return (
    <div ref={containerRef} style={{ height: '100%', background: '#0d1117', position: 'relative', display: 'flex' }}>
      {/* Graph canvas */}
      <div style={{ flex: 1, position: 'relative', minWidth: 0 }}>
        <div style={{
          position: 'absolute', top: 8, left: 8, zIndex: 10,
          display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center',
        }}>
          <button
            onClick={loadKG} disabled={refreshing}
            style={{
              background: '#161b22', border: '1px solid #30363d', borderRadius: 4,
              color: refreshing ? '#484f58' : '#8b949e', cursor: refreshing ? 'default' : 'pointer',
              fontSize: 11, padding: '2px 8px',
            }}
          >
            {refreshing ? '⟳ Refreshing…' : '↻ Refresh'}
          </button>
          {legendEntries.map(({ type, color }) => {
            const active = typeFilter.has(type);
            return (
              <button
                key={type}
                onClick={() => {
                  setTypeFilter(prev => {
                    const next = new Set(prev);
                    active ? next.delete(type) : next.add(type);
                    return next;
                  });
                }}
                style={{
                  background: active ? color + '22' : '#161b22',
                  border: `1px solid ${active ? color : color + '44'}`,
                  borderRadius: 4, padding: '2px 8px', fontSize: 11, color: active ? color : color + 'aa',
                  cursor: 'pointer', fontFamily: 'inherit',
                  fontWeight: active ? 600 : 400,
                }}
              >
                {type}
              </button>
            );
          })}
          {(typeFilter.size > 0 || hopFilterNodeId) && (
            <>
              <span style={{ fontSize: 10, color: '#484f58', padding: '2px 4px' }}>
                {visibleNodes.length} / {nodes.length} nodes
              </span>
              <button
                onClick={() => { setTypeFilter(new Set()); setHopFilterNodeId(null); }}
                style={{
                  background: 'none', border: '1px solid #30363d', borderRadius: 4,
                  padding: '2px 8px', fontSize: 11, color: '#8b949e',
                  cursor: 'pointer', fontFamily: 'inherit',
                }}
              >
                ✕ show all
              </button>
            </>
          )}
          {activeReasoningSubgraphIds.size > 0 && (
            <span style={{
              background: '#f78166', color: '#0d1117',
              borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600,
            }}>
              Reasoning subgraph highlighted
            </span>
          )}
        </div>

        {nodes.length > 0 && (
          <CytoscapeComponent
            elements={elements}
            style={{ width: '100%', height: '100%' }}
            stylesheet={stylesheet}
            layout={{ name: 'cose', animate: false, padding: 40 }}
            cy={(cy) => {
              cyRef.current = cy;
              cy.on('tap', 'node', (e) => {
                const nodeId: string = e.target.id();
                const nodeType: string = e.target.data('type') ?? '';
                const inferred: string[] = e.target.data('inferred_types') ?? [];
                const isSatellite = nodeType === 'satellite' ||
                  nodeType.toLowerCase().includes('satellite') ||
                  inferred.includes('Satellite');
                const noradId: string | null = e.target.data('norad_id') ?? null;
                if (isSatellite && noradId && /^\d+$/.test(noradId)) {
                  selectSatellite(noradId);
                }
                const full = nodeById(nodeId);
                if (full) setPanelItem({ kind: 'node', data: full });

                // Activate 1-hop filter
                setHopFilterNodeId(nodeId);
              });
              cy.on('tap', 'edge', (e) => {
                const edgeId: string = e.target.id();
                const full = edgeById(edgeId);
                if (full) {
                  const srcLabel = nodeById(full.source)?.label ?? full.source;
                  const tgtLabel = nodeById(full.target)?.label ?? full.target;
                  setPanelItem({ kind: 'edge', data: full, sourceLabel: srcLabel, targetLabel: tgtLabel });
                }
              });
              cy.on('tap', (e) => { if (e.target === cy) setPanelItem(null); });
              cy.on('mouseover', 'edge', (e) => {
                const article = e.target.data('article') as ArticleSource | null;
                if (!article) return;
                const rp = e.renderedPosition ?? e.position;
                const rect = containerRef.current?.getBoundingClientRect();
                setTooltip({ x: rp.x + (rect?.left ?? 0), y: rp.y + (rect?.top ?? 0), article, label: e.target.data('label') as string });
              });
              cy.on('mouseout', 'edge', () => setTooltip(null));
            }}
          />
        )}

        {tooltip && (
          <div style={{
            position: 'fixed', left: tooltip.x + 12, top: tooltip.y - 10, zIndex: 100,
            background: '#161b22', border: '1px solid #30363d', borderRadius: 6,
            padding: '8px 10px', maxWidth: 280, pointerEvents: 'none',
          }}>
            <div style={{ color: '#e3b341', fontSize: 10, fontWeight: 600, marginBottom: 4 }}>
              SOURCE · {tooltip.label}
            </div>
            <div style={{ color: '#e6edf3', fontSize: 12, marginBottom: 4, lineHeight: 1.4 }}>{tooltip.article.title}</div>
            <div style={{ color: '#8b949e', fontSize: 11 }}>
              {tooltip.article.news_site} · {tooltip.article.published_at.slice(0, 10)}
            </div>
          </div>
        )}
      </div>

      {/* Info panel */}
      {panelItem && (
        <KGInfoPanel
          item={panelItem}
          width={panelWidth}
          allNodes={nodes}
          onClose={() => setPanelItem(null)}
          onDeleted={() => { setPanelItem(null); loadKG(); }}
          onEdgeLabelSaved={(newId, newLabel) => {
            setPanelItem((prev) => {
              if (!prev || prev.kind !== 'edge') return prev;
              return { ...prev, data: { ...prev.data, id: newId, label: newLabel } };
            });
            loadKG();
          }}
        />
      )}
    </div>
  );
}

// ── Info Panel ────────────────────────────────────────────────────────────────

function KGInfoPanel({ item, width, allNodes, onClose, onDeleted, onEdgeLabelSaved }: {
  item: PanelItem;
  width: number;
  allNodes: KGNode[];
  onClose: () => void;
  onDeleted: () => void;
  onEdgeLabelSaved: (newId: string, newLabel: string) => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [edgeEditing, setEdgeEditing] = useState(false);
  const [edgeLabelDraft, setEdgeLabelDraft] = useState('');
  const [edgeSaving, setEdgeSaving] = useState(false);

  // Merge state
  const [mergeMode, setMergeMode] = useState(false);
  const [mergeQuery, setMergeQuery] = useState('');
  const [mergeTarget, setMergeTarget] = useState<KGNode | null>(null);
  const [mergeCanonical, setMergeCanonical] = useState<'this' | 'other'>('this');
  const [conflictChoices, setConflictChoices] = useState<Record<string, 'this' | 'other'>>({});
  const [merging, setMerging] = useState(false);

  // Reset state on item change
  useEffect(() => {
    setConfirmDelete(false);
    setEdgeEditing(false);
    setMergeMode(false);
    setMergeQuery('');
    setMergeTarget(null);
    setMergeCanonical('this');
    setConflictChoices({});
    if (item.kind === 'edge') setEdgeLabelDraft(item.data.label);
  }, [item.kind === 'node' ? item.data.id : item.data.id]);

  const deleteItem = async () => {
    setDeleting(true);
    try {
      const path = item.kind === 'node'
        ? `${API}/api/kg/nodes/${encodeURIComponent(item.data.id)}`
        : `${API}/api/kg/edges/${encodeURIComponent(item.data.id)}`;
      const r = await fetch(path, { method: 'DELETE' });
      if (r.ok) onDeleted();
    } finally { setDeleting(false); }
  };

  const saveEdgeLabel = async () => {
    if (item.kind !== 'edge') return;
    setEdgeSaving(true);
    try {
      const r = await fetch(`${API}/api/kg/edges/${encodeURIComponent(item.data.id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: edgeLabelDraft }),
      });
      if (r.ok) {
        const d = await r.json();
        onEdgeLabelSaved(d.id, d.label);
        setEdgeEditing(false);
      }
    } finally { setEdgeSaving(false); }
  };

  return (
    <div style={{
      width, flexShrink: 0, borderLeft: '1px solid #30363d', background: '#161b22',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 12px', borderBottom: '1px solid #30363d',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0,
      }}>
        <span style={{ color: '#8b949e', fontSize: 11, fontWeight: 600 }}>
          {item.kind === 'node' ? 'NODE' : 'EDGE'}
        </span>
        <button onClick={onClose}
          style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 16, lineHeight: 1 }}>
          ×
        </button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px' }}>
        {item.kind === 'node' ? (
          <NodeInfo node={item.data} />
        ) : (
          <EdgeInfo
            edge={item.data}
            sourceLabel={item.sourceLabel}
            targetLabel={item.targetLabel}
            editing={edgeEditing}
            labelDraft={edgeLabelDraft}
            saving={edgeSaving}
            onDraftChange={setEdgeLabelDraft}
            onEditStart={() => { setEdgeLabelDraft(item.data.label); setEdgeEditing(true); }}
            onEditCancel={() => setEdgeEditing(false)}
            onEditSave={saveEdgeLabel}
          />
        )}

        {/* Merge (node only) */}
        {item.kind === 'node' && (() => {
          const thisNode = item.data;
          const thisAttrs = thisNode.attributes ?? {};
          const otherAttrs = mergeTarget?.attributes ?? {};

          // Compute conflicts and auto-fills when a target is selected
          const conflicts: { key: string; thisVal: unknown; otherVal: unknown }[] = [];
          const fills: string[] = [];
          if (mergeTarget) {
            const allKeys = new Set([...Object.keys(thisAttrs), ...Object.keys(otherAttrs)]);
            allKeys.delete('aliases');
            for (const key of allKeys) {
              const aRaw = thisAttrs[key] as KGAttrValue | undefined;
              const bRaw = otherAttrs[key] as KGAttrValue | undefined;
              const aVal = aRaw?.value !== undefined ? aRaw.value : aRaw;
              const bVal = bRaw?.value !== undefined ? bRaw.value : bRaw;
              if (aVal != null && bVal != null && String(aVal) !== String(bVal)) {
                conflicts.push({ key, thisVal: aVal, otherVal: bVal });
              } else if ((aVal == null || aVal === '') && bVal != null && bVal !== '') {
                fills.push(key);
              }
            }
          }

          const doMerge = async () => {
            if (!mergeTarget) return;
            setMerging(true);
            const canonicalId = mergeCanonical === 'this' ? thisNode.id : mergeTarget.id;
            const overrides: Record<string, unknown> = {};
            for (const c of conflicts) {
              const choice = conflictChoices[c.key] ?? 'this';
              // If user chose the non-canonical node's value, pass it as override
              const choseOther = (choice === 'other');
              const canonicalIsThis = mergeCanonical === 'this';
              if (choseOther === canonicalIsThis) {
                // chosen value is from the duplicate — pass as override
                overrides[c.key] = canonicalIsThis ? c.otherVal : c.thisVal;
              }
            }
            try {
              const r = await fetch(
                `${API}/api/kg/nodes/${encodeURIComponent(thisNode.id)}/merge/${encodeURIComponent(mergeTarget.id)}`,
                {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ canonical: canonicalId, overrides }),
                }
              );
              if (r.ok) onDeleted();
            } finally { setMerging(false); }
          };

          const filtered = mergeMode && mergeQuery.trim()
            ? allNodes.filter(n => n.id !== thisNode.id && n.label.toLowerCase().includes(mergeQuery.toLowerCase())).slice(0, 8)
            : [];

          return (
            <div style={{ marginTop: 16, borderTop: '1px solid #21262d', paddingTop: 12 }}>
              {!mergeMode ? (
                <button onClick={() => setMergeMode(true)} style={{
                  width: '100%', background: 'none', border: '1px solid #30363d', borderRadius: 4,
                  color: '#8b949e', fontSize: 11, cursor: 'pointer', padding: '4px 0',
                }}>
                  Merge with…
                </button>
              ) : (
                <div>
                  <div style={{ color: '#8b949e', fontSize: 10, fontWeight: 600, marginBottom: 6 }}>MERGE NODE</div>

                  {!mergeTarget ? (
                    <>
                      <input
                        autoFocus
                        placeholder="Search nodes by label…"
                        value={mergeQuery}
                        onChange={e => setMergeQuery(e.target.value)}
                        style={{
                          width: '100%', boxSizing: 'border-box', background: '#0d1117',
                          border: '1px solid #30363d', borderRadius: 4, color: '#e6edf3',
                          fontSize: 11, padding: '4px 8px', outline: 'none',
                        }}
                      />
                      {filtered.length > 0 && (
                        <div style={{ marginTop: 4, border: '1px solid #30363d', borderRadius: 4, overflow: 'hidden' }}>
                          {filtered.map(n => (
                            <div key={n.id} onClick={() => { setMergeTarget(n); setConflictChoices({}); }}
                              style={{
                                padding: '5px 8px', fontSize: 11, color: '#e6edf3', cursor: 'pointer',
                                borderBottom: '1px solid #21262d', background: 'transparent',
                              }}
                              onMouseEnter={e => (e.currentTarget.style.background = '#1c2128')}
                              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                            >
                              <span style={{ color: '#8b949e', marginRight: 6 }}>{n.type}</span>{n.label}
                            </div>
                          ))}
                        </div>
                      )}
                      <button onClick={() => { setMergeMode(false); setMergeQuery(''); }}
                        style={{ marginTop: 6, background: 'none', border: 'none', color: '#8b949e', fontSize: 10, cursor: 'pointer', padding: 0 }}>
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      {/* Canonical toggle */}
                      <div style={{ marginBottom: 10 }}>
                        <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 4 }}>KEEP AS CANONICAL</div>
                        {(['this', 'other'] as const).map(side => {
                          const lbl = side === 'this' ? thisNode.label : mergeTarget.label;
                          const active = mergeCanonical === side;
                          return (
                            <button key={side} onClick={() => setMergeCanonical(side)} style={{
                              display: 'block', width: '100%', textAlign: 'left', padding: '4px 8px',
                              marginBottom: 4, borderRadius: 4, fontSize: 11, cursor: 'pointer',
                              background: active ? '#1f6feb22' : 'transparent',
                              border: `1px solid ${active ? '#58a6ff' : '#30363d'}`,
                              color: active ? '#58a6ff' : '#8b949e',
                            }}>
                              {active ? '● ' : '○ '}{lbl}
                            </button>
                          );
                        })}
                      </div>

                      {/* Auto-fills */}
                      {fills.length > 0 && (
                        <div style={{ marginBottom: 8 }}>
                          <div style={{ fontSize: 10, color: '#3fb950', marginBottom: 2 }}>
                            AUTO-FILL ({fills.length} missing fields)
                          </div>
                          <div style={{ fontSize: 10, color: '#8b949e' }}>{fills.join(', ')}</div>
                        </div>
                      )}

                      {/* Conflicts */}
                      {conflicts.length > 0 && (
                        <div style={{ marginBottom: 10 }}>
                          <div style={{ fontSize: 10, color: '#e3b341', marginBottom: 4 }}>
                            CONFLICTING FIELDS — choose which value to keep
                          </div>
                          {conflicts.map(c => {
                            const choice = conflictChoices[c.key] ?? 'this';
                            const thisLbl = mergeCanonical === 'this' ? thisNode.label : mergeTarget.label;
                            const otherLbl = mergeCanonical === 'this' ? mergeTarget.label : thisNode.label;
                            const aVal = mergeCanonical === 'this' ? c.thisVal : c.otherVal;
                            const bVal = mergeCanonical === 'this' ? c.otherVal : c.thisVal;
                            return (
                              <div key={c.key} style={{ marginBottom: 6, padding: '5px 6px', background: '#0d1117', borderRadius: 4, border: '1px solid #30363d' }}>
                                <div style={{ fontSize: 10, color: '#484f58', marginBottom: 4 }}>{c.key}</div>
                                {(['this', 'other'] as const).map(side => {
                                  const val = side === 'this' ? aVal : bVal;
                                  const nodeLbl = side === 'this' ? thisLbl : otherLbl;
                                  const active = choice === side;
                                  return (
                                    <div key={side} onClick={() => setConflictChoices(prev => ({ ...prev, [c.key]: side }))}
                                      style={{ display: 'flex', alignItems: 'flex-start', gap: 6, cursor: 'pointer', marginBottom: 2 }}>
                                      <span style={{ color: active ? '#58a6ff' : '#484f58', fontSize: 11, flexShrink: 0, marginTop: 1 }}>
                                        {active ? '●' : '○'}
                                      </span>
                                      <span style={{ fontSize: 11, color: active ? '#e6edf3' : '#8b949e', wordBreak: 'break-all' }}>
                                        {String(val)} <span style={{ color: '#484f58' }}>({nodeLbl})</span>
                                      </span>
                                    </div>
                                  );
                                })}
                              </div>
                            );
                          })}
                        </div>
                      )}

                      <div style={{ display: 'flex', gap: 6 }}>
                        <button onClick={doMerge} disabled={merging} style={{
                          flex: 1, background: '#1f6feb', border: 'none', borderRadius: 4,
                          color: '#fff', fontSize: 11, cursor: merging ? 'default' : 'pointer', padding: '4px 0',
                        }}>
                          {merging ? 'Merging…' : 'Confirm Merge'}
                        </button>
                        <button onClick={() => { setMergeTarget(null); setMergeQuery(''); setConflictChoices({}); }}
                          style={{
                            flex: 1, background: 'none', border: '1px solid #30363d', borderRadius: 4,
                            color: '#8b949e', fontSize: 11, cursor: 'pointer', padding: '4px 0',
                          }}>
                          Back
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })()}

        {/* Delete */}
        <div style={{ marginTop: 12, borderTop: '1px solid #21262d', paddingTop: 12 }}>
          {confirmDelete ? (
            <div style={{ display: 'flex', gap: 6 }}>
              <button onClick={deleteItem} disabled={deleting}
                style={{
                  flex: 1, background: '#da3633', border: 'none', borderRadius: 4,
                  color: '#fff', fontSize: 11, cursor: deleting ? 'default' : 'pointer', padding: '4px 0',
                }}>
                {deleting ? 'Deleting…' : 'Confirm delete'}
              </button>
              <button onClick={() => setConfirmDelete(false)}
                style={{
                  flex: 1, background: 'none', border: '1px solid #30363d', borderRadius: 4,
                  color: '#8b949e', fontSize: 11, cursor: 'pointer', padding: '4px 0',
                }}>
                Cancel
              </button>
            </div>
          ) : (
            <button onClick={() => setConfirmDelete(true)}
              style={{
                width: '100%', background: 'none', border: '1px solid #da3633', borderRadius: 4,
                color: '#f78166', fontSize: 11, cursor: 'pointer', padding: '4px 0',
              }}>
              Delete {item.kind}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function NodeInfo({ node }: { node: KGNode }) {
  const attrs = node.attributes ?? {};
  const sources = node.sources ?? [];

  return (
    <>
      <div style={{ color: '#e6edf3', fontSize: 14, fontWeight: 600, marginBottom: 4, wordBreak: 'break-word' }}>
        {node.label}
      </div>
      <div style={{ marginBottom: 12 }}>
        <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: '#21262d', color: '#bc8cff', border: '1px solid #30363d' }}>
          {node.type}
        </span>
        {(node.inferred_types ?? []).map((t) => (
          <span key={t} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: '#0d1117', color: '#484f58', border: '1px solid #21262d', marginLeft: 4 }}>
            {t}
          </span>
        ))}
      </div>

      {/* Attributes */}
      {Object.keys(attrs).length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ color: '#8b949e', fontSize: 10, fontWeight: 600, marginBottom: 6 }}>ATTRIBUTES</div>
          {Object.entries(attrs).map(([key, raw]) => {
            const av = raw as KGAttrValue;
            const val = av?.value !== undefined ? av.value : raw;
            const date = av?.event_date ?? null;
            if (val === null || val === undefined || val === '') return null;
            return (
              <div key={key} style={{ marginBottom: 8, paddingBottom: 8, borderBottom: '1px solid #21262d' }}>
                <div style={{ color: '#484f58', fontSize: 10, marginBottom: 2 }}>{key}</div>
                <div style={{ color: '#e6edf3', fontSize: 12, wordBreak: 'break-word' }}>
                  {Array.isArray(val) ? val.join(', ') : String(val)}
                </div>
                {date && <div style={{ color: '#484f58', fontSize: 10, marginTop: 2 }}>{date}</div>}
              </div>
            );
          })}
        </div>
      )}

      {/* News keywords */}
      <NodeKeywordsEditor nodeId={node.id} initial={
        (() => { const a = attrs.news_keywords as { value?: unknown } | undefined; return String(a?.value ?? ''); })()
      } />

      {/* Sources */}
      {sources.length > 0 && <SourcesList sources={sources} />}

      {/* Timestamps */}
      {node.created_at && (
        <div style={{ color: '#484f58', fontSize: 10, marginTop: 8 }}>
          Added {node.created_at.slice(0, 10)}
        </div>
      )}
    </>
  );
}

function EdgeInfo({ edge, sourceLabel, targetLabel, editing, labelDraft, saving, onDraftChange, onEditStart, onEditCancel, onEditSave }: {
  edge: KGEdge; sourceLabel: string; targetLabel: string;
  editing: boolean; labelDraft: string; saving: boolean;
  onDraftChange: (v: string) => void;
  onEditStart: () => void; onEditCancel: () => void; onEditSave: () => void;
}) {
  const sources = edge.sources ?? [];
  return (
    <>
      {/* Relation display */}
      <div style={{ marginBottom: 14, padding: '8px 10px', background: '#0d1117', borderRadius: 6 }}>
        <div style={{ color: '#8b949e', fontSize: 11, marginBottom: 4, wordBreak: 'break-word' }}>{sourceLabel}</div>
        {editing ? (
          <>
            <input
              value={labelDraft} onChange={(e) => onDraftChange(e.target.value)} autoFocus
              style={{
                width: '100%', boxSizing: 'border-box', background: '#161b22',
                border: '1px solid #388bfd', borderRadius: 4,
                color: '#bc8cff', fontSize: 12, padding: '3px 6px', marginBottom: 4,
              }}
            />
            <div style={{ display: 'flex', gap: 6 }}>
              <button onClick={onEditSave} disabled={saving}
                style={{ flex: 1, background: '#1f6feb', border: 'none', borderRadius: 4, color: '#fff', fontSize: 11, cursor: saving ? 'default' : 'pointer', padding: '3px 0' }}>
                {saving ? 'Saving…' : 'Save'}
              </button>
              <button onClick={onEditCancel}
                style={{ flex: 1, background: 'none', border: '1px solid #30363d', borderRadius: 4, color: '#8b949e', fontSize: 11, cursor: 'pointer', padding: '3px 0' }}>
                Cancel
              </button>
            </div>
          </>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ color: '#bc8cff', fontSize: 12, fontWeight: 600 }}>— {edge.label} →</span>
            <button onClick={onEditStart}
              style={{ background: 'none', border: 'none', color: '#58a6ff', fontSize: 11, cursor: 'pointer', padding: 0 }}>
              Edit
            </button>
          </div>
        )}
        <div style={{ color: '#8b949e', fontSize: 11, marginTop: 4, wordBreak: 'break-word' }}>{targetLabel}</div>
      </div>

      {/* Sources */}
      {sources.length > 0 && <SourcesList sources={sources} />}

      {edge.created_at && (
        <div style={{ color: '#484f58', fontSize: 10, marginTop: 8 }}>
          Added {edge.created_at.slice(0, 10)}
        </div>
      )}
    </>
  );
}

function NodeKeywordsEditor({ nodeId, initial }: { nodeId: string; initial: string }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(initial);
  const [saved, setSaved] = useState(initial);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/kg/nodes/${encodeURIComponent(nodeId)}/attribute`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'news_keywords', value: value.trim() }),
      });
      if (r.ok) { setSaved(value.trim()); setEditing(false); }
    } finally { setSaving(false); }
  };

  return (
    <div style={{ marginBottom: 14, borderTop: '1px solid #21262d', paddingTop: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ color: '#8b949e', fontSize: 10, fontWeight: 600 }}>NEWS KEYWORDS</span>
        {!editing && (
          <button onClick={() => { setValue(saved); setEditing(true); }}
            style={{ background: 'none', border: 'none', color: '#58a6ff', fontSize: 11, cursor: 'pointer', padding: 0 }}>
            Edit
          </button>
        )}
      </div>
      {editing ? (
        <>
          <textarea
            value={value} onChange={(e) => setValue(e.target.value)}
            placeholder="e.g. NASA, NOAA&#10;Comma-separated search terms"
            rows={3}
            style={{
              width: '100%', boxSizing: 'border-box', background: '#0d1117',
              border: '1px solid #388bfd', borderRadius: 4, color: '#e6edf3',
              fontSize: 12, padding: '6px 8px', resize: 'vertical', fontFamily: 'inherit',
            }}
          />
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <button onClick={save} disabled={saving}
              style={{ flex: 1, background: '#1f6feb', border: 'none', borderRadius: 4, color: '#fff', fontSize: 11, cursor: saving ? 'default' : 'pointer', padding: '4px 0' }}>
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button onClick={() => setEditing(false)}
              style={{ flex: 1, background: 'none', border: '1px solid #30363d', borderRadius: 4, color: '#8b949e', fontSize: 11, cursor: 'pointer', padding: '4px 0' }}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <div style={{ color: saved ? '#e6edf3' : '#484f58', fontSize: 12, lineHeight: 1.5, wordBreak: 'break-word' }}>
          {saved || 'Not set — excluded from news feed'}
        </div>
      )}
    </div>
  );
}

function SourcesList({ sources }: { sources: { source_id: string; title?: string; url?: string; date?: string; excerpt?: string }[] }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ color: '#8b949e', fontSize: 10, fontWeight: 600, marginBottom: 6 }}>SOURCES</div>
      {sources.map((s, i) => (
        <div key={i} style={{ marginBottom: 8, padding: '6px 8px', background: '#0d1117', borderRadius: 4, borderLeft: '2px solid #388bfd' }}>
          {s.url ? (
            <a
              href={s.url} target="_blank" rel="noopener noreferrer"
              style={{ color: '#58a6ff', fontSize: 11, wordBreak: 'break-word', lineHeight: 1.4, display: 'block', textDecoration: 'none' }}
              onMouseEnter={(e) => ((e.target as HTMLElement).style.textDecoration = 'underline')}
              onMouseLeave={(e) => ((e.target as HTMLElement).style.textDecoration = 'none')}
            >
              {s.title || s.source_id}
            </a>
          ) : (
            <div style={{ color: '#8b949e', fontSize: 11, wordBreak: 'break-word' }}>{s.title || s.source_id}</div>
          )}
          {s.date && <div style={{ color: '#484f58', fontSize: 10, marginTop: 2 }}>{s.date.slice(0, 10)}</div>}
          {s.excerpt && (
            <div style={{ color: '#8b949e', fontSize: 11, marginTop: 4, fontStyle: 'italic', lineHeight: 1.4 }}>
              "{s.excerpt}"
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
