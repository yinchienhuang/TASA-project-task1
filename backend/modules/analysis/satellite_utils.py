"""Utility functions for satellite classification (no external dependencies)."""
from modules.knowledge_graph.kg_store import kg_store


_CHINESE_OPERATORS = {"casc", "cnsa", "pla", "china", "chinese", "cast", "cgwic", "commsat"}


def _is_chinese_satellite(node: dict) -> bool:
    """Heuristic: check if a KG satellite node is operated by a Chinese entity."""
    attrs = node.get("attributes") or {}
    operator = str((attrs.get("operator") or {}).get("value") or "").lower()
    if any(kw in operator for kw in _CHINESE_OPERATORS):
        return True
    # Also check edges via kg_store
    nid = node.get("id", "")
    for eid, edge in kg_store.edges.items():
        if edge.get("source") == nid and edge.get("type") in ("operatedBy", "builtBy", "ownedBy"):
            target_id = edge.get("target", "")
            target_node = kg_store.nodes.get(target_id, {})
            target_label = (target_node.get("label") or "").lower()
            if any(kw in target_label for kw in _CHINESE_OPERATORS):
                return True
    return False


def _is_satellite_node(node: dict) -> bool:
    """Check if a KG node represents a satellite."""
    all_types = [node.get("type", "")] + (node.get("inferred_types") or [])
    return any(t == "Satellite" for t in all_types)
