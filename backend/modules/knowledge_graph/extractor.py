"""
Extractor: GPT-4o entity/relation extraction from text documents.
"""
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


@dataclass
class AttributeValue:
    value: Any
    event_date: str | None
    source_id: str | None


@dataclass
class EntityProposal:
    id: str | None  # non-null if LLM matched existing node
    label: str
    type: str
    inferred_types: list[str] = field(default_factory=list)
    attributes: dict[str, AttributeValue] = field(default_factory=dict)
    excerpt: str = ""
    schema_status: str = "confirmed"  # "confirmed" | "proposed"
    proposed_type_info: dict | None = None


@dataclass
class RelationProposal:
    subject_label: str
    predicate: str
    object_label: str
    excerpt: str = ""
    subject_id: str | None = None
    object_id: str | None = None


@dataclass
class ExtractionResult:
    entities: list[EntityProposal] = field(default_factory=list)
    relations: list[RelationProposal] = field(default_factory=list)
    event_date: str | None = None
    event_date_approximate: bool = False
    truncated: bool = False
    original_length: int = 0


def _preprocess_text(text: str) -> str:
    """Strip Wikipedia boilerplate and truncate before sending to LLM.

    Strategy:
    1. Cut at the Wikipedia reference block — 3+ consecutive lines starting with
       '^ ' mark the footnote section. Everything from there on is references and
       navboxes (noise for extraction).
    2. Strip any remaining navbox lines (lines dense with separator characters or
       lines that are just space-separated short name tokens with no sentence structure).
    3. Hard-cap at 12000 chars (article body is always first).
    """
    lines = text.splitlines()

    # Pass 1: find and cut at the Wikipedia footnote/reference block
    ref_run = 0
    cut_index = len(lines)
    for i, line in enumerate(lines):
        if line.strip().startswith('^ '):
            ref_run += 1
            if ref_run >= 3:
                cut_index = i - (ref_run - 1)
                break
        else:
            ref_run = 0
    lines = lines[:cut_index]

    # Pass 2: strip navbox-style lines (separator-dense or pure name lists)
    cleaned = []
    nav_run = 0
    for line in lines:
        s = line.strip()
        sep_count = s.count('·') + s.count('•') + s.count('、') + s.count(' · ')
        comma_count = s.count(',') + s.count('，')
        # Space-separated name-list heuristic: many tokens, all short, no sentence-ending chars
        tokens = s.split()
        all_short_tokens = len(tokens) >= 5 and all(len(t) <= 12 for t in tokens) and not re.search(r'[.。!！?？]', s)
        is_navbox = len(s) < 200 and (
            sep_count >= 3
            or (comma_count >= 4 and len(s) < 100)
            or all_short_tokens
        )
        if is_navbox:
            nav_run += 1
            if nav_run > 2:
                continue
        else:
            nav_run = 0
        cleaned.append(line)

    result = '\n'.join(cleaned)
    return result[:12000], len(result) > 12000


_SYSTEM_PROMPT_TEMPLATE = """You are a knowledge graph extraction system for space situational awareness.

Given a document, extract entities and relationships and return them as JSON.

{schema_context}

=== EXISTING ENTITIES IN KNOWLEDGE GRAPH ===
{existing_labels}

=== EXTRACTION RULES ===
1. Extract all meaningful entities (satellites, organizations, missions, people, documents).
2. For each entity, populate ALL attributes defined in the schema for that type. Set to null if not found — do NOT hallucinate values.
3. ENTITY MATCHING — before creating a new entity, always check if it already exists in the knowledge graph:
   a. EXACT / NORMALIZED MATCH: obvious same-name entities → always match (set id to existing id).
   b. OCR AND TYPO VARIANTS: common character confusions are digit zero (0) vs letter O, digit one (1) vs letter I or l, digit five (5) vs letter S, doubled/missing letters (CZZ-2 vs CZ-2). Use the surrounding source text as context to resolve ambiguity — if "CZZ-2" appears in a sentence about a Chinese launch from Jiuquan, it is clearly a typo for "Long March 2 / CZ-2". If "PRSC-EO3" appears in a document that consistently describes PRSC-E03, match it to the existing PRSC-E03 entity. → Match to the existing entity and set its id.
   c. CROSS-LANGUAGE AND ABBREVIATION ALIASES — known equivalences you must apply:
      - Launch vehicles: "CZ-X", "LM-X", "长征X", "Chang Zheng X" all normalize to "Long March X" (already enforced by rule 6, but also apply here for matching).
      - Satellite programs: "COSMIC-2" and "FORMOSAT-7" refer to the same constellation.
      - Organizations: "CASC" = "China Aerospace Science and Technology Corporation", "CNSA" = "China National Space Administration". Apply the same principle to other well-known space industry abbreviations.
      → Match to the existing canonical entity and set its id.
   d. DIFFERENT-NUMBERED ENTRIES IN A SERIES: "FORMOSAT-5" and "FORMOSAT-7" are DIFFERENT satellites, "Yaogan-19" and "Yaogan-20" are different satellites. Only match when you are confident the names refer to the SAME single object.
   e. UNCERTAINTY: if after reading the full source text you are still unsure whether a new name matches an existing entity, leave "id" as null. The human reviewer will handle it. Do NOT guess.
4. If two entity names clearly refer to the same entity, use the existing entity's id. When in doubt, leave "id" as null.
5. TWO-LEVEL SATELLITE HIERARCHY — apply these rules whenever satellites appear:
   a. CONSTELLATION (SatelliteConstellation): A group of satellites that work together as one system (e.g. Starlink, BeiDou, GPS, Tianqi/天启, FORMOSAT-7/COSMIC-2, OneWeb). Extract ONE SatelliteConstellation node for the program AND individual Satellite nodes for each named/numbered member. Link each Satellite to the constellation with a "memberOfConstellation" relation.
   b. SERIES (SatelliteSeries): A lineage of independently-operating satellites sharing a program name but NOT coordinated as a system (e.g. Yaogan, Cosmos, Fengyun, LandSat). Extract ONE SatelliteSeries node for the program AND individual Satellite nodes (Yaogan-19, Yaogan-20, …). Link each Satellite to the series with a "memberOfSeries" relation.
   c. INDIVIDUAL SATELLITE (Satellite): A single spacecraft. Always extract a specific numbered satellite (Tianqi-37, Yaogan-19) as a Satellite node, never collapse it into the constellation/series node.
   d. BATCH LAUNCHES: When text describes launching a numbered batch (e.g. "06组卫星（37星至40星）共4颗", "satellites 37 to 40", "a batch of 6 satellites"), extract EACH satellite as a separate Satellite node with sequential labels (Tianqi-37, Tianqi-38, …). All members share the same launch_date, orbit, and launch_vehicle from context. Add a "memberOfConstellation" or "memberOfSeries" relation for each.
   e. Do NOT create a Satellite node for a constellation or series name alone (e.g. "Tianqi" by itself is a SatelliteConstellation, not a Satellite).
6. THREE-LEVEL LAUNCH VEHICLE HIERARCHY — apply whenever a launch vehicle is mentioned:
   a. FAMILY (LaunchVehicleFamily): The top-level family. Extract ONE node per family.
      - All Chinese aliases map to ONE family node labeled "Long March":
        "LM", "CZ", "CZ-", "长征", "Chang Zheng", "Long March" → label: "Long March"
      - Other families: "Falcon" (SpaceX), "Soyuz" (Roscosmos/RSC Energia), "Ariane" (ArianeGroup), "PSLV" (ISRO), etc.
   b. SERIES (LaunchVehicleSeries): The numbered sub-series within a family. Extract ONE node per series.
      - "LM-2", "CZ-2", "Long March 2" → label: "Long March 2"
      - "LM-6", "CZ-6", "Long March 6" → label: "Long March 6"
      - "Falcon 9" is its own series within the "Falcon" family.
      - Link each series to its family with a memberOfFamily relation.
   c. VARIANT (LaunchVehicle): The specific rocket variant being flown. Extract ONE node per variant.
      - "LM-2D", "CZ-2D", "Long March 2D" → label: "Long March 2D"
      - "LM-2C", "CZ-2C" → label: "Long March 2C"
      - "LM-6A", "CZ-6A" → label: "Long March 6A"
      - Link each variant to its series with a variantOfSeries relation.
   d. ALWAYS create all three levels when a variant is mentioned, even if only the variant name appears in text.
      E.g., text says "launched on a CZ-2D" → extract: Long March (family) + Long March 2 (series) + Long March 2D (variant) with memberOfFamily and variantOfSeries edges.
   e. Use the satellite's carriedBy relation to link to the VARIANT node (LaunchVehicle), NOT the series or family.
   f. Normalize all labels to English "Long March N[letter]" form regardless of how the source writes it.
   g. Do NOT collapse levels: "Long March 2D launched two satellites" still requires all three hierarchy nodes.
   h. NEVER add launch vehicle information as a string attribute on the Satellite node. There is no "launch_vehicle" or "launch_vehicle_name" attribute — always use the carriedBy relationship + hierarchy nodes instead.
7. LAUNCH SITE DETECTION — when a named launch site or launch center is mentioned:
   a. Extract a LaunchSite node. Canonical labels for common Chinese facilities:
      - 酒泉 / Jiuquan / JSLC / Shuang Cheng Zi → "Jiuquan Satellite Launch Center"
      - 西昌 / Xichang / XSLC                   → "Xichang Satellite Launch Center"
      - 太原 / Taiyuan / TSLC                   → "Taiyuan Satellite Launch Center"
      - 文昌 / Wenchang / WSLC                  → "Wenchang Space Launch Site"
      - Other sites: use the name as written in the source.
   b. Link the launched satellite or mission to the site with a launchedFrom relation.
   c. If an operating organization is mentioned alongside the site, add an operatesLaunchSite relation.
   d. Do NOT create a LaunchSite node if only a country is named ("launched in China") — a specific facility name is required.
8. PAIR SECTION EXTRACTION — JCO/NOTOS reports often contain pipe-delimited intelligence summaries formatted as:
   `NORAD | Name (designation) | Orbit | Operator (Country) | Status | Users | Mission | Launch date | Intel description | Propulsion | ...`
   Or narrative paragraphs beginning with "PAI suggests..." or "According to PAI...".
   When you encounter these sections, extract ALL of the following Satellite attributes if present:
   - `status`: the operational status field (e.g. "Active / Manoeuverable")
   - `maneuverable`: "Yes" if "Manoeuverable" or "Yes, maneuverable" appears; "No" if explicitly stated not maneuverable; else "Unknown"
   - `propulsion_type`: the propulsion field (e.g. "Chemical bipropellant", "On-board Propulsion / Unknown", "Hydrazine")
   - `designation`: the platform/bus designation in parentheses after the name (e.g. "14F166A" from "COSMOS 2589 (14F166A)")
   - `intel_description`: the free-text intelligence assessment (e.g. "Russian military satellite. Suspected to have satellite inspection or 'satellite killing' capabilities.")
   - `mission`: the mission/purpose field if more specific than already recorded
   - `operator`: the operator field (e.g. "Russian Ministry of Defence - VKS (MORF)")
   Also extract any associated satellites mentioned (e.g. "COSMOS 2590" in the same row) as separate Satellite entities and link with appropriate relations.
9. COUNTRY NODES — when a satellite's operating country is mentioned:
   a. Extract a Country node with its canonical English name (e.g. "China", "USA", "Russia").
   b. Link the satellite to the country with an "operatingCountry" relation.
   c. Use consistent canonical names: "China" (not PRC), "USA" (not United States), "Russia" (not Russian Federation).
   d. Do NOT extract Country nodes for countries only mentioned in passing — only when directly tied to a satellite as its operator country.
10. If no schema type fits an entity, propose a new type: set "schema_status": "proposed" and include "proposed_type_info": {{"suggested_parent": "...", "suggested_attributes": [...], "reason": "..."}}.
11. For each relation, use ONLY the relationship types listed in the schema.
12. "excerpt" must be the EXACT verbatim sentence(s) from the text that support the extraction. If you cannot find a verbatim excerpt, do NOT extract that fact.
13. Try to extract the real-world event_date for each entity/relation (e.g., when a satellite was launched, when a maneuver occurred). Use ISO date format (YYYY-MM-DD or YYYY-MM-DDThh:mm:ssZ).
14. At the top level, include "event_date" (the most relevant date in the document, e.g., article publication date or main event date) and "event_date_approximate" (true if the date is estimated).
15. CRITICAL: Only extract facts EXPLICITLY stated in the document text. Do NOT use your training knowledge to fill in missing facts. If a piece of information (e.g., launch vehicle, manufacturer) is not clearly stated in the text, leave it null. An entity appearing only in a navigation list (without context) should NOT be extracted with inferred attributes.

Return ONLY valid JSON in this exact structure:
{{
  "event_date": "YYYY-MM-DD or null",
  "event_date_approximate": false,
  "entities": [
    {{
      "id": "existing_id_or_null",
      "label": "Entity Name",
      "type": "SchemaType",
      "schema_status": "confirmed",
      "attributes": {{
        "attr_name": {{"value": "...", "event_date": "YYYY-MM-DD or null"}}
      }},
      "excerpt": "verbatim sentence from text"
    }}
  ],
  "relations": [
    {{
      "subject": "Subject Label",
      "predicate": "relationshipType",
      "object": "Object Label",
      "excerpt": "verbatim sentence from text"
    }}
  ]
}}"""


async def extract_from_text(
    text: str,
    source: dict,
    schema,
    kg_store,
) -> ExtractionResult:
    """Call GPT-4o to extract entities and relations from text."""
    original_length = len(text)
    text, truncated = _preprocess_text(text)
    existing_labels = kg_store.get_existing_labels()
    labels_str = "\n".join(f"  - {label} (id: {nid})" for label, nid in existing_labels.items()) or "  (none yet)"

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        schema_context=schema.as_prompt_context(),
        existing_labels=labels_str,
    )

    source_date = source.get("date") or source.get("published_at", "")
    user_message = f"Source: {source.get('title', 'Unknown')} ({source.get('news_site', source.get('type', 'document'))}, {source_date})\n\n{text}"

    try:
        response = await _get_client().chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
        )
        raw = json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"[extractor] GPT-4o error: {e}")
        return ExtractionResult()

    source_id = source.get("source_id", "")
    result = ExtractionResult(
        event_date=raw.get("event_date"),
        event_date_approximate=raw.get("event_date_approximate", False),
        truncated=truncated,
        original_length=original_length,
    )

    for ent in raw.get("entities", []):
        attrs = {}
        for attr_name, attr_val in (ent.get("attributes") or {}).items():
            if isinstance(attr_val, dict):
                attrs[attr_name] = AttributeValue(
                    value=attr_val.get("value"),
                    event_date=attr_val.get("event_date") or raw.get("event_date"),
                    source_id=source_id,
                )
            else:
                attrs[attr_name] = AttributeValue(value=attr_val, event_date=raw.get("event_date"), source_id=source_id)

        type_name = ent.get("type", "Entity")
        inferred = schema.get_ancestors(type_name) if schema.is_valid_type(type_name) else []

        ep = EntityProposal(
            id=ent.get("id"),
            label=ent.get("label", ""),
            type=type_name,
            inferred_types=inferred,
            attributes=attrs,
            excerpt=ent.get("excerpt", ""),
            schema_status=ent.get("schema_status", "confirmed"),
            proposed_type_info=ent.get("proposed_type_info"),
        )
        result.entities.append(ep)

    for rel in raw.get("relations", []):
        rp = RelationProposal(
            subject_label=rel.get("subject", ""),
            predicate=rel.get("predicate", ""),
            object_label=rel.get("object", ""),
            excerpt=rel.get("excerpt", ""),
        )
        result.relations.append(rp)

    return result
