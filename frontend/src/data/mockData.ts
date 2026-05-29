export interface SatelliteInfo {
  noradId: string;
  name: string;
  imageUrl: string;
  launchDate: string;
  manufacturer: string;
  operator: string;
  mission: string;
  description: string;
  newsKeywords?: string;
  nodeId?: string;
  type?: string;
}

export interface Position {
  lat: number;
  lon: number;
  alt: number; // km
  timestamp: number; // unix ms
}

export interface KGAttrValue {
  value: unknown;
  event_date?: string | null;
  source_id?: string | null;
}

export interface KGSource {
  source_id: string;
  title?: string;
  url?: string;
  date?: string;
  excerpt?: string;
}

export interface KGNode {
  id: string;
  label: string;
  type: string;
  inferred_types?: string[];
  attributes?: Record<string, KGAttrValue | unknown>;
  sources?: KGSource[];
  created_at?: string;
  updated_at?: string;
}

export interface ArticleSource {
  id: number;
  title: string;
  url: string;
  news_site: string;
  published_at: string;
}

export interface KGEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  sources?: KGSource[];
  article?: ArticleSource;
  created_at?: string;
  updated_at?: string;
}

export interface ThreatAssessment {
  severity: 'Low' | 'Medium' | 'High' | 'Critical';
  narrative: string;
  recommendedActions: string[];
  subgraphIds: string[];
  timestamp: string;
}

// ── Satellites ──────────────────────────────────────────────────────────────

export const MOCK_SATELLITES: SatelliteInfo[] = [
  {
    noradId: '25544',
    name: 'ISS (ZARYA)',
    imageUrl: '/satellites/iss.jpg',
    launchDate: '1998-11-20',
    manufacturer: 'Boeing / RSC Energia',
    operator: 'NASA / Roscosmos / ESA / JAXA / CSA',
    mission: 'International Space Station',
    description: 'The ISS is a modular space station in low Earth orbit. It is a multinational collaborative project involving five space agencies.',
  },
  {
    noradId: '43013',
    name: 'NOAA-20',
    imageUrl: '/satellites/noaa20.jpg',
    launchDate: '2017-11-18',
    manufacturer: 'Ball Aerospace',
    operator: 'NOAA',
    mission: 'Earth Observation',
    description: 'NOAA-20 is the first satellite in the JPSS constellation, providing global environmental monitoring for weather forecasting.',
  },
  {
    noradId: '48274',
    name: 'Starlink-1971',
    imageUrl: '/satellites/starlink.jpg',
    launchDate: '2021-05-26',
    manufacturer: 'SpaceX',
    operator: 'SpaceX',
    mission: 'Broadband Internet',
    description: 'Part of SpaceX Starlink constellation providing broadband internet coverage globally.',
  },
  {
    noradId: '42920',
    name: 'FORMOSAT-5',
    imageUrl: '/satellites/formosat5.png',
    launchDate: '2017-08-25',
    manufacturer: 'NSPO (National Space Organization)',
    operator: 'NSPO / TASA',
    mission: 'Earth Observation',
    description: 'FORMOSAT-5 is a Taiwanese optical remote sensing satellite operated by TASA. It carries a 2-meter resolution panchromatic imager and was launched on a SpaceX Falcon 9 from Vandenberg AFB.',
  },
  {
    noradId: '49026',
    name: 'Yaogan-30 11A',
    imageUrl: '/satellites/yaogan30.jpg',
    launchDate: '2021-09-27',
    manufacturer: 'CAST (China Academy of Space Technology)',
    operator: 'PLA Strategic Support Force',
    mission: 'SIGINT / Electronic Intelligence (ELINT)',
    description: 'Yaogan-30 11A is part of a Chinese PLA military ELINT triplet constellation in low Earth orbit. The Yaogan-30 series is believed to conduct signals intelligence gathering. Launched by Long March 2C from Xichang Satellite Launch Center.',
  },
];

// ── Pre-computed orbit positions (simplified circular paths for mock) ────────

function generateOrbitPositions(
  inclinationDeg: number,
  altKm: number,
  periodMinutes: number,
  phaseDeg: number,
  count: number,
  startMs: number,
  stepMs: number
): Position[] {
  const positions: Position[] = [];
  const inc = (inclinationDeg * Math.PI) / 180;
  for (let i = 0; i < count; i++) {
    const t = startMs + i * stepMs;
    const angle = ((2 * Math.PI * (i / count)) + (phaseDeg * Math.PI) / 180) % (2 * Math.PI);
    const lat = Math.asin(Math.sin(inc) * Math.sin(angle)) * (180 / Math.PI);
    const lon = (Math.atan2(Math.cos(inc) * Math.sin(angle), Math.cos(angle)) * (180 / Math.PI) - (i * 360 * stepMs) / (periodMinutes * 60 * 1000)) % 360;
    positions.push({ lat, lon: ((lon + 540) % 360) - 180, alt: altKm, timestamp: t });
  }
  return positions;
}

const NOW = Date.now();
const STEP = 60_000; // 1 min
const COUNT = 1440;  // 24h

export const MOCK_POSITIONS: Record<string, Position[]> = {
  '25544': generateOrbitPositions(51.6, 408, 92.9, 0, COUNT, NOW - 12 * 3600_000, STEP),
  '43013': generateOrbitPositions(98.7, 833, 101.3, 120, COUNT, NOW - 12 * 3600_000, STEP),
  '48274': generateOrbitPositions(53, 550, 95.5, 240, COUNT, NOW - 12 * 3600_000, STEP),
  '42920': generateOrbitPositions(98.2, 720, 99.0, 60, COUNT, NOW - 12 * 3600_000, STEP),
  '49026': generateOrbitPositions(35.0, 600, 95.8, 180, COUNT, NOW - 12 * 3600_000, STEP),
};

// ── Knowledge Graph ──────────────────────────────────────────────────────────
// Built from real Spaceflight News API articles (cache.json, April 2026)

export const MOCK_KG_NODES: KGNode[] = [
  // Satellites
  { id: '25544', label: 'ISS', type: 'satellite' },
  { id: '43013', label: 'NOAA-20', type: 'satellite' },
  { id: '42920', label: 'FORMOSAT-5', type: 'satellite' },

  // Organizations
  { id: 'nasa',     label: 'NASA',                type: 'company' },
  { id: 'esa',      label: 'ESA',                 type: 'company' },
  { id: 'noaa',     label: 'NOAA',                type: 'company' },
  { id: 'northrop', label: 'Northrop Grumman',    type: 'company' },
  { id: 'spacex',   label: 'SpaceX',              type: 'company' },
  { id: 'voyager',  label: 'Voyager Technologies', type: 'company' },
  { id: 'tasa',     label: 'TASA',                type: 'company' },
  { id: 'avio',     label: 'Avio',                type: 'company' },
  { id: 'pla',      label: 'PLA SSF',             type: 'company' },
  { id: 'cast',     label: 'CAST',                type: 'company' },

  // Satellites
  { id: '49026',    label: 'Yaogan-30 11A',        type: 'satellite' },

  // Missions
  { id: 'expedition74', label: 'Expedition 74',   type: 'mission' },
  { id: 'jpss',         label: 'JPSS Program',    type: 'mission' },
  { id: 'crs24',        label: 'CRS-24 (NG-24)',  type: 'mission' },

  // JCO report
  { id: 'jco1', label: 'JCO Report #2026-041', type: 'report' },
];

// Article metadata constants (from cache.json)
const ART_37561: ArticleSource = { id: 37561, title: 'Voyager Space and Hilton Hotels Announce Private Astronaut Mission to ISS', url: 'https://spacenews.com/voyager-space-hilton-hotels-announce-private-astronaut-mission-to-iss/', news_site: 'SpaceNews', published_at: '2026-03-18T14:00:00Z' };
const ART_37444: ArticleSource = { id: 37444, title: 'Northrop Grumman CRS-24 Cygnus Cargo Ship Launches Aboard SpaceX Falcon 9', url: 'https://spaceflightnow.com/2026/03/05/northrop-grumman-crs-24-cygnus-cargo-ship-launches-aboard-spacex-falcon-9/', news_site: 'Spaceflight Now', published_at: '2026-03-05T18:22:00Z' };
const ART_37557: ArticleSource = { id: 37557, title: 'ESA Astronaut Opens Cygnus NG-24 Hatch on International Space Station', url: 'https://www.esa.int/Newsroom/Press_Releases/ESA_astronaut_opens_Cygnus_NG-24_hatch', news_site: 'ESA', published_at: '2026-03-08T10:15:00Z' };
const ART_35859: ArticleSource = { id: 35859, title: 'NASA\'s Libera Climate Sensor Completes Environmental Testing for JPSS-4', url: 'https://www.nasa.gov/science-research/earth-science/libera-climate-sensor-completes-testing/', news_site: 'NASA', published_at: '2025-11-12T16:00:00Z' };
const ART_24820: ArticleSource = { id: 24820, title: 'NASA Awards SpaceX Contract to Launch JPSS-4 Weather Satellite', url: 'https://www.nasa.gov/news-release/nasa-awards-spacex-contract-launch-jpss-4/', news_site: 'NASA', published_at: '2024-06-05T19:00:00Z' };
const ART_34997: ArticleSource = { id: 34997, title: 'TASA Awards Avio Contract to Launch FORMOSAT-8 and FORMOSAT-9 on Vega-C', url: 'https://spacenews.com/tasa-awards-avio-contract-formosat-8-9/', news_site: 'SpaceNews', published_at: '2025-09-22T08:30:00Z' };

export const MOCK_KG_EDGES: KGEdge[] = [
  // ISS — organizations
  { id: 'e1',  source: '25544', target: 'nasa',         label: 'operatedBy' },
  { id: 'e2',  source: '25544', target: 'esa',          label: 'operatedBy',    article: ART_37557 },
  // ISS — missions
  { id: 'e3',  source: '25544', target: 'expedition74', label: 'partOf' },
  { id: 'e4',  source: '25544', target: 'crs24',        label: 'receivedCargo', article: ART_37444 },
  // ISS — JCO
  { id: 'e5',  source: 'jco1',  target: '25544',        label: 'concerns' },

  // CRS-24 mission links
  { id: 'e6',  source: 'crs24', target: 'northrop',     label: 'operatedBy',    article: ART_37444 },
  { id: 'e7',  source: 'crs24', target: 'spacex',       label: 'launchedBy',    article: ART_37444 },

  // Voyager — ISS private mission
  { id: 'e8',  source: 'voyager', target: '25544',      label: 'missionTo',     article: ART_37561 },
  { id: 'e9',  source: 'voyager', target: 'nasa',       label: 'contractedBy',  article: ART_37561 },

  // ESA — CRS-24 ISS crew activity
  { id: 'e10', source: 'esa',   target: 'crs24',        label: 'crewOn',        article: ART_37557 },

  // NOAA-20 — organizations
  { id: 'e11', source: '43013', target: 'noaa',         label: 'operatedBy' },
  { id: 'e12', source: '43013', target: 'northrop',     label: 'manufacturedBy' },
  { id: 'e13', source: '43013', target: 'nasa',         label: 'launchedBy' },
  // NOAA-20 — missions
  { id: 'e14', source: '43013', target: 'jpss',         label: 'partOf',        article: ART_35859 },

  // JPSS program
  { id: 'e15', source: 'jpss',  target: 'noaa',         label: 'managedBy' },
  { id: 'e16', source: 'jpss',  target: 'nasa',         label: 'partneredWith' },
  { id: 'e17', source: 'jpss',  target: 'spacex',       label: 'launchContractWith', article: ART_24820 },

  // FORMOSAT-5 — organizations
  { id: 'e18', source: '42920', target: 'tasa',         label: 'operatedBy' },
  { id: 'e19', source: 'tasa',  target: 'avio',         label: 'contractedWith', article: ART_34997 },

  // Yaogan-30 11A — organizations
  { id: 'e20', source: '49026', target: 'pla',          label: 'operatedBy' },
  { id: 'e21', source: '49026', target: 'cast',         label: 'manufacturedBy' },
];

// Subgraph highlighted during ISS conjunction reasoning
export const MOCK_REASONING_SUBGRAPH = {
  nodeIds: new Set(['25544', 'nasa', 'esa', 'expedition74', 'crs24', 'northrop', 'jco1']),
  edgeIds: new Set(['e1', 'e2', 'e3', 'e4', 'e5', 'e6', 'e7', 'e10']),
};

// ── Threat Assessment ────────────────────────────────────────────────────────

export const MOCK_THREAT: ThreatAssessment = {
  severity: 'Medium',
  narrative:
    'JCO Report #2024-112 indicates an unplanned orbital maneuver by ISS (NORAD 25544) on 2024-10-14T08:32Z, raising the apogee by approximately 3.2 km. Cross-referencing the knowledge graph: Boeing (prime contractor) is currently undergoing supply-chain restructuring per recent news, which may affect maintenance cycles. The maneuver is consistent with debris avoidance procedures and does not indicate hostile intent. Crew safety is not at risk. Recommend continued monitoring over the next 72 hours.',
  recommendedActions: [
    'Monitor ISS orbital parameters every 6 hours for the next 72 hours.',
    'Request clarification from NASA on maneuver justification.',
    'Update conjunction analysis for ISS with active satellites within 5 km radius.',
  ],
  subgraphIds: ['25544', 'boeing', 'nasa', 'news1', 'news2', 'jco1'],
  timestamp: '2024-10-14T09:15:00Z',
};
