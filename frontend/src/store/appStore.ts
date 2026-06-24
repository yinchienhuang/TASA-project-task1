import { create } from 'zustand';
import type { ThreatAssessment } from '../data/mockData';

export interface TrajectoryZone {
  notam_id: string;
  shape: 'circle' | 'polygon';
  center_lat?: number;
  center_lon?: number;
  radius_km?: number;
  vertices?: [number, number][];  // [lat, lon] pairs
  active_start: string;           // ISO 8601
  active_end: string;
}

interface AppState {
  selectedSatelliteId: string | null;
  currentTimeIndex: number; // index into position arrays (0 = 12h ago, max = now+12h)
  activeReasoning: ThreatAssessment | null;
  activeReasoningSubgraphIds: Set<string>;
  activePanel: 'kg' | 'reasoning';
  visibleSatelliteIds: Set<string>;
  notamZones: TrajectoryZone[];

  selectSatellite: (id: string | null) => void;
  setTimeIndex: (idx: number) => void;
  setActiveReasoning: (result: ThreatAssessment | null, subgraphIds?: Set<string>) => void;
  setActivePanel: (panel: 'kg' | 'reasoning') => void;
  toggleSatelliteVisibility: (id: string) => void;
  hideAllSatellites: () => void;
  setNotamZones: (zones: TrajectoryZone[]) => void;
}

export const useAppStore = create<AppState>((set) => ({
  selectedSatelliteId: null,
  currentTimeIndex: 720, // midpoint = "now"
  activeReasoning: null,
  activeReasoningSubgraphIds: new Set(),
  activePanel: 'kg',
  visibleSatelliteIds: new Set<string>(),
  notamZones: [],

  selectSatellite: (id) => set({ selectedSatelliteId: id }),
  setTimeIndex: (idx) => set({ currentTimeIndex: idx }),
  setActiveReasoning: (result, subgraphIds = new Set()) =>
    set({ activeReasoning: result, activeReasoningSubgraphIds: subgraphIds, activePanel: 'reasoning' }),
  setActivePanel: (panel) => set({ activePanel: panel }),
  toggleSatelliteVisibility: (id) => set((s) => {
    const next = new Set(s.visibleSatelliteIds);
    if (next.has(id)) next.delete(id); else next.add(id);
    return { visibleSatelliteIds: next };
  }),
  hideAllSatellites: () => set({ visibleSatelliteIds: new Set(), selectedSatelliteId: null }),
  setNotamZones: (zones) => set({ notamZones: zones }),
}));
