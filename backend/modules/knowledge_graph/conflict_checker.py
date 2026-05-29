"""
ConflictChecker: detects duplicate, compatible, and contradictory facts.
"""
import json
import os
from typing import Literal

from openai import AsyncOpenAI

ConflictResult = Literal["compatible", "contradiction", "duplicate", "update"]

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


def is_exact_duplicate(edge_a: dict, edge_b: dict) -> bool:
    """True if both edges have same source, predicate, object — same fact, same source."""
    return (
        edge_a["source"] == edge_b["source"]
        and edge_a["label"] == edge_b["label"]
        and edge_a["target"] == edge_b["target"]
        and any(
            s["source_id"] == t["source_id"]
            for s in edge_a.get("sources", [])
            for t in edge_b.get("sources", [])
        )
    )


async def assess_conflict(
    new_edge: dict,
    existing_edge: dict,
    schema,
    source_a_meta: dict,
    source_b_meta: dict,
) -> tuple[ConflictResult, str]:
    """
    Assess whether two edges with same subject+predicate but different objects conflict.
    Returns (result, llm_reasoning).
    """
    rel_types = schema.get_relationship_types()
    rel_info = rel_types.get(new_edge["label"], {})

    prompt = f"""You are analyzing two knowledge graph statements about space entities.

Relationship type: {new_edge['label']}
Schema definition: domain={rel_info.get('domain', [])}, range={rel_info.get('range', [])}

Statement A (from: {source_a_meta.get('title', '?')}, date: {source_a_meta.get('date', '?')}):
  {existing_edge['source']} --[{existing_edge['label']}]--> {existing_edge['target']}

Statement B (from: {source_b_meta.get('title', '?')}, date: {source_b_meta.get('date', '?')}):
  {new_edge['source']} --[{new_edge['label']}]--> {new_edge['target']}

Determine the relationship between these two statements:
- "compatible": both can be simultaneously true (e.g., ISS is operated by both NASA and Roscosmos)
- "contradiction": logically incompatible (e.g., two different launch dates for the same satellite)
- "duplicate": same fact expressed differently (e.g., "NASA operates ISS" ≡ "ISS operatedBy NASA" with different entity labels that refer to the same thing)

Return JSON: {{"result": "compatible"|"contradiction"|"duplicate", "reasoning": "one sentence explanation"}}"""

    try:
        response = await _get_client().chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = json.loads(response.choices[0].message.content)
        return raw.get("result", "compatible"), raw.get("reasoning", "")
    except Exception as e:
        print(f"[conflict_checker] edge conflict assessment error: {e}")
        return "compatible", f"Error during assessment: {e}"


async def assess_attribute_conflict(
    entity_id: str,
    field: str,
    field_meta: dict,
    old_val: object,
    old_date: str | None,
    old_source_title: str,
    new_val: object,
    new_date: str | None,
    new_source_title: str,
) -> tuple[ConflictResult, str]:
    """
    Assess whether a new attribute value conflicts with an existing one.
    Returns (result, llm_reasoning).
    """
    prompt = f"""You are analyzing two attribute values for the same entity in a space situational awareness knowledge graph.

Entity ID: {entity_id}
Attribute: {field}
Attribute description: {field_meta.get('description', 'no description')}
Attribute type: {field_meta.get('type', 'string')}

Existing value: "{old_val}" (event_date: {old_date}, source: {old_source_title})
New value: "{new_val}" (event_date: {new_date}, source: {new_source_title})

Determine:
- "update": new value supersedes old (e.g., altitude changed after reboost, newer source is more accurate)
- "contradiction": factually incompatible, a human should decide (e.g., conflicting launch dates)
- "duplicate": same value expressed differently ("United States" ≡ "USA")

Return JSON: {{"result": "update"|"contradiction"|"duplicate", "reasoning": "one sentence explanation"}}"""

    try:
        response = await _get_client().chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = json.loads(response.choices[0].message.content)
        return raw.get("result", "contradiction"), raw.get("reasoning", "")
    except Exception as e:
        print(f"[conflict_checker] attribute conflict assessment error: {e}")
        return "contradiction", f"Error during assessment: {e}"
