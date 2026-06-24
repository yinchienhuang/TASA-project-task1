"""
KGStore: JSON-persisted knowledge graph (nodes, edges, conflicts, sources).
"""
import json
import pathlib
from datetime import datetime, timezone
from typing import Any

GRAPH_FILE = pathlib.Path(__file__).parents[3] / "data" / "kg" / "graph.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


import re as _re

def _normalize_label(s: str) -> str:
    """Normalize a label for fuzzy dedup: lowercase, strip parens/brackets, collapse spaces, normalize Corp./Corporation."""
    s = s.lower()
    s = _re.sub(r'\([^)]*\)', '', s)   # remove parentheticals like "(CASC)"
    s = _re.sub(r'\[[^\]]*\]', '', s)   # remove bracket suffixes
    s = s.replace('corporation', 'corp').replace('corp.', 'corp')
    s = s.replace('limited', 'ltd').replace('ltd.', 'ltd')
    s = s.replace('incorporated', 'inc').replace('inc.', 'inc')
    s = _re.sub(r'[^\w\s]', '', s)      # strip remaining punctuation
    s = _re.sub(r'\s+', ' ', s).strip()
    return s


class KGStore:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}
        self.conflicts: list[dict] = []
        self.sources: dict[str, dict] = {}
        self.processed_sources: set[str] = set()

    def load(self) -> None:
        GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not GRAPH_FILE.exists():
            self.save()
            return
        with open(GRAPH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.nodes = data.get("nodes", {})
        self.edges = data.get("edges", {})
        self.conflicts = data.get("conflicts", [])
        self.sources = data.get("sources", {})
        self.processed_sources = set(data.get("processed_sources", []))
        print(f"[kg_store] loaded: {len(self.nodes)} nodes, {len(self.edges)} edges, {len(self.processed_sources)} processed sources")

    def save(self) -> None:
        GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(GRAPH_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "nodes": self.nodes,
                "edges": self.edges,
                "conflicts": self.conflicts,
                "sources": self.sources,
                "processed_sources": list(self.processed_sources),
            }, f, ensure_ascii=False, indent=2)

    def is_processed(self, source_id: str) -> bool:
        return source_id in self.processed_sources

    def mark_processed(self, source_id: str) -> None:
        self.processed_sources.add(source_id)

    def register_source(self, source_id: str, metadata: dict) -> None:
        self.sources[source_id] = metadata

    # ── Alias validation ───────────────────────────────────────────────────────

    def _validate_aliases_immutable(self, node_id: str, new_aliases: list) -> None:
        """
        Validate that aliases can only be added, never removed.

        Raises ValueError if any existing aliases are missing from new_aliases.
        """
        if node_id not in self.nodes:
            return  # New node, no validation needed

        existing_node = self.nodes[node_id]
        existing_aliases = (existing_node.get("attributes", {})
                           .get("aliases", {})
                           .get("value", []) or [])

        if not existing_aliases:
            return  # No existing aliases, any new aliases are fine

        new_aliases = new_aliases or []
        existing_set = set(existing_aliases)
        new_set = set(new_aliases)

        removed_aliases = existing_set - new_set
        if removed_aliases:
            raise ValueError(
                f"Node '{node_id}': Aliases can only be added, not removed. "
                f"Removed aliases: {removed_aliases}. "
                f"Existing: {existing_set}, New: {new_set}"
            )

    # ── Nodes ─────────────────────────────────────────────────────────────────

    def upsert_node(self, node: dict) -> str:
        """Insert or update a node. Returns 'created' | 'updated' | 'duplicate'.

        Raises ValueError if aliases are being removed.
        """
        node_id = node["id"]

        # Validate aliases before making any changes
        new_aliases = (node.get("attributes", {})
                      .get("aliases", {})
                      .get("value", []) or [])
        self._validate_aliases_immutable(node_id, new_aliases)

        if node_id not in self.nodes:
            self.nodes[node_id] = {**node, "created_at": _now(), "updated_at": _now()}
            return "created"
        existing = self.nodes[node_id]
        # Merge new sources
        new_sources = node.get("sources", [])
        existing_source_ids = {s["source_id"] for s in existing.get("sources", [])}
        added = False
        for s in new_sources:
            if s["source_id"] not in existing_source_ids:
                existing.setdefault("sources", []).append(s)
                added = True
        # Merge attributes: fill nulls from new node
        new_attrs = node.get("attributes", {})
        existing_attrs = existing.get("attributes", {})
        for key, val in new_attrs.items():
            if key not in existing_attrs or existing_attrs[key]["value"] is None:
                if val.get("value") is not None:
                    existing_attrs[key] = val
                    added = True
        existing["attributes"] = existing_attrs
        if added:
            existing["updated_at"] = _now()
            return "updated"
        return "duplicate"

    def apply_node(self, node: dict) -> None:
        """Directly write a node to the store (used when approving pending items).

        Raises ValueError if aliases are being removed.
        """
        node_id = node["id"]

        # Validate aliases before making any changes
        new_aliases = (node.get("attributes", {})
                      .get("aliases", {})
                      .get("value", []) or [])
        self._validate_aliases_immutable(node_id, new_aliases)

        if node_id in self.nodes:
            self.nodes[node_id].update({**node, "updated_at": _now()})
        else:
            self.nodes[node_id] = {**node, "created_at": _now(), "updated_at": _now()}

    def find_node_by_label(self, label: str) -> dict | None:
        label_lower = label.lower().strip()
        label_norm = _normalize_label(label)
        for node in self.nodes.values():
            node_label = node.get("label", "")
            if node_label.lower().strip() == label_lower:
                return node
            if _normalize_label(node_label) == label_norm:
                return node
            # Also search aliases
            for alias in (node.get("attributes", {})
                              .get("aliases", {})
                              .get("value", []) or []):
                if str(alias).lower().strip() == label_lower:
                    return node
        return None

    def merge_nodes(self, canonical_id: str, duplicate_id: str, overrides: dict | None = None) -> dict:
        """Merge duplicate_id into canonical_id. overrides: {attr_key: chosen_value} for conflicts."""
        canonical = self.nodes.get(canonical_id)
        duplicate = self.nodes.get(duplicate_id)
        if not canonical or not duplicate:
            raise KeyError("Node not found")
        overrides = overrides or {}

        # 1. Merge attributes
        for key, dup_attr in duplicate.get("attributes", {}).items():
            dup_val = dup_attr.get("value") if isinstance(dup_attr, dict) else dup_attr
            can_attr = canonical.get("attributes", {}).get(key)
            can_val = can_attr.get("value") if isinstance(can_attr, dict) else can_attr

            if key == "aliases":
                c_list = (can_attr.get("value", []) if isinstance(can_attr, dict) else []) or []
                d_list = (dup_attr.get("value", []) if isinstance(dup_attr, dict) else []) or []
                merged = list(dict.fromkeys(c_list + d_list))
                canonical.setdefault("attributes", {})[key] = {"value": merged, "event_date": None, "source_id": None}
            elif can_val is None:
                canonical.setdefault("attributes", {})[key] = dup_attr
            elif key in overrides:
                canonical["attributes"][key] = {
                    "value": overrides[key],
                    "event_date": dup_attr.get("event_date") if isinstance(dup_attr, dict) else None,
                    "source_id": dup_attr.get("source_id") if isinstance(dup_attr, dict) else None,
                }
            # else: canonical wins — no action

        # 2. Add duplicate's label as alias on canonical
        alias_attr = canonical.get("attributes", {}).get("aliases", {})
        alias_list = (alias_attr.get("value", []) if isinstance(alias_attr, dict) else []) or []
        dup_label = duplicate.get("label", "")
        if dup_label and dup_label not in alias_list and dup_label != canonical.get("label"):
            alias_list = list(alias_list) + [dup_label]
            canonical.setdefault("attributes", {})["aliases"] = {"value": alias_list, "event_date": None, "source_id": None}

        # 3. Merge sources (dedup by source_id)
        existing_sids = {s.get("source_id") for s in canonical.get("sources", [])}
        for s in duplicate.get("sources", []):
            if s.get("source_id") not in existing_sids:
                canonical.setdefault("sources", []).append(s)

        # 4. Re-point edges; drop exact duplicates created by redirect
        edges_redirected = 0
        edges_to_delete = []
        for eid, edge in list(self.edges.items()):
            changed = False
            if edge.get("source") == duplicate_id:
                edge["source"] = canonical_id
                changed = True
            if edge.get("target") == duplicate_id:
                edge["target"] = canonical_id
                changed = True
            if changed:
                new_id = self._edge_id(edge["source"], edge["label"], edge["target"])
                if new_id != eid:
                    if new_id in self.edges:
                        edges_to_delete.append(eid)
                    else:
                        edge["id"] = new_id
                        self.edges[new_id] = self.edges.pop(eid)
                edges_redirected += 1

        for eid in edges_to_delete:
            if eid in self.edges:
                del self.edges[eid]

        # 5. Remove duplicate node
        del self.nodes[duplicate_id]
        canonical["updated_at"] = _now()
        self.save()
        return {
            "canonical_id": canonical_id,
            "removed_id": duplicate_id,
            "edges_redirected": edges_redirected,
            "duplicate_edges_removed": len(edges_to_delete),
        }

    # ── Edges ─────────────────────────────────────────────────────────────────

    def _edge_id(self, source: str, label: str, target: str) -> str:
        return f"e_{source}_{label}_{target}"

    def upsert_edge(self, edge: dict) -> str:
        """Insert or update an edge. Returns 'created' | 'updated' | 'duplicate'."""
        edge_id = edge.get("id") or self._edge_id(edge["source"], edge["label"], edge["target"])
        edge["id"] = edge_id
        if edge_id not in self.edges:
            self.edges[edge_id] = {**edge, "created_at": _now(), "updated_at": _now()}
            return "created"
        existing = self.edges[edge_id]
        new_sources = edge.get("sources", [])
        existing_source_ids = {s["source_id"] for s in existing.get("sources", [])}
        added = False
        for s in new_sources:
            if s["source_id"] not in existing_source_ids:
                existing.setdefault("sources", []).append(s)
                added = True
        if added:
            existing["updated_at"] = _now()
            return "updated"
        return "duplicate"

    def apply_edge(self, edge: dict) -> None:
        edge_id = edge.get("id") or self._edge_id(edge["source"], edge["label"], edge["target"])
        edge["id"] = edge_id
        if edge_id in self.edges:
            self.edges[edge_id].update({**edge, "updated_at": _now()})
        else:
            self.edges[edge_id] = {**edge, "created_at": _now(), "updated_at": _now()}

    def find_edges_by_source_label(self, source_id: str, label: str) -> list[dict]:
        return [e for e in self.edges.values() if e["source"] == source_id and e["label"] == label]

    # ── Conflicts ─────────────────────────────────────────────────────────────

    def add_conflict(self, conflict: dict) -> None:
        self.conflicts.append({**conflict, "detected_at": _now()})

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_all(self) -> dict:
        return {"nodes": self.nodes, "edges": self.edges}

    def get_subgraph(self, node_id: str, hops: int = 1) -> dict:
        visited_nodes = set()
        frontier = {node_id}
        for _ in range(hops):
            next_frontier = set()
            for nid in frontier:
                visited_nodes.add(nid)
                for edge in self.edges.values():
                    if edge["source"] == nid and edge["target"] not in visited_nodes:
                        next_frontier.add(edge["target"])
                    if edge["target"] == nid and edge["source"] not in visited_nodes:
                        next_frontier.add(edge["source"])
            frontier = next_frontier
        visited_nodes.update(frontier)
        sub_nodes = {nid: self.nodes[nid] for nid in visited_nodes if nid in self.nodes}
        sub_edges = {
            eid: e for eid, e in self.edges.items()
            if e["source"] in visited_nodes and e["target"] in visited_nodes
        }
        return {"nodes": sub_nodes, "edges": sub_edges}

    def get_existing_labels(self) -> dict[str, str]:
        """Returns {label: node_id} for entity linking in prompts."""
        return {node["label"]: nid for nid, node in self.nodes.items()}


# Singleton
kg_store = KGStore()
