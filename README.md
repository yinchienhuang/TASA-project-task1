# TASA — Tactical Space Awareness System

A web-based Space Situational Awareness (SSA) platform for tracking, analyzing, and visualizing satellite activity. Combines 3D orbital visualization, a structured knowledge graph, AI-powered analysis, and NOTAM-based restricted area mapping.

---

## Features

### 3D Satellite Tracking
- Real-time satellite position propagation using **SGP4** orbital mechanics
- Interactive 3D globe powered by **CesiumJS**
- TLE auto-fetch from [tle.ivanstanojevic.me](https://tle.ivanstanojevic.me) with CelesTrak fallback
- 24-hour position pre-computation on startup; TLE history archived daily

### Knowledge Graph (KG)
- Graph of satellites, organizations, launch vehicles, constellations, and their relationships
- Ingest source documents (PDF, HTML, MHTML) via GPT-4o extraction
- Node types: `MilitarySatellite`, `CivilSatellite`, `CommercialSatellite`, `Organization`, `LaunchVehicle`, `SatelliteConstellation`, and more
- Conflict detection and evolution tracking for graph updates
- Interactive graph view with node type filtering and reasoning subgraph highlighting

### Event Tracking
- Maneuver events: ΔV, regime change, TLE/JCO discrepancy flags
- Photometric change events: sudden brightness anomalies
- Activity badges and recency sorting in the satellite panel
- Filter events by satellite, regime (LEO/MEO/GEO), or time window

### NOTAM Ingest & Map Overlay
- Paste raw ICAO NOTAM text to extract restricted/danger area events
- Supports Q-codes: `QRDCA`, `QRDCB`, `QWMLW`, `QWMLA`, `QRMCA`, and all `QR*`/`QW*` variants
- Parses both coordinate formats:
  - Format A (prefix): `N281400E1020100`
  - Format B (suffix): `194200N 1184200E`
- Renders polygon and circle zones on the globe with time-aware coloring:
  - Active: red glow
  - Upcoming: amber
  - Past: ghost grey
- Deduplication by NOTAM ID; zones persist across sessions

### AI-Powered Analysis
- Agentic Q&A engine (GPT-4o) for SSA questions — chains multiple tool calls to answer complex queries
- Tools: satellite info, event search, maneuver history, coverage analysis, fleet coverage
- Coverage analysis: passes per day, revisit interval over configurable regions (Taiwan, South China Sea, Korean Peninsula, etc.)
- Proximity / conjunction detection between satellites

### News Feed
- Automated space news collection, refreshed every 6 hours
- Cached locally for offline browsing

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend framework | React 19 + TypeScript |
| Build tool | Vite 8 |
| 3D globe | CesiumJS 1.140 (via Resium) |
| Graph visualization | Cytoscape.js 3.33 |
| State management | Zustand 5 |
| Backend framework | FastAPI + Uvicorn |
| Orbital mechanics | sgp4 |
| AI / LLM | OpenAI GPT-4o |
| PDF parsing | PyMuPDF |
| Task scheduling | APScheduler |
| Storage | JSON files (no external database) |

---

## Project Structure

```
TASA-project-task1/
├── backend/
│   ├── main.py                   # FastAPI app entrypoint
│   ├── requirements.txt
│   ├── api/                      # REST route handlers
│   │   ├── routes_events.py      # Maneuver / NOTAM events
│   │   ├── routes_kg.py          # Knowledge graph CRUD
│   │   ├── routes_analysis.py    # Coverage, Q&A
│   │   ├── routes_propagation.py # TLE / position propagation
│   │   └── routes_ingestion.py   # News / document ingest
│   └── modules/
│       ├── propagation/          # SGP4, TLE store, history
│       ├── knowledge_graph/      # KG store, extractor, schema
│       ├── events/               # Event store, JCO/NOTAM extractors
│       ├── analysis/             # Coverage, Q&A engine
│       └── ingestion/            # News collector
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── EarthView/        # CesiumJS globe + NOTAM overlay
│       │   ├── KGView/           # Cytoscape knowledge graph
│       │   ├── Notam/            # NOTAM ingest panel
│       │   ├── Analysis/         # Q&A and coverage panel
│       │   └── SatelliteInfo/    # Satellite list + activity panel
│       ├── store/appStore.ts     # Zustand global state
│       └── api/client.ts         # Backend API client
└── data/
    ├── kg/graph.json             # Knowledge graph
    ├── events/events.json        # Event store
    ├── schema/schema.yaml        # KG entity/relation schema
    └── reference/                # UCS satellite database CSV
```

---

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 20+
- OpenAI API key
- Cesium Ion access token (free at [ion.cesium.com](https://ion.cesium.com))

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt

# Create backend/.env
echo OPENAI_API_KEY=your_key_here > .env

uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install

# Create frontend/.env
echo VITE_CESIUM_ION_TOKEN=your_token_here > .env

npm run dev
```

The app will be available at `http://localhost:5173`.

---

## API Overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/events` | List events (filter by type, regime, days) |
| `POST` | `/api/events/notam/ingest` | Parse and store a raw NOTAM |
| `GET` | `/api/events/notam` | List all NOTAM launch events |
| `DELETE` | `/api/events/{id}` | Delete an event |
| `GET` | `/api/kg/nodes` | List KG nodes |
| `POST` | `/api/kg/ingest` | Ingest a document into the KG |
| `GET` | `/api/analysis/coverage/{norad_id}` | Coverage passes for a satellite |
| `POST` | `/api/analysis/query` | Natural language SSA query (GPT-4o) |
| `GET` | `/api/propagation/positions/{norad_id}` | Propagated orbit positions |

---

## Environment Variables

| File | Variable | Description |
|---|---|---|
| `backend/.env` | `OPENAI_API_KEY` | OpenAI API key (GPT-4o) |
| `frontend/.env` | `VITE_CESIUM_ION_TOKEN` | Cesium Ion access token |
