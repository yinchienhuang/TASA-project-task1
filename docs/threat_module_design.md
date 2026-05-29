# Threat Module — Design & Implementation Plan

## Context

The system has a KG of satellites/organizations/missions with orbital mechanics (SGP4), event history (maneuvers, photometric changes, launches), and coverage analysis. This plan designs a **Threat Scoring Module** using a three-layer architecture:

**Truth Data → Capability Assessment → Threat Assessment**

The capability layer decouples "what can this satellite physically do?" from "how threatening is that given who operates it?" — making the reasoning chain transparent and auditable.

---

## Existing Architecture (relevant)

| Component | File | Key facts |
|---|---|---|
| KG store | `backend/modules/knowledge_graph/kg_store.py` | `nodes`, `edges`; `get_subgraph(node_id, hops)` already exists |
| Schema | `data/schema/schema.yaml` | Satellite (Civil/Military/Commercial), Organization (SpaceAgency/Company/MilitaryUnit), SatelliteConstellation, SatelliteSeries |
| Relationship types | `data/schema/schema.yaml` | `operatedBy`, `manufacturedBy`, `carriedBy`, `memberOfConstellation`, `contractedWith`, `partneredWith`, `builtBy` |
| Event store | `backend/modules/events/event_store.py` | `query_events()`; events have `delta_v`, `period_change`, `maneuver_type`, `regime`, `discrepancy_flag` |
| Coverage | `backend/modules/analysis/coverage.py` | `compute_passes()` → passes; `passes_summary()` → avg_passes_per_day, revisit_interval_hours |
| Analysis routes | `backend/api/routes_analysis.py` | `/api/analysis/coverage/{norad_id}`, `/api/analysis/query` (GPT-4o Q&A) |
| Q&A engine | `backend/modules/analysis/qa_engine.py` | 5 tools: get_satellite_info, search_events, get_maneuver_history, get_coverage, get_fleet_coverage |

---

## Layer Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  LAYER 1 — TRUTH DATA (existing)                             │
│  KG nodes/edges · Event history · TLE/orbital mechanics      │
│  Coverage passes · OSINT attributes                          │
└────────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  LAYER 2 — CAPABILITY ASSESSMENT (new)                       │
│  What can this satellite physically do?                      │
│  Independent of intent or actor                              │
│  Output: CapabilityProfile (ISR / Propulsion / Persistence)  │
└────────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  LAYER 3 — THREAT ASSESSMENT (new)                           │
│  Rules: KG graph traversal (who operates it?)                │
│  LLM: organizational context augmentation (narrow scope)     │
│  Output: ThreatAssessment — score + level + narrative        │
└──────────────────────────────────────────────────────────────┘
```

---

## Layer 2 — Capability Assessment

### CapabilityProfile output

```python
@dataclass
class CapabilityProfile:
    satellite_id: str
    assessed_at: str

    # ISR / Surveillance
    isr_score: float          # 0–1
    isr_orbit_optimal: bool   # SSO at 250–600 km
    ground_resolution_class: str   # "sub-meter possible" / "1–3m" / "3–10m" / ">10m"
    revisit_rate_daily: float | None   # avg passes/day over high-value regions

    # Propulsion / Maneuver
    propulsion_score: float   # 0–1
    total_delta_v_obs: float  # m/s cumulative
    max_single_delta_v: float # m/s largest single burn
    incl_change_count: int    # plane changes observed
    maneuver_frequency: float # maneuvers per month
    stealth_burn_count: int   # events with discrepancy_flag=True

    # RPO (Rendezvous/Proximity Operations)
    rpo_score: float          # 0–1

    # Persistence
    persistence_score: float  # 0–1

    evidence: list[str]
```

### Capability signal rules

**ISR score:**
```
SSO orbit (96–100° incl) + LEO altitude (250–600 km)  → +0.5
Mission keyword in ISR taxonomy (imaging, reconnaissance, EO, SAR)  → +0.3
Passes > 4/day over any high-value region  → +0.2
payload_type = "EO" or "SAR" (if KG attribute set)  → +0.2
```

**Ground resolution class** (heuristic from altitude, no aperture data):
```
altitude < 300 km  → "sub-meter possible"
300–500 km         → "1–3m range"
500–800 km         → "3–10m range"
> 800 km           → ">10m range"
```

**Propulsion score:**
```
total_delta_v_obs > 50 m/s   → +0.5
total_delta_v_obs > 10 m/s   → +0.3
incl_change_count > 0         → +0.3  (plane changes are extremely expensive)
maneuver_frequency > 2/month  → +0.2
max_single_delta_v > 10 m/s  → +0.2
```

**RPO score:**
```
stealth_burn_count > 0  → +0.4  (unreported burns = suspicious execution)
formation_flying (member of close-separation constellation)  → +0.2
```

**Persistence score:**
```
orbital_period < 120 min (LEO) + inclination stable > 6 months  → +0.3
propellant estimate positive (from mass data if available)  → +0.3
```

---

## Layer 3 — Threat Assessment

### ThreatScore (0–100)

```
ThreatScore = CapabilityScore (0–50) + ActorContextScore (0–50)

ThreatLevel:
  0–33   → LOW
  34–66  → MEDIUM
  67+    → HIGH
```

### CapabilityScore (0–50): from CapabilityProfile

| Dimension | Max | Formula |
|---|---|---|
| ISR capability | 20 | `isr_score × 20` |
| Propulsion/RPO | 15 | `max(propulsion_score, rpo_score) × 15` |
| Persistence | 10 | `persistence_score × 10` |
| Revisit rate | 5 | capped at 5: passes_per_day > 4 → 5, > 2 → 3, > 0 → 1 |

### ActorContextScore (0–50)

**Rule-based graph traversal (0–45):**

Graph BFS from satellite node outward (max 3 hops, using `kg_store.get_subgraph()`):

| Condition | Points |
|---|---|
| node type = `MilitarySatellite` | +35 |
| `operatedBy` → `MilitaryUnit` (direct edge) | +30 |
| operator org has any edge to a `MilitarySatellite` (1-hop from org) | +20 |
| `manufacturedBy` → org with edges to `MilitarySatellite` | +12 |
| `memberOfConstellation` → constellation contains a `MilitarySatellite` | +10 |
| operator `contractedWith`/`partneredWith` → `MilitaryUnit` | +10 |
| mission/description keyword mismatch: ISR orbit + stated "experimental"/"science" | +8 |

Capped at 45.

**LLM agent augmentation (−5 to +5):**

Narrow adjustment applied only to ActorContextScore. The LLM agent:
- Identifies whether named organizations (e.g. "CAST", "Roscosmos") are known military actors using training knowledge
- Catches organizational relationships that rules missed (e.g. subsidiary → parent company → military contracts)
- Flags likely rule false-positives (e.g. organization matched by name but is unrelated)

The LLM does **not**: reason about geopolitical intentions, infer ASAT or other weapon intent, or make treaty compliance judgements.

Final ActorContextScore = `min(rule_score + llm_adjustment, 50)`

---

## LLM Agent Design (threat_llm.py)

Follows the same agentic loop pattern as `qa_engine.py`. Max 5 iterations.

**Tools available:**
```python
TOOLS = [
    expand_node(node_id, direction="both|out|in"),        # get neighbors + edges
    get_organization_satellites(org_id),                  # all sats by this org
    search_nodes_by_type(entity_type),                    # find MilitarySatellite, MilitaryUnit nodes
    get_event_history(satellite_id, days),                # maneuver/photometric history
]
```

**System prompt (scoped):**
```
You are evaluating organizational context for a satellite in a knowledge graph.
Your task: determine whether the operator or manufacturer has a known military space program.
Use the tools to walk the organizational graph.

Do NOT:
- Reason about geopolitical intentions or national threat posture
- Infer weapon or ASAT intent from behavior
- Flag based on country name alone without an organizational relationship

Return JSON:
{
  "adjustment": int,           // -5 to +5
  "confidence": str,           // "low" | "medium" | "high"
  "reasoning": str,            // 1–3 sentences on what you found
  "evidence": list[str],       // specific graph paths or org facts
  "false_positive_flags": list[str]  // rule flags you believe are incorrect
}
```

**Caching:**
```
data/threat/
  {node_id}_capability.json  # CapabilityProfile, recomputed on TLE/event change
  {node_id}_actor.json       # ActorContextScore (rules + LLM), cached with timestamp
```
Fast path: rules only (< 100ms). Full path: adds LLM (3–10s, cached).

---

## Signal Inventory

### A. Graph signals (Layer 3 rules)
1. Entity type: MilitarySatellite/CivilSatellite/CommercialSatellite
2. Direct operator type (MilitaryUnit)
3. Operator's historical military satellite connections (2-hop)
4. Manufacturer dual-use (also builds military satellites)
5. Constellation contains military members
6. Organizational military contracts (contractedWith → MilitaryUnit)
7. Mission/orbit mismatch (stated civil mission + ISR orbit)

### B. Behavioral signals (Layer 2 propulsion/RPO)
8. Maneuver frequency (maneuvers/month)
9. Total ΔV budget (cumulative propellant usage)
10. Large single-event ΔV (>10 m/s)
11. Inclination change events (plane changes — very expensive)
12. JCO/TLE discrepancy flag (stealth burn indicator)
13. Photometric anomalies (sudden brightness change)
14. Maneuver rate acceleration (recent 30d vs historical baseline)

### C. Orbital geometry signals (Layer 2 ISR)
15. Coverage frequency over high-value regions (passes/day)
16. SSO orbit at ISR-optimal altitude (97-98° incl, 250-600 km)
17. Inclination optimized for specific latitude bands
18. Altitude trend direction (raising/lowering)

### D. Capability derived (Layer 2 outputs)
19. Ground resolution class (from altitude heuristic)
20. Revisit rate to point target (from coverage analysis)
21. Estimated ΔV remaining (rough, from event history)
22. Formation flying detection (constellation separation)

---

## New Schema Additions

### New Satellite attributes (schema.yaml):
```yaml
Satellite:
  attributes:
    payload_type:        { type: string, required: false, description: "EO / SAR / SIGINT / COMSAT / unknown" }
    ground_resolution_m: { type: float,  required: false, description: "Estimated ground resolution in meters" }
    isr_tier:           { type: string, required: false, description: "Confirmed / Suspected / Unlikely / Unknown" }
```

Threat score is stored in `data/threat/` cache files, not in the KG — it is derived, not ingested.

### New relationship type (schema.yaml):
```yaml
hasBuiltMilitarySatellite: { domain: [Organization], range: [MilitarySatellite], description: "Org has manufactured confirmed military satellites" }
```

---

## Implementation Plan

### New files

| File | Purpose |
|---|---|
| `backend/modules/analysis/capability_assessor.py` | Layer 2: CapabilityProfile from orbital params + event history + KG attributes |
| `backend/modules/analysis/threat_scorer.py` | Layer 3 rules: KG graph traversal (BFS 3 hops) → ActorContextScore |
| `backend/modules/analysis/threat_llm.py` | Layer 3 LLM: GPT-4o agent (5 tools, max 5 iters) → narrow adjustment (−5 to +5) + reasoning |
| `backend/modules/analysis/adversary_config.py` | Static config: ISR mission keywords, high-value regions, known military org names |

### Modified files

| File | Change |
|---|---|
| `backend/api/routes_analysis.py` | Add `GET /api/analysis/threat/{node_id}`, `GET /api/analysis/threat/fleet`, `POST /api/analysis/threat/refresh` |
| `backend/modules/analysis/qa_engine.py` | Add `get_threat_score` and `get_fleet_threat` tools |
| `data/schema/schema.yaml` | Add `payload_type`, `ground_resolution_m`, `isr_tier` to Satellite; add `hasBuiltMilitarySatellite` relation |
| `frontend/src/api/client.ts` | Add `ThreatAssessment` type, `getThreatScore()`, `getFleetThreat()` |
| `frontend/src/components/SatelliteInfo/SatellitePanel.tsx` | Threat badge (LOW / MEDIUM / HIGH) in satellite header |
| `frontend/src/components/Analysis/AnalysisPanel.tsx` | Threat column in fleet query; Threat Overview section |

### Endpoints

```
GET  /api/analysis/threat/{node_id}
     → { score, level, capability_score, actor_context_score,
          capability: {...}, flags, evidence, narrative, rule_only, assessed_at }

GET  /api/analysis/threat/fleet
     → [{ node_id, label, score, level, capability_score, actor_context_score }]
        sorted descending by score

POST /api/analysis/threat/refresh?node_id={id}
     → recompute capability + rules + LLM for one or all satellites
```

---

## Future Knowledge Sources (prioritized)

| Source | Value | Priority |
|---|---|---|
| UCS Satellite Database (CSV) | Adds `payload_type`, mass, power for ~2000 satellites | High — one-time import |
| ISR orbit auto-classifier | Rule-based `isr_tier` tag from TLE inclination + altitude | High — pure logic |
| Space-Track CSM conjunction reports | Real close-approach history between satellites | Medium — API integration |
| Gunter's Space Page | Manufacturer/mission details for additional satellites | Medium |
| Ground station network (ITU public data) | Command/control topology, operational tempo | Medium |

---

## Verification

1. `GET /api/analysis/threat/{node_id}` for a known `MilitarySatellite` → HIGH, actor_context_score ≥ 35, evidence shows graph path
2. `GET /api/analysis/threat/{node_id}` for a `CommercialSatellite` with no military connections → LOW
3. `GET /api/analysis/threat/fleet` → list sorted by score, all KG satellites covered
4. Satellite with stealth burn events → elevated `rpo_score` in capability profile
5. SatellitePanel: threat badge visible alongside satellite name
6. Q&A: "Which satellites in the KG are highest threat?" → routes to `get_fleet_threat`, returns ranked answer
