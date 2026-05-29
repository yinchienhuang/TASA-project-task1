"""
Spaceflight News API collector.
Articles are fetched and immediately queued for KG processing.
No raw cache — processed documents live in source_store (data/sources/).
The news feed is served from source_store, not a separate cache file.
"""
import requests

BASE_URL = "https://api.spaceflightnewsapi.net/v4"


def _build_keyword_map() -> dict[str, list[str]]:
    """Build node_id → keyword list for all KG nodes that have news_keywords set.

    For satellite nodes without explicit keywords, falls back to label + aliases.
    The node_id for satellites already equals their NORAD ID, so existing
    per-satellite news filtering continues to work unchanged.
    """
    try:
        from modules.knowledge_graph.kg_store import kg_store
        from modules.knowledge_graph.schema import schema_manager
        if not schema_manager._loaded:
            print("[news] KG not loaded yet — skipping keyword map build")
            return {}

        result: dict[str, list[str]] = {}
        for node in kg_store.nodes.values():
            node_id = node["id"]
            attrs = node.get("attributes", {})
            all_types = [node.get("type", "")] + node.get("inferred_types", [])
            is_satellite = any("Satellite" in t for t in all_types)

            kw_attr = attrs.get("news_keywords", {})
            kw_val = kw_attr.get("value") if isinstance(kw_attr, dict) else kw_attr
            if kw_val and str(kw_val).strip():
                keywords = [k.strip() for k in str(kw_val).split(",") if k.strip()]
            elif is_satellite:
                # Satellites without explicit keywords: fall back to label + aliases
                label = node.get("label", "").strip()
                alias_attr = attrs.get("aliases", {})
                alias_val = alias_attr.get("value") if isinstance(alias_attr, dict) else alias_attr
                aliases = alias_val if isinstance(alias_val, list) else []
                keywords = ([label] if label else []) + [a for a in aliases if isinstance(a, str)]
            else:
                continue  # non-satellite nodes require explicit keywords

            if keywords:
                result[node_id] = keywords
        return result
    except Exception as e:
        print(f"[news] could not build KG keyword map: {e}")
        return {}


def _fetch(query: str, limit: int = 10) -> list[dict]:
    try:
        resp = requests.get(
            f"{BASE_URL}/articles/",
            params={"search": query, "limit": limit, "ordering": "-published_at"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as e:
        print(f"[news] fetch error for '{query}': {e}")
        return []


def _collect_for(node_id: str, keywords: list[str], limit: int = 10) -> int:
    """Fetch articles for a node's keywords and store them in source_store.
    Returns count of newly stored articles. Does NOT run LLM extraction —
    users explicitly queue articles via the news feed '+ Queue' button."""
    from modules.knowledge_graph import source_store
    from modules.knowledge_graph.kg_store import kg_store

    new_count = 0
    seen_ids: set[str] = set()
    for kw in keywords:
        for raw in _fetch(kw, limit=limit):
            source_id = f"snapi_{raw['id']}"
            if source_id in seen_ids:
                continue
            seen_ids.add(source_id)
            # Update related_node_ids on existing entry or create new
            index = source_store._load_index()
            existing = index.get(source_id)
            if existing:
                nids = existing.get("related_norad_ids", [])
                if node_id not in nids:
                    nids.append(node_id)
                    existing["related_norad_ids"] = nids
                    source_store._save_index(index)
            else:
                source_store.save_source(source_id, {
                    "type": "news",
                    "title": raw.get("title", ""),
                    "url": raw.get("url", ""),
                    "date": raw.get("published_at", ""),
                    "news_site": raw.get("news_site", ""),
                    "related_norad_ids": [node_id],
                }, raw.get("summary", ""))
                new_count += 1
    return new_count


# ── Collection ────────────────────────────────────────────────────────────────

def collect_all() -> int:
    """Fetch latest articles for all KG nodes with keywords. Returns count of newly stored articles."""
    keyword_map = _build_keyword_map()
    print(f"[news] collecting for {len(keyword_map)} nodes: {list(keyword_map.keys())}")
    count = 0
    for node_id, keywords in keyword_map.items():
        count += _collect_for(node_id, keywords)
    print(f"[news] stored {count} new articles")
    return count


def collect_for_satellite(norad_id: str, limit: int = 20) -> int:
    """Fetch articles for a single node. Raises ValueError if no keywords configured."""
    keyword_map = _build_keyword_map()
    keywords = keyword_map.get(norad_id)
    if not keywords:
        raise ValueError(f"No keywords configured for node {norad_id} — set news_keywords on the KG node")
    return _collect_for(norad_id, keywords, limit=limit)


def reset_and_refetch(norad_id: str) -> dict:
    """Re-fetch articles for a node using current KG keywords. Returns {removed, fetched}."""
    keyword_map = _build_keyword_map()
    keywords = keyword_map.get(norad_id)
    if not keywords:
        raise ValueError(f"No keywords configured for node {norad_id}")
    fetched = _collect_for(norad_id, keywords, limit=20)
    print(f"[news] reset {norad_id}: stored {fetched} new articles")
    return {"removed": 0, "fetched": fetched, "total": total()}


# ── Queries (from source_store) ───────────────────────────────────────────────

def get_all() -> list[dict]:
    """Return all processed news articles from source_store, newest first."""
    from modules.knowledge_graph import source_store
    return sorted(
        [s for s in source_store.get_all_sources() if s.get("type") == "news"],
        key=lambda s: s.get("date", ""),
        reverse=True,
    )


def get_by_norad(norad_id: str) -> list[dict]:
    """Return processed news articles associated with a given NORAD ID."""
    from modules.knowledge_graph import source_store
    return sorted(
        [s for s in source_store.get_all_sources()
         if s.get("type") == "news" and norad_id in (s.get("related_norad_ids") or [])],
        key=lambda s: s.get("date", ""),
        reverse=True,
    )


def total() -> int:
    from modules.knowledge_graph import source_store
    return sum(1 for s in source_store.get_all_sources() if s.get("type") == "news")
