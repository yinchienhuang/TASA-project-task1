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


_SYSTEM_PROMPT = """You are an SSA (Space Situational Awareness) analyst assistant. Answer questions about satellite maneuvers, orbital patterns, coverage, and related intelligence.

Use the provided tools to retrieve structured data. Chain multiple tool calls as needed to fully answer complex questions. Stop calling tools once you have enough information to give a confident answer.

Rules:
- Always cite the source data behind your answer (which tool was called, what it returned).
- If data is insufficient for a confident answer, say so explicitly.
- For numeric values, include units and round to 2 decimal places.
- Be concise but complete. Use bullet points for lists.
- Today's date: """ + datetime.now(timezone.utc).strftime("%Y-%m-%d") + """

Available named regions for coverage analysis: taiwan, south_china_sea, east_china_sea, korean_peninsula, persian_gulf, ukraine."""

_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_satellite_info",
            "description": "Get KG metadata for a satellite: label, type, operator, orbital params, mission info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "satellite_id": {"type": "string", "description": "KG node ID or NORAD ID"}
                },
                "required": ["satellite_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_events",
            "description": "Fleet-level search across all satellite events. Returns matching events sorted newest first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Event type filter: maneuver | launch | photometric_change"},
                    "regime": {"type": "string", "description": "Orbital regime filter: LEO | MEO | GEO | HEO"},
                    "days": {"type": "integer", "description": "Limit to events in the past N days"},
                    "satellite_id": {"type": "string", "description": "Filter by satellite KG node ID or NORAD ID"},
                },
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
                    "satellite_id": {"type": "string", "description": "KG node ID or NORAD ID"},
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
]


async def _call_tool(name: str, args: dict) -> dict:
    """Execute a tool call and return the result dict."""
    if name == "get_satellite_info":
        from modules.knowledge_graph.kg_store import kg_store
        sat_id = args["satellite_id"]
        node = kg_store.nodes.get(sat_id)
        if not node:
            # Try NORAD ID lookup
            for n in kg_store.nodes.values():
                nid = str(((n.get("attributes") or {}).get("norad_id") or {}).get("value") or "")
                if nid == sat_id:
                    node = n
                    break
        if not node:
            return {"error": f"Satellite {sat_id} not found in knowledge graph"}
        attrs = {k: v.get("value") for k, v in (node.get("attributes") or {}).items()}
        return {"id": node["id"], "label": node.get("label"), "type": node.get("type"), "attributes": attrs}

    elif name == "search_events":
        from modules.events.event_store import event_store
        events = event_store.query_events(
            event_type=args.get("type"),
            regime=args.get("regime"),
            days=args.get("days"),
            satellite_id=args.get("satellite_id"),
        )
        # Trim to 20 events to keep context manageable
        return {"count": len(events), "events": events[:20]}

    elif name == "get_maneuver_history":
        from modules.events.event_store import event_store
        events = event_store.query_events(
            event_type="maneuver",
            satellite_id=args["satellite_id"],
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
        from api.routes_analysis import _is_satellite_node, _is_chinese_satellite

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

    return {"error": f"Unknown tool: {name}"}


async def run_qa(question: str, satellite_id: str | None = None) -> dict:
    """Run the agentic Q&A loop. Returns {answer, steps, iterations}."""
    client = _get_client()

    context = ""
    if satellite_id:
        context = f"\n\nContext: the user is currently viewing satellite with ID '{satellite_id}'."

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": question + context},
    ]

    steps: list[dict] = []
    MAX_ITER = 8

    for iteration in range(MAX_ITER):
        response = await client.chat.completions.create(
            model="gpt-4o",
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
