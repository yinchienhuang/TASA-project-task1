"""
GPT-4o agentic Q&A engine with multi-step tool calling for SSA questions.
"""
import json
import os
from datetime import datetime, timezone

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


# LLM Model configuration
LLM_MODEL = "gpt-4o"

# Supported event types in the system
SUPPORTED_EVENT_TYPES = {"launch", "maneuver", "photometric_change"}

_SYSTEM_PROMPT = """You are an SSA (Space Situational Awareness) analyst assistant. Answer questions about satellite maneuvers, orbital patterns, coverage, and related intelligence.

## How to use tools

A PLANNING step has been done first - you have a suggested tool usage plan.
Review the plan and execute it by calling the suggested tools IN ORDER.

You have autonomy to:
- Follow the suggested plan (recommended for comprehensive answers)
- Deviate from the plan if you discover better approaches mid-execution
- Call additional tools if needed to deepen analysis
- Skip tools from the plan only if they become unnecessary after earlier results

The tool descriptions explain what each tool does - use them to understand when to apply each one.

## Source Report Enhancement (IMPORTANT)

When your answer references source reports (from search_events, get_entity_relationships, or other tools):
1. ALWAYS call search_report_content to retrieve the FULL report text
2. Use the complete report content to enhance and deepen your analysis
3. Extract specific details, quotes, and context from the full report
4. This elevates your answer from summary-level to source-level detail

Example: If search_events returns "maneuver on 2026-06-17", call search_report_content to get the complete analysis, then include specific technical details, assessments, and context from the report.

## Important Patterns

- For "what events?", "what happened?", "satellite activity", or "dynamics" questions: use search_all_events (not search_events) to get all event types at once
- For "maneuver history" of a single satellite: use get_maneuver_history for deeper detail
- For detailed analysis: combine structured data (events) with full report context via search_report_content
- For "what happened" questions: use source reports as the authoritative source
- Never cite a report without reading its full content

## Core Rules

1. Always cite sources with full context from reports (not just summaries)
2. Search_report_content is not optional when citing reports - use it to enrich answers
3. If data could be more complete, gather it
4. Never assume single-tool answers are comprehensive
5. Supported event types only: launch, maneuver, photometric_change
6. For numeric values: include units, round to 2 decimal places

- Today's date: """ + datetime.now(timezone.utc).strftime("%Y-%m-%d") + """
- Regions: taiwan, south_china_sea, east_china_sea, korean_peninsula, persian_gulf, ukraine"""

_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_entity_relationships",
            "description": "Scan ALL edges connected to a single entity. Returns all relationship types and related entities with source reports. NO target type filtering - scans everything. Best for: 'What are all relationships for SJ-20?', 'Show info about AZERSPACE-2', 'What does X relate to?'. This is the primary tool for entity relationship queries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "Entity name, ID, or node ID (e.g., 'SJ-20', 'AZERSPACE-2', '44910')"},
                },
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_satellites_by_country",
            "description": "Find all satellites operated by a specific country. Returns list of satellite names with basic info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "country": {"type": "string", "description": "Country name (e.g. 'China', 'USA', 'Pakistan'). Full list of countries in system: China, Pakistan, USA"},
                },
                "required": ["country"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_satellite_info",
            "description": "Get KG metadata for a satellite: label, type, operator, orbital params, mission info. Can query by satellite name (e.g. 'TJS-24'), KG node ID, or NORAD ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "satellite_id": {"type": "string", "description": "Satellite name (e.g. TJS-24, COSMOS 2589), KG node ID, or NORAD catalog number"}
                },
                "required": ["satellite_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_events",
            "description": "Fleet-level search across all satellite events. Returns matching events sorted newest first. Only supports: launch, maneuver, photometric_change. Do NOT use unsupported types like 'close_approach' or 'rpo'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Event type filter: ONLY 'maneuver', 'launch', or 'photometric_change'. Required. No other types are supported."},
                    "regime": {"type": "string", "description": "Orbital regime filter: LEO | MEO | GEO | HEO"},
                    "days": {"type": "integer", "description": "Limit to events in the past N days"},
                    "satellite_id": {"type": "string", "description": "Filter by satellite name (e.g. TJS-24), KG node ID, or NORAD ID"},
                },
                "required": ["type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_all_events",
            "description": "Search ALL types of satellite events (maneuver, photometric_change, launch) in a single aggregated query. Best for 'What events happened?', 'What should I monitor?', or 'Tell me about satellite activity' questions. Automatically queries all event types and returns them sorted by date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "regime": {"type": "string", "description": "Optional orbital regime filter: LEO | MEO | GEO | HEO"},
                    "days": {"type": "integer", "description": "Optional limit to events in the past N days"},
                    "satellite_id": {"type": "string", "description": "Optional filter by satellite name (e.g. TJS-24), KG node ID, or NORAD ID"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_maneuver_history",
            "description": "Get all maneuver events for a specific satellite, optionally filtered by recency.",
            "parameters": {
                "type": "object",
                "properties": {
                    "satellite_id": {"type": "string", "description": "Satellite name (e.g. TJS-24), KG node ID, or NORAD ID"},
                    "days": {"type": "integer", "description": "Only return maneuvers in the past N days"},
                },
                "required": ["satellite_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_coverage",
            "description": "Compute how many times a satellite passes over a named geographic region.",
            "parameters": {
                "type": "object",
                "properties": {
                    "norad_id": {"type": "string", "description": "NORAD catalog number"},
                    "region": {"type": "string", "description": "Named region ID (e.g. taiwan, south_china_sea)"},
                    "days": {"type": "integer", "description": "Number of days to analyze (default 7)"},
                },
                "required": ["norad_id", "region"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fleet_coverage",
            "description": "Rank satellites from a given country by how frequently they pass over a region.",
            "parameters": {
                "type": "object",
                "properties": {
                    "country": {"type": "string", "description": "Country filter, e.g. 'china'"},
                    "region": {"type": "string", "description": "Named region ID"},
                    "days": {"type": "integer", "description": "Number of days to analyze (default 30)"},
                },
                "required": ["country", "region"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_report_content",
            "description": "Search raw NOTOS/JCO report files by satellite name/ID or keyword. Use only when structured data is insufficient (e.g., needing specific analyst assessment, detailed orbits, or report-specific context).",
            "parameters": {
                "type": "object",
                "properties": {
                    "satellite_name_or_id": {"type": "string", "description": "Satellite name (e.g. 'COSMOS 2589', 'TJS-15', 'SHIYAN 30-01') or NORAD ID"},
                    "keyword": {"type": "string", "description": "Optional keyword to filter results (e.g. 'maneuver', 'photometric', 'delta_v')"},
                },
                "required": ["satellite_name_or_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_report_by_file",
            "description": "Read the COMPLETE content of a specific NOTOS/JCO report file by its exact filename. Use this when you have a source filename from another tool (e.g., from search_events or get_entity_relationships) and need to read the full report. Returns the entire report text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Exact filename of the report (e.g., 'NOTSO_Maneuver_SJ-20 (44910)_GEO_17Jun_2100Z.mhtml' or with .txt extension)"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explore_relationships",
            "description": "Autonomously traverse the knowledge graph to find related entities. Use for multi-hop queries: finding satellites by country, checking close approaches, discovering operators, etc. Examples: 'close approach events', 'satellites operated by country', 'launch organizations'. Works with all relationship types in the graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_node_id": {
                        "type": "string",
                        "description": "Starting node ID or satellite name (e.g., 'sat_tjs6', 'SJ-20', 'AZERSPACE-2', 'COSMOS 2520', '47613')"
                    },
                    "target_info": {
                        "type": "string",
                        "description": "Natural language description of what to find. Examples: 'satellites with close approach to this one', 'all satellites operated by this country', 'organizations that operate this satellite', 'close approach relationships'"
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum traversal depth (1-3, default 2)",
                        "default": 2
                    }
                },
                "required": ["start_node_id", "target_info"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_info",
            "description": "Get detailed information about any node in the knowledge graph. Works for satellites, organizations, launch sites, missions, and other entity types.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "Node ID (e.g., 'sat_tjs6', 'org_casc', 'mission_xyz') or entity name/identifier"
                    }
                },
                "required": ["node_id"]
            }
        }
    }
]


async def _understand_target_info(target_info: str) -> dict:
    """Use LLM to understand what information to find in the graph."""
    client = _get_client()

    prompt = f"""Given this natural language request about a knowledge graph:
"{target_info}"

Available relationship types in the knowledge graph:
- operatedBy: Who operates a satellite
- launchedBy: Who launched a satellite
- launchedFrom: Which launch site was used
- closeApproachWith: Satellites that had close approaches
- manufacturedBy: Who manufactured a satellite
- launchContractWith: Organizations with launch contracts
- hasHeadquarters: Organization headquarters locations

Determine:
1. target_type: What type of nodes to find (e.g., "Satellite", "Organization", "LaunchSite")
2. relationship_types: What relationships to traverse from the available list above. If the query mentions:
   - "close approach", "proximity", "passing near" → use ["closeApproachWith"]
   - "operator", "operated by" → use ["operatedBy"]
   - "launch", "launched" → use ["launchedBy", "launchedFrom"]
   - "manufacturer", "made by" → use ["manufacturedBy"]
3. directions: Direction to traverse (["outgoing"], ["incoming"], or ["outgoing", "incoming"])
4. estimated_depth: How many hops needed (1-3)

Return as JSON only, no explanation:
{{
  "target_type": "...",
  "relationship_types": [...],
  "directions": [...],
  "estimated_depth": N,
  "reasoning": "..."
}}
"""

    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=2000
        )
        result = json.loads(response.choices[0].message.content)
        return result
    except:
        return {
            "target_type": "Satellite",
            "relationship_types": ["operatedBy"],
            "directions": ["outgoing", "incoming"],
            "estimated_depth": 2,
            "reasoning": "fallback"
        }


async def _bfs_traverse(start_id: str, understanding: dict, max_depth: int, max_nodes: int = 50) -> list:
    """Breadth-first search through knowledge graph following the understanding."""
    from collections import deque
    from modules.knowledge_graph.kg_store import kg_store

    target_type = understanding.get("target_type", "Satellite")
    relationship_types = understanding.get("relationship_types", [])
    directions = understanding.get("directions", ["outgoing", "incoming"])

    queue = deque([(start_id, 0)])
    visited = {start_id}
    found = []

    while queue and len(found) < max_nodes:
        node_id, depth = queue.popleft()

        if depth > max_depth:
            continue

        node = kg_store.nodes.get(node_id)
        if not node:
            continue

        # Check if this is target type (with flexible matching for subtypes)
        node_types = [node.get("type", "")] + (node.get("inferred_types") or [])

        # Match logic: if target_type is "Satellite", match any *Satellite type
        type_matches = False
        if target_type in node_types:
            type_matches = True
        elif target_type == "Satellite" and any(t.endswith("Satellite") for t in node_types):
            type_matches = True

        if type_matches:
            if node_id != start_id:  # Don't return start node
                found.append(node)

        # Traverse edges
        if depth < max_depth:
            for edge in kg_store.edges.values():
                next_id = None

                # Outgoing edges
                if "outgoing" in directions and edge.get("source") == node_id:
                    if edge.get("type") in relationship_types:
                        next_id = edge.get("target")

                # Incoming edges
                if "incoming" in directions and edge.get("target") == node_id:
                    if edge.get("type") in relationship_types:
                        next_id = edge.get("source")

                if next_id and next_id not in visited and len(visited) < max_nodes * 3:
                    visited.add(next_id)
                    queue.append((next_id, depth + 1))

    return found


# Common Chinese-to-English satellite name translations
_CHINESE_SAT_NAMES = {
    "實驗": "shiyan",
    "試驗": "shiyan",
    "遥感": "yaogan",
    "中星": "chinasat",
    "北斗": "beidou",
}


def _normalize_sat_name(name: str) -> str:
    """Normalize satellite name for comparison: lowercase, remove hyphens/extra spaces/parens.
    Also translates common Chinese characters to English."""
    import re
    s = str(name).lower().strip()

    # Translate Chinese characters to English
    for cn, en in _CHINESE_SAT_NAMES.items():
        s = s.replace(cn.lower(), en)

    s = re.sub(r'\([^)]*\)', '', s)  # Remove parentheses and content
    s = re.sub(r'[\s\-]+', ' ', s)  # Replace hyphens and multiple spaces with single space
    return s.strip()


def _find_candidate_satellites(sat_id: str, max_candidates: int = 5) -> list:
    """Find candidate satellites based on fuzzy matching. Returns list of (node_id, label, score)."""
    from modules.knowledge_graph.kg_store import kg_store
    from difflib import SequenceMatcher

    sat_id_norm = _normalize_sat_name(sat_id)
    candidates = []

    for n in kg_store.nodes.values():
        if n.get("type") != "Satellite":
            continue

        label = n.get("label", "")
        label_norm = _normalize_sat_name(label)

        # Calculate similarity score
        score = SequenceMatcher(None, sat_id_norm, label_norm).ratio()

        # Also check aliases
        aliases = (n.get("attributes") or {}).get("aliases", {}).get("value") or []
        for alias in aliases:
            alias_norm = _normalize_sat_name(alias)
            alias_score = SequenceMatcher(None, sat_id_norm, alias_norm).ratio()
            if alias_score > score:
                score = alias_score

        if score > 0.5:  # Only candidates above 50% similarity
            candidates.append((n.get("id"), label, score))

    # Sort by score descending
    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates[:max_candidates]


async def _resolve_satellite_id_with_llm_fallback(sat_id: str) -> str | None:
    """Enhanced satellite resolution with LLM fallback for ambiguous cases.

    Three-layer approach:
    1. Exact match (fast)
    2. Fuzzy match with high confidence (instant)
    3. LLM-assisted choice from candidates (slow but accurate for edge cases)
    """
    from modules.knowledge_graph.kg_store import kg_store

    # Layer 1: Direct node ID match
    if sat_id in kg_store.nodes:
        return sat_id

    # Layer 2: NORAD ID lookup
    if str(sat_id).isdigit():
        for n in kg_store.nodes.values():
            nid = str(((n.get("attributes") or {}).get("norad_id") or {}).get("value") or "")
            if nid == sat_id:
                return n.get("id")

    # Layer 3: Exact normalized match (fast)
    sat_id_norm = _normalize_sat_name(sat_id)
    for n in kg_store.nodes.values():
        label_norm = _normalize_sat_name(n.get("label", ""))
        if label_norm == sat_id_norm:
            return n.get("id")

        aliases = (n.get("attributes") or {}).get("aliases", {}).get("value") or []
        for alias in aliases:
            if _normalize_sat_name(alias) == sat_id_norm:
                return n.get("id")

    # Layer 4: Fuzzy match with high confidence (still fast)
    candidates = _find_candidate_satellites(sat_id, max_candidates=1)
    if candidates and candidates[0][2] > 0.85:  # >85% confidence
        return candidates[0][0]

    # Layer 5: LLM-assisted disambiguation (slow, only for ambiguous cases)
    if len(candidates) > 0:
        client = _get_client()
        prompt = f"""Given the satellite query "{sat_id}", which of these candidates is the best match?

Candidates:
{chr(10).join(f"{i+1}. {label}" for i, (_, label, score) in enumerate(candidates))}

Respond with just the number (1-{len(candidates)}) of the best match, or 0 if none match."""

        try:
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=10
            )
            choice = response.choices[0].message.content.strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(candidates):
                    return candidates[idx][0]
        except:
            pass

    # Not found
    return None


def _resolve_satellite_id(sat_id: str) -> str | None:
    """Convert satellite name, KG node ID, or NORAD ID to the canonical satellite identifier.
    Returns the satellite_id (node ID or NORAD ID) for use in event queries, or None if not found.

    Note: For async resolution with LLM fallback, use _resolve_satellite_id_with_llm_fallback()
    """
    from modules.knowledge_graph.kg_store import kg_store

    # Direct node ID match
    if sat_id in kg_store.nodes:
        return sat_id

    # Try NORAD ID lookup
    if str(sat_id).isdigit():
        for n in kg_store.nodes.values():
            nid = str(((n.get("attributes") or {}).get("norad_id") or {}).get("value") or "")
            if nid == sat_id:
                return n.get("id")

    # Normalize the input for flexible matching
    sat_id_norm = _normalize_sat_name(sat_id)

    # Try satellite name/label lookup with normalization
    for n in kg_store.nodes.values():
        label_norm = _normalize_sat_name(n.get("label", ""))
        if label_norm == sat_id_norm:
            return n.get("id")

        # Try matching aliases if they exist
        aliases = (n.get("attributes") or {}).get("aliases", {}).get("value") or []
        for alias in aliases:
            alias_norm = _normalize_sat_name(alias)
            if alias_norm == sat_id_norm:
                return n.get("id")

    # Try partial name matching (e.g., "AZERSPACE-2" matches "AZERSPACE-2 / INTELSAT 38")
    for n in kg_store.nodes.values():
        label = n.get("label", "").lower()
        if sat_id.lower() in label or label.startswith(sat_id.lower()):
            return n.get("id")

    # Try fuzzy match as fallback (high confidence only)
    candidates = _find_candidate_satellites(sat_id, max_candidates=1)
    if candidates and candidates[0][2] > 0.85:
        return candidates[0][0]

    # Not found
    return None


async def _call_tool(name: str, args: dict) -> dict:
    """Execute a tool call and return the result dict."""
    if name == "get_entity_relationships":
        from modules.knowledge_graph.kg_store import kg_store

        entity_id = args.get("entity_id", "").strip()
        if not entity_id:
            return {"error": "entity_id is required"}

        # Resolve entity
        resolved_id = _resolve_satellite_id(entity_id)
        if not resolved_id:
            resolved_id = entity_id  # Try as direct node ID

        node = kg_store.nodes.get(resolved_id)
        if not node:
            return {"error": f"Entity '{entity_id}' not found in knowledge graph"}

        # Scan all edges for this entity
        relationships_by_type = {}
        all_sources = set()

        for edge in kg_store.edges.values():
            related_node = None
            relationship_type = edge.get("label")

            # Check if this edge involves our entity
            if edge.get("source") == resolved_id:
                related_node = kg_store.nodes.get(edge.get("target"))
                direction = "outgoing"
            elif edge.get("target") == resolved_id:
                related_node = kg_store.nodes.get(edge.get("source"))
                direction = "incoming"

            if related_node:
                # Initialize relationship type if not seen
                if relationship_type not in relationships_by_type:
                    relationships_by_type[relationship_type] = []

                # Get source reports for this edge
                sources_info = []
                edge_sources = edge.get("sources") or []
                for src in edge_sources:
                    source_id = src.get("source_id")
                    if source_id and source_id in kg_store.sources:
                        source_data = kg_store.sources[source_id]
                        sources_info.append({
                            "source_id": source_id,
                            "title": source_data.get("title"),
                            "type": source_data.get("type"),
                        })
                        all_sources.add(source_id)

                relationships_by_type[relationship_type].append({
                    "related_entity": related_node.get("label"),
                    "related_entity_type": related_node.get("type"),
                    "direction": direction,
                    "source_reports": sources_info,
                })

        if relationships_by_type:
            return {
                "entity": {
                    "id": resolved_id,
                    "label": node.get("label"),
                    "type": node.get("type")
                },
                "relationship_types": list(relationships_by_type.keys()),
                "relationships": relationships_by_type,
                "total_related_entities": sum(len(v) for v in relationships_by_type.values()),
                "total_source_reports": len(all_sources),
                "source_reports": [
                    {
                        "source_id": sid,
                        "title": kg_store.sources.get(sid, {}).get("title"),
                        "type": kg_store.sources.get(sid, {}).get("type"),
                    }
                    for sid in sorted(all_sources)
                ]
            }
        else:
            return {
                "entity": {
                    "id": resolved_id,
                    "label": node.get("label"),
                    "type": node.get("type")
                },
                "relationship_count": 0,
                "message": f"No relationships found for {node.get('label')}"
            }

    elif name == "search_satellites_by_country":
        from modules.knowledge_graph.kg_store import kg_store

        country_query = args.get("country", "").strip()
        if not country_query:
            return {"error": "country parameter is required"}

        # Collect all available countries first
        available_countries = set()
        satellites = []

        # Satellite types to match (Satellite, CommercialSatellite, MilitarySatellite, etc.)
        satellite_types = {"Satellite", "CommercialSatellite", "MilitarySatellite", "ReconnaissanceSatellite"}

        for node in kg_store.nodes.values():
            node_type = node.get("type", "")
            # Match any satellite type (including subtypes)
            if node_type not in satellite_types and not node_type.endswith("Satellite"):
                continue

            node_country = (node.get("attributes", {}).get("operator_country", {}) or {}).get("value", "")
            if node_country:
                available_countries.add(str(node_country).strip())

                # Check if this satellite matches the query (case-insensitive)
                if node_country.lower() == country_query.lower():
                    satellites.append({
                        "id": node.get("id"),
                        "label": node.get("label"),
                        "norad_id": (node.get("attributes", {}).get("norad_id", {}) or {}).get("value"),
                        "orbit_type": (node.get("attributes", {}).get("orbit_type", {}) or {}).get("value"),
                        "launch_date": (node.get("attributes", {}).get("launch_date", {}) or {}).get("value"),
                        "operator": (node.get("attributes", {}).get("operator", {}) or {}).get("value"),
                    })

        if satellites:
            return {
                "count": len(satellites),
                "country": country_query,
                "satellites": satellites,
            }
        else:
            return {
                "error": f"No satellites found for '{country_query}' in the system.",
                "available_countries": sorted(available_countries),
                "hint": f"Available countries with satellite data: {', '.join(sorted(available_countries))}"
            }

    elif name == "get_satellite_info":
        from modules.knowledge_graph.kg_store import kg_store
        sat_id = args["satellite_id"]
        resolved_id = _resolve_satellite_id(sat_id)
        if not resolved_id:
            return {"error": f"Satellite '{sat_id}' not found in knowledge graph"}
        node = kg_store.nodes.get(resolved_id)
        if not node:
            return {"error": f"Satellite '{sat_id}' not found in knowledge graph"}
        attrs = {k: v.get("value") for k, v in (node.get("attributes") or {}).items()}
        return {"id": node["id"], "label": node.get("label"), "type": node.get("type"), "attributes": attrs}

    elif name == "search_events":
        from modules.events.event_store import event_store

        # Validate event type if provided
        event_type = args.get("type")
        if event_type and event_type.lower() not in SUPPORTED_EVENT_TYPES:
            return {
                "error": f"Event type '{event_type}' is not supported.",
                "supported_types": list(SUPPORTED_EVENT_TYPES),
                "hint": f"Did you mean one of: {', '.join(sorted(SUPPORTED_EVENT_TYPES))}?"
            }

        sat_id = args.get("satellite_id")
        if sat_id:
            sat_id = _resolve_satellite_id(sat_id)
            if not sat_id:
                return {"error": f"Satellite '{args.get('satellite_id')}' not found"}
        events = event_store.query_events(
            event_type=event_type,
            regime=args.get("regime"),
            days=args.get("days"),
            satellite_id=sat_id,
        )

        # Collect source reports referenced by events
        source_reports = {}
        for event in events:
            source_id = event.get("source_id")
            if source_id and source_id not in source_reports:
                source_reports[source_id] = {
                    "source_id": source_id,
                    "report_title": event.get("report_title"),
                }

        # Return ALL events with complete information (no truncation)
        return {
            "count": len(events),
            "event_type": event_type,
            "satellite_id": sat_id,
            "filter_criteria": {
                "type": event_type,
                "regime": args.get("regime"),
                "days": args.get("days"),
                "satellite_id": args.get("satellite_id"),
            },
            "events": events,  # Return ALL events, no limit
            "source_reports": list(source_reports.values()),
        }

    elif name == "search_all_events":
        from modules.events.event_store import event_store

        sat_id = args.get("satellite_id")
        if sat_id:
            sat_id = _resolve_satellite_id(sat_id)
            if not sat_id:
                return {"error": f"Satellite '{args.get('satellite_id')}' not found"}

        # Query all three event types
        all_events = []
        source_reports = {}
        event_type_counts = {}

        for event_type in SUPPORTED_EVENT_TYPES:
            events = event_store.query_events(
                event_type=event_type,
                regime=args.get("regime"),
                days=args.get("days"),
                satellite_id=sat_id,
            )
            all_events.extend(events)
            event_type_counts[event_type] = len(events)

            # Collect source reports
            for event in events:
                source_id = event.get("source_id")
                if source_id and source_id not in source_reports:
                    source_reports[source_id] = {
                        "source_id": source_id,
                        "report_title": event.get("report_title"),
                    }

        # Sort by date (newest first)
        all_events.sort(key=lambda e: e.get("event_date", ""), reverse=True)

        return {
            "count": len(all_events),
            "event_type": "all (maneuver + photometric_change + launch)",
            "satellite_id": sat_id,
            "event_type_breakdown": event_type_counts,
            "filter_criteria": {
                "regime": args.get("regime"),
                "days": args.get("days"),
                "satellite_id": args.get("satellite_id"),
            },
            "events": all_events,  # All events combined and sorted
            "source_reports": list(source_reports.values()),
        }

    elif name == "get_maneuver_history":
        from modules.events.event_store import event_store
        sat_id = _resolve_satellite_id(args["satellite_id"])
        if not sat_id:
            return {"error": f"Satellite '{args['satellite_id']}' not found"}
        events = event_store.query_events(
            event_type="maneuver",
            satellite_id=sat_id,
            days=args.get("days"),
        )
        return {"count": len(events), "maneuvers": events[:30]}

    elif name == "get_coverage":
        from modules.analysis.coverage import compute_passes, passes_summary, REGIONS
        from modules.propagation import tle_store
        norad_id = args["norad_id"]
        region = args.get("region", "taiwan")
        days = args.get("days", 7)
        region_bounds = REGIONS.get(region)
        if not region_bounds:
            return {"error": f"Unknown region '{region}'"}
        sat = tle_store.get(norad_id)
        if not sat:
            return {"error": f"No TLE for NORAD ID {norad_id}"}
        passes = compute_passes(sat.line1, sat.line2, region_bounds, days=days)
        return {"norad_id": norad_id, "region": region, "days": days, "summary": passes_summary(passes, days)}

    elif name == "get_fleet_coverage":
        from modules.analysis.coverage import compute_passes, passes_summary, REGIONS
        from modules.propagation import tle_store
        from modules.knowledge_graph.kg_store import kg_store
        from modules.analysis.coverage import REGIONS

        country = args.get("country", "china")
        region = args.get("region", "taiwan")
        days = args.get("days", 30)
        region_bounds = REGIONS.get(region)
        if not region_bounds:
            return {"error": f"Unknown region '{region}'"}

        # Import coverage helper
        from modules.analysis.satellite_utils import _is_satellite_node, _is_chinese_satellite

        results = []
        for node in kg_store.nodes.values():
            if not _is_satellite_node(node):
                continue
            if country.lower() in ("china", "chinese") and not _is_chinese_satellite(node):
                continue
            attrs = node.get("attributes") or {}
            norad_id = str((attrs.get("norad_id") or {}).get("value") or "").strip()
            if not norad_id or not norad_id.isdigit():
                continue
            sat = tle_store.get(norad_id)
            if not sat:
                continue
            try:
                passes = compute_passes(sat.line1, sat.line2, region_bounds, days=days)
                summary = passes_summary(passes, days)
                results.append({
                    "norad_id": norad_id,
                    "label": node.get("label", norad_id),
                    "node_id": node.get("id", ""),
                    "summary": summary,
                })
            except Exception:
                pass
        results.sort(key=lambda r: r["summary"]["avg_passes_per_day"], reverse=True)
        return {"country": country, "region": region, "days": days, "count": len(results), "top_satellites": results[:10]}

    elif name == "search_report_content":
        from pathlib import Path
        from modules.knowledge_graph.mhtml_reader import read_mhtml

        sat_query = args.get("satellite_name_or_id", "").lower().strip()
        keyword = (args.get("keyword") or "").lower().strip()

        if not sat_query:
            return {"error": "satellite_name_or_id is required"}

        # Use absolute path to be work-directory agnostic
        report_dir = Path(__file__).parents[3] / "data" / "JCO report"
        if not report_dir.exists():
            return {"error": "Report directory not found"}

        results = []
        for mhtml_file in sorted(report_dir.glob("*.mhtml")):
            try:
                text = read_mhtml(mhtml_file)
                if not text:
                    continue

                # Check if satellite appears in this report
                if sat_query not in text.lower():
                    continue

                filename = mhtml_file.name

                # If keyword is specified, find and highlight relevant sections
                if keyword:
                    # Find sections containing both satellite and keyword
                    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
                    relevant_sections = []
                    for para in paragraphs:
                        para_lower = para.lower()
                        if sat_query in para_lower and keyword in para_lower:
                            relevant_sections.append(para)

                    if relevant_sections:
                        results.append({
                            "file": filename,
                            "full_content": text,
                            "matched_sections": relevant_sections,  # Return matching sections (untruncated)
                        })
                else:
                    # No keyword filter - return full content
                    results.append({
                        "file": filename,
                        "full_content": text,
                    })
            except Exception as e:
                pass

        if not results:
            return {"count": 0, "message": f"No reports found for '{sat_query}'" + (f" with keyword '{keyword}'" if keyword else "")}

        return {
            "count": len(results),
            "satellite_query": sat_query,
            "keyword_filter": keyword,
            "results": results
        }

    elif name == "get_report_by_file":
        from pathlib import Path
        from modules.knowledge_graph.mhtml_reader import read_mhtml

        filename = args.get("filename", "").strip()
        if not filename:
            return {"error": "filename is required"}

        # Support both .mhtml and .txt extensions
        if not filename.endswith((".mhtml", ".txt")):
            filename_mhtml = filename if filename.endswith(".mhtml") else filename + ".mhtml"
            filename_txt = filename if filename.endswith(".txt") else filename + ".txt"
        else:
            filename_mhtml = filename if filename.endswith(".mhtml") else filename.replace(".txt", ".mhtml")
            filename_txt = filename if filename.endswith(".txt") else filename.replace(".mhtml", ".txt")

        report_dir = Path(__file__).parents[3] / "data" / "JCO report"
        if not report_dir.exists():
            return {"error": "Report directory not found"}

        # Try to find the file
        file_path = None
        for candidate in [filename_mhtml, filename_txt, filename]:
            potential_path = report_dir / candidate
            if potential_path.exists():
                file_path = potential_path
                break

        if not file_path:
            # Try to search case-insensitively
            for f in report_dir.glob("*"):
                if f.name.lower() == filename.lower():
                    file_path = f
                    break

        if not file_path:
            return {"error": f"Report file '{filename}' not found", "searched_in": str(report_dir)}

        try:
            if file_path.suffix == ".mhtml":
                content = read_mhtml(file_path)
            else:
                content = file_path.read_text(encoding="utf-8")

            if not content:
                return {"error": f"Could not read content from '{filename}'"}

            return {
                "filename": file_path.name,
                "full_content": content,
                "file_size_chars": len(content),
            }
        except Exception as e:
            return {"error": f"Error reading file '{filename}': {str(e)}"}

    elif name == "explore_relationships":
        from modules.knowledge_graph.kg_store import kg_store

        start_node_id = args.get("start_node_id", "")
        target_info = args.get("target_info", "")
        max_depth = min(args.get("max_depth", 2), 3)  # Clamp to 1-3

        # Resolve start node
        resolved_start = _resolve_satellite_id(start_node_id)
        if resolved_start:
            start_node_id = resolved_start

        start_node = kg_store.nodes.get(start_node_id)
        if not start_node:
            return {"error": f"Node '{start_node_id}' not found in knowledge graph"}

        # Understand target using LLM
        understanding = await _understand_target_info(target_info)

        # Traverse graph
        found_nodes = await _bfs_traverse(start_node_id, understanding, max_depth)

        # Format results
        result_list = []
        for node in found_nodes:
            attrs = {k: v.get("value") for k, v in (node.get("attributes") or {}).items()}
            result_list.append({
                "id": node.get("id"),
                "label": node.get("label"),
                "type": node.get("type"),
                "attributes": attrs
            })

        return {
            "start_node": {
                "id": start_node.get("id"),
                "label": start_node.get("label"),
                "type": start_node.get("type")
            },
            "target_type": understanding.get("target_type"),
            "found_count": len(result_list),
            "found_nodes": result_list,
            "relationships": understanding.get("relationship_types"),
            "traversal_depth_used": max_depth,
            "message": f"Found {len(result_list)} {understanding.get('target_type', 'entities')} through {', '.join(understanding.get('relationship_types', []))} relationships"
        }

    elif name == "get_node_info":
        from modules.knowledge_graph.kg_store import kg_store

        node_id = args.get("node_id", "").strip()
        if not node_id:
            return {"error": "node_id is required"}

        # Try to resolve if it's a satellite name/ID
        resolved_id = _resolve_satellite_id(node_id)
        if resolved_id:
            node_id = resolved_id

        # Try to find the node in KG
        node = kg_store.nodes.get(node_id)
        if not node:
            return {"error": f"Node '{node_id}' not found in knowledge graph"}

        # Extract and format node information
        attrs = {}
        for k, v in (node.get("attributes") or {}).items():
            if isinstance(v, dict):
                attrs[k] = v.get("value")
            else:
                attrs[k] = v

        return {
            "id": node.get("id"),
            "label": node.get("label"),
            "type": node.get("type"),
            "attributes": attrs,
            "message": f"Retrieved {node.get('type')} node: {node.get('label')}"
        }

    return {"error": f"Unknown tool: {name}"}


async def _create_tool_plan(question: str) -> tuple[list[str], bool, str]:
    """Let LLM analyze the question and create a tool usage plan.

    Returns:
        (plan, success, message)
        - plan: list of tool names to use
        - success: True if LLM planning succeeded, False if fallback was used
        - message: explanation of what happened
    """
    client = _get_client()

    # Build tool list description
    tool_descriptions = []
    for tool_def in _TOOL_SCHEMAS:
        fn = tool_def["function"]
        tool_descriptions.append(f"- {fn['name']}: {fn['description']}")

    tools_text = "\n".join(tool_descriptions)

    prompt = f"""You are an SSA (Space Situational Awareness) analyst. Analyze this question and create a COMPREHENSIVE tool usage plan.

Question: {question}

Available tools:
{tools_text}

IMPORTANT: Your job is to identify ALL the tools needed to fully answer this question. Don't stop at just one tool!

For this question, break it down:
1. What entities/filters are mentioned? (country, satellite name, region, time period, etc.)
2. What information is needed?
   - Event data? → search_all_events or search_events
   - Specific satellite? → search_satellites_by_country or get_satellite_info
   - Relationships? → get_entity_relationships
   - Original report details? → search_report_content
   - Coverage info? → get_coverage or get_fleet_coverage
3. What's the logical execution order?
4. Do we need multiple tools in sequence? (VERY COMMON - don't default to just one!)

Examples of good multi-tool plans:
- "Russia satellites events" → [search_satellites_by_country, search_all_events]
- "SJ-20 activity" → [search_all_events, get_entity_relationships, search_report_content]
- "Taiwan coverage" → [search_satellites_by_country, get_coverage, get_fleet_coverage]

Return ONLY a JSON list of tool names in order: ["tool1", "tool2", "tool3"]
Must be valid JSON. Aim for 2-4 tools for most questions."""

    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500
        )

        plan_text = response.choices[0].message.content.strip()

        # Try to extract JSON from markdown code blocks if present
        if "```json" in plan_text:
            plan_text = plan_text.split("```json")[1].split("```")[0].strip()
        elif "```" in plan_text:
            plan_text = plan_text.split("```")[1].split("```")[0].strip()

        # Debug: log the raw response
        import sys
        print(f"[PLANNING DEBUG] Raw response: {repr(plan_text[:200])}", file=sys.stderr)

        if not plan_text:
            return None, False, "LLM returned empty response"

        plan = json.loads(plan_text)

        if isinstance(plan, list) and len(plan) > 0 and all(isinstance(x, str) for x in plan):
            return plan, True, "LLM planning successful"
        else:
            return None, False, f"LLM returned invalid plan format: {plan}"
    except json.JSONDecodeError as e:
        return None, False, f"LLM response is not valid JSON: {str(e)}"
    except Exception as e:
        return None, False, f"LLM planning failed: {str(e)}"

    # Fallback: intelligent default plans based on question keywords
    q_lower = question.lower()

    # Check for country/region mentions
    has_country = any(word in q_lower for word in ["china", "russia", "usa", "pakistan", "azerbaijan",
                                                      "中国", "俄罗斯", "美国", "巴基斯坦"])
    has_region = any(word in q_lower for word in ["taiwan", "台湾", "south china sea", "南海",
                                                    "east china sea", "东海", "coverage", "覆蓋"])
    has_event = any(word in q_lower for word in ["event", "happen", "activity", "動態", "事件", "maneuver", "機動"])
    has_relationship = any(word in q_lower for word in ["relationship", "relate", "connect", "關係", "orbit", "軌道"])

    # Build plan based on combinations
    plan = []
    reason = ""

    # Step 1: If asking about a specific country's satellites + events
    if has_country and has_event:
        plan = ["search_satellites_by_country", "search_all_events"]
        reason = "Detected country + events → search satellites then events"
    # Step 2: If asking about coverage/activity in a region
    elif has_region and (has_event or has_country):
        plan = ["search_satellites_by_country", "get_fleet_coverage", "search_all_events"]
        reason = "Detected region + activity → search satellites, coverage, and events"
    # Step 3: If asking about events generally
    elif has_event:
        plan = ["search_all_events"]
        reason = "Detected event-focused question"
    # Step 4: If asking about relationships
    elif has_relationship:
        plan = ["get_entity_relationships", "search_all_events"]
        reason = "Detected relationship-focused question"
    # Step 5: If asking about satellites
    elif has_country:
        plan = ["search_satellites_by_country", "get_entity_relationships"]
        reason = "Detected country-specific satellite question"
    # Default: comprehensive approach
    else:
        plan = ["search_all_events", "get_entity_relationships"]
        reason = "No specific keywords detected → using comprehensive approach"

    return plan, False, f"Using fallback: {reason}"


async def run_qa(
    question: str,
    satellite_id: str | None = None,
    history: list[dict] | None = None,
    on_tool_call = None  # Optional callback: on_tool_call(tool_name, args)
) -> dict:
    """Run the agentic Q&A loop with multi-turn conversation support.

    Args:
        question: Current user question
        satellite_id: Optional KG node ID of selected satellite for context
        history: Previous conversation turns (list of {role, content} dicts)
        on_tool_call: Optional callback function(tool_name, args) called before each tool invocation

    Returns:
        {answer, steps, iterations, ...}
    """
    client = _get_client()

    context = ""
    if satellite_id:
        context = f"\n\nContext: the user is currently viewing satellite with ID '{satellite_id}'."

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
    ]

    # Add conversation history (only assistant answers, not reasoning steps)
    if history:
        for msg in history:
            # msg is a HistoryMessage Pydantic model, use attribute access
            role = msg.role if hasattr(msg, "role") else msg.get("role", "user")
            content = msg.content if hasattr(msg, "content") else msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    # Add current question
    messages.append({"role": "user", "content": question + context})

    # PLANNING STEP: Let LLM create a tool usage plan
    tool_plan, plan_success, plan_message = await _create_tool_plan(question)

    steps: list[dict] = []
    steps.append({
        "tool": "PLANNING",
        "args": {"question": question},
        "result": {
            "plan": tool_plan,
            "success": plan_success,
            "message": plan_message
        }
    })

    # Add plan to messages so Agent can see it
    if tool_plan:
        plan_instruction = f"""ANALYSIS PLAN for this question:
Based on the question analysis, you should call these tools IN ORDER to comprehensively answer:
{', '.join(tool_plan)}

Execute these tools in sequence to gather all necessary information."""
        messages.append({"role": "assistant", "content": plan_instruction})

    MAX_ITER = 8

    for iteration in range(MAX_ITER):
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            tools=_TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0,
        )

        msg = response.choices[0].message

        # If no tool calls, we have the final answer
        if not msg.tool_calls:
            return {
                "answer": msg.content or "",
                "steps": steps,
                "iterations": iteration + 1,
            }

        # Process all tool calls in this turn
        tool_results = []
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            # Notify callback before tool call (support both sync and async)
            if on_tool_call:
                import inspect
                if inspect.iscoroutinefunction(on_tool_call):
                    await on_tool_call(fn_name, fn_args)
                else:
                    on_tool_call(fn_name, fn_args)

            result = await _call_tool(fn_name, fn_args)
            steps.append({"tool": fn_name, "args": fn_args, "result": result})
            tool_results.append({
                "tool_call_id": tc.id,
                "role": "tool",
                "content": json.dumps(result, default=str),
            })

        # Append assistant message with tool_calls, then all tool results
        messages.append(msg)
        messages.extend(tool_results)

    # Exhausted iterations — ask for a final answer without tools
    messages.append({"role": "user", "content": "Please summarize what you've found so far."})
    final = await client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0,
    )
    return {
        "answer": final.choices[0].message.content or "",
        "steps": steps,
        "iterations": MAX_ITER,
        "warning": "Max iterations reached",
    }
