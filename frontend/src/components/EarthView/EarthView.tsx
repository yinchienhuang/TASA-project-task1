import { useEffect, useRef, useState } from 'react';
import * as Cesium from 'cesium';
import { useAppStore } from '../../store/appStore';
import type { TrajectoryZone } from '../../store/appStore';
import { MOCK_POSITIONS } from '../../data/mockData';
import type { Position } from '../../data/mockData';
import { getPositions, getCurrentPosition, getKGSatellites } from '../../api/client';
import Timeline from './Timeline';
import 'cesium/Build/Cesium/Widgets/widgets.css';

interface LaunchSite {
  name: string; lat: number; lon: number;
  country: string; operator: string;
  firstLaunch: string; vehicles: string; inclinations: string; description: string;
}

const LAUNCH_SITES: LaunchSite[] = [
  {
    name: 'Kennedy Space Center', lat: 28.5623, lon: -80.5774,
    country: 'USA', operator: 'NASA / SpaceX',
    firstLaunch: '1950 (Cape Canaveral)', vehicles: 'Falcon 9, Falcon Heavy, SLS',
    inclinations: '28.5° – 57°', description: 'Primary US crewed and heavy-lift launch facility on Florida\'s Atlantic coast.',
  },
  {
    name: 'Vandenberg SFB', lat: 34.7420, lon: -120.5724,
    country: 'USA', operator: 'USSF / SpaceX',
    firstLaunch: '1958', vehicles: 'Falcon 9, Falcon Heavy',
    inclinations: 'SSO / Polar (97°–105°)', description: 'Primary US polar-orbit and SSO launch site on the California coast.',
  },
  {
    name: 'Baikonur Cosmodrome', lat: 45.9208, lon: 63.3420,
    country: 'KAZ (leased by RUS)', operator: 'Roscosmos',
    firstLaunch: '1957 (Sputnik 1)', vehicles: 'Soyuz, Proton',
    inclinations: '51.6° (ISS), 65°, 72°', description: 'World\'s first and largest operational space launch facility; birthplace of the Space Age.',
  },
  {
    name: 'Plesetsk Cosmodrome', lat: 62.9271, lon: 40.5777,
    country: 'RUS', operator: 'Russian MoD / Roscosmos',
    firstLaunch: '1966', vehicles: 'Soyuz-2, Angara',
    inclinations: 'High-inclination (63°–98°)', description: 'Russia\'s primary military and polar-orbit launch site; also home of the Angara family.',
  },
  {
    name: 'Jiuquan SLLC', lat: 40.9600, lon: 100.2980,
    country: 'CHN', operator: 'PLA / CASC',
    firstLaunch: '1970 (DFH-1)', vehicles: 'Long March 2, 4, 11',
    inclinations: '42°–98° (SSO)', description: 'China\'s oldest launch center; used for crewed Shenzhou missions and SSO/polar missions.',
  },
  {
    name: 'Wenchang SLC', lat: 19.6145, lon: 110.9514,
    country: 'CHN', operator: 'CASC',
    firstLaunch: '2016', vehicles: 'Long March 5, 7, 8',
    inclinations: '19°–98°', description: 'China\'s newest and lowest-latitude launch center; supports GTO and lunar/deep-space missions.',
  },
  {
    name: 'Taiyuan SLC', lat: 38.8490, lon: 111.6082,
    country: 'CHN', operator: 'CASC',
    firstLaunch: '1988', vehicles: 'Long March 2C/D, 4B/C, 6',
    inclinations: 'SSO (97°–100°)', description: 'Major Chinese SSO launch site; frequently used for Earth observation and weather satellites.',
  },
  {
    name: 'Xichang SLC', lat: 28.2464, lon: 102.0267,
    country: 'CHN', operator: 'CASC',
    firstLaunch: '1984', vehicles: 'Long March 3A/B/C',
    inclinations: 'GTO (28°)', description: 'China\'s primary GEO/GTO launch site; home of the BeiDou navigation constellation launches.',
  },
  {
    name: 'Sriharikota (SDSC)', lat: 13.7199, lon: 80.2304,
    country: 'IND', operator: 'ISRO',
    firstLaunch: '1979', vehicles: 'PSLV, GSLV, LVM3',
    inclinations: 'SSO / GTO (13°)', description: 'India\'s only orbital spaceport; used for Chandrayaan, Mangalyaan, and OneWeb launches.',
  },
  {
    name: 'Kourou (CSG)', lat: 5.2322, lon: -52.7688,
    country: 'FRA / ESA', operator: 'ESA / ArianeGroup',
    firstLaunch: '1968', vehicles: 'Ariane 5, Ariane 6, Vega',
    inclinations: 'GTO / SSO (5°–98°)', description: 'Europe\'s primary spaceport near the equator in French Guiana; optimal for GTO launches.',
  },
  {
    name: 'Tanegashima SC', lat: 30.4005, lon: 130.9750,
    country: 'JPN', operator: 'JAXA',
    firstLaunch: '1975', vehicles: 'H-IIA, H-IIB, H3',
    inclinations: 'GTO (28°–30°), SSO', description: 'Japan\'s primary launch site on Tanegashima island; home of H-IIA and new H3 rocket.',
  },
  {
    name: 'Mahia LC-1', lat: -39.2610, lon: 177.8645,
    country: 'NZL', operator: 'Rocket Lab',
    firstLaunch: '2017', vehicles: 'Electron',
    inclinations: 'SSO / Mid-inclination (39°–98°)', description: 'Rocket Lab\'s private launch facility; world\'s most frequently used dedicated small-sat launcher.',
  },
  {
    name: 'Naro Space Center', lat: 34.4321, lon: 127.5356,
    country: 'KOR', operator: 'KARI',
    firstLaunch: '2013', vehicles: 'Nuri (KSLV-II)',
    inclinations: 'SSO (98°)', description: 'South Korea\'s first orbital spaceport; achieved first independent orbital launch with Nuri in 2022.',
  },
  {
    name: 'Palmachim AB', lat: 31.8974, lon: 34.6906,
    country: 'ISR', operator: 'IAI / Israeli MoD',
    firstLaunch: '1988', vehicles: 'Shavit',
    inclinations: 'Retrograde (143°)', description: 'Israel\'s launch site; launches westward over the Mediterranean into retrograde orbit to avoid overflying neighbors.',
  },
];

const LAUNCH_SITE_COLOR = Cesium.Color.fromCssColorString('#f0a500');

const INIT_VIEW = {
  destination: Cesium.Cartesian3.fromDegrees(0, 20, 20_000_000),
  orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 },
};

const TIMELINE_H = 40;
const STEP_MS = 60_000;
const ORBIT_HALF = 45; // ~90 min arc at 1-min steps

// Proximity thresholds (km)
const DANGER_KM  = 600;
const WARNING_KM = 1500;

const SAT_PALETTE = [
  Cesium.Color.CYAN,
  Cesium.Color.fromCssColorString('#3fb950'),
  Cesium.Color.fromCssColorString('#e8163c'),
  Cesium.Color.fromCssColorString('#f0a500'),
  Cesium.Color.fromCssColorString('#a371f7'),
  Cesium.Color.fromCssColorString('#79c0ff'),
  Cesium.Color.fromCssColorString('#ffa657'),
];

function satColor(id: string): Cesium.Color {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) & 0xffff;
  return SAT_PALETTE[h % SAT_PALETTE.length];
}

function orbitPositions(posArr: Position[], timeIndex: number): Cesium.Cartesian3[] {
  const result: Cesium.Cartesian3[] = [];
  for (let i = -ORBIT_HALF; i <= ORBIT_HALF; i++) {
    const idx = Math.min(Math.max(timeIndex + i, 0), posArr.length - 1);
    const p = posArr[idx];
    result.push(Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.alt * 1000));
  }
  return result;
}

function findNowIndex(positions: Position[]): number {
  if (!positions.length) return 0;
  const idx = Math.round((Date.now() - positions[0].timestamp) / STEP_MS);
  return Math.max(0, Math.min(positions.length - 1, idx));
}

function toECEF(lat: number, lon: number, alt: number): [number, number, number] {
  const a = 6378.137, e2 = 0.00669437999014;
  const latR = lat * Math.PI / 180, lonR = lon * Math.PI / 180;
  const N = a / Math.sqrt(1 - e2 * Math.sin(latR) ** 2);
  return [
    (N + alt) * Math.cos(latR) * Math.cos(lonR),
    (N + alt) * Math.cos(latR) * Math.sin(lonR),
    (N * (1 - e2) + alt) * Math.sin(latR),
  ];
}

function distanceBetween(a: Position, b: Position): number {
  const [ax, ay, az] = toECEF(a.lat, a.lon, a.alt);
  const [bx, by, bz] = toECEF(b.lat, b.lon, b.alt);
  return Math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2);
}

function proximityColor(dist: number): Cesium.Color {
  if (dist < DANGER_KM)  return Cesium.Color.fromCssColorString('#ff4444');
  if (dist < WARNING_KM) return Cesium.Color.YELLOW;
  return Cesium.Color.WHITE.withAlpha(0.15);
}

export default function EarthView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef    = useRef<Cesium.Viewer | null>(null);
  const pointsRef    = useRef<Cesium.PointPrimitiveCollection | null>(null);
  const labelsRef    = useRef<Cesium.LabelCollection | null>(null);
  const polylinesRef = useRef<Cesium.PolylineCollection | null>(null);
  const satRefs = useRef<Record<string, {
    point: Cesium.PointPrimitive;
    label: Cesium.Label;
    orbitLine: Cesium.Polyline;
    color: Cesium.Color;
  }>>({});
  const proximityLineRef = useRef<Cesium.Polyline | null>(null);
  const launchSitePointsRef = useRef<Cesium.PointPrimitiveCollection | null>(null);
  const launchSiteLabelsRef = useRef<Cesium.LabelCollection | null>(null);
  const launchSitePointMap = useRef<Map<Cesium.PointPrimitive, LaunchSite>>(new Map());
  const positionsRef = useRef<Record<string, Position[]>>({ ...MOCK_POSITIONS });

  const [dataSource, setDataSource] = useState<'mock' | 'sgp4'>('mock');
  const [showLaunchSites, setShowLaunchSites] = useState(true);
  const [selectedLaunchSite, setSelectedLaunchSite] = useState<LaunchSite | null>(null);
  const [distKm, setDistKm] = useState<number | null>(null);
  const [closestPairLabel, setClosestPairLabel] = useState('');
  const [satLabelMap, setSatLabelMap] = useState<Map<string, string>>(new Map());
  const [timelineMeta, setTimelineMeta] = useState({
    startTimestamp: Date.now() - 12 * 3600_000,
    stepMs: STEP_MS,
    nowIndex: 720,
    posCount: 1440,
  });

  const { currentTimeIndex, visibleSatelliteIds, notamZones, setNotamZones } = useAppStore();

  // ── Load satellite labels from KG ──────────────────────────────────────────
  useEffect(() => {
    getKGSatellites().then((sats) => {
      setSatLabelMap(new Map(
        sats.filter(s => s.noradId).map(s => [s.noradId!, s.name])
      ));
    });
  }, []);

  // ── Load existing NOTAM zones from API on mount ────────────────────────────
  useEffect(() => {
    fetch('http://localhost:8000/api/events/notam', { signal: AbortSignal.timeout(5000) })
      .then((r) => r.ok ? r.json() : [])
      .then((events: unknown[]) => {
        const zones: TrajectoryZone[] = [];
        for (const ev of events) {
          const z = (ev as { trajectory_zones?: TrajectoryZone[] }).trajectory_zones ?? [];
          zones.push(...z);
        }
        if (zones.length > 0) setNotamZones(zones);
      })
      .catch(() => {/* backend may not be running */});
  }, []);

  // ── Render NOTAM zones on globe ───────────────────────────────────────────
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;

    // Remove all existing NOTAM entities (fill + outline + label each have their own id)
    const toRemove = viewer.entities.values.filter(
      (e) => typeof e.id === 'string' && (e.id as string).startsWith('notam:')
    );
    for (const e of toRemove) viewer.entities.remove(e);

    const now = Date.now();

    for (const zone of notamZones) {
      const start = new Date(zone.active_start).getTime();
      const end = new Date(zone.active_end).getTime();
      const isActive = now >= start && now <= end;
      const isPast   = now > end;

      // Color scheme: red = active, amber = upcoming, grey = past
      const baseHex   = isActive ? '#ff4444' : isPast ? '#5a6270' : '#f0c040';
      const baseColor = Cesium.Color.fromCssColorString(baseHex);
      const fillColor = baseColor.withAlpha(isActive ? 0.35 : isPast ? 0.10 : 0.22);
      const lineWidth = isActive ? 5 : 2.5;

      // Centroid helper
      const centroid = (lats: number[], lons: number[]) => ({
        clat: lats.reduce((a, b) => a + b, 0) / lats.length,
        clon: lons.reduce((a, b) => a + b, 0) / lons.length,
      });


      if (zone.shape === 'polygon' && zone.vertices && zone.vertices.length >= 3) {
        const positions = Cesium.Cartesian3.fromDegreesArray(
          zone.vertices.flatMap(([lat, lon]) => [lon, lat])
        );
        const lats = zone.vertices.map(([lat]) => lat);
        const lons = zone.vertices.map(([, lon]) => lon);
        const { clat, clon } = centroid(lats, lons);

        // Fill (CLAMP_TO_GROUND — outline property silently ignored by Cesium here)
        viewer.entities.add({
          id: `notam:fill:${zone.notam_id}`,
          polygon: {
            hierarchy: new Cesium.PolygonHierarchy(positions),
            material: new Cesium.ColorMaterialProperty(fillColor),
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            classificationType: Cesium.ClassificationType.TERRAIN,
          },
        });

        // Outline drawn as a ground-clamped polyline (the only way it renders)
        viewer.entities.add({
          id: `notam:outline:${zone.notam_id}`,
          polyline: {
            positions: [...positions, positions[0]], // close the loop
            width: lineWidth,
            material: isActive
              ? new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.25, color: baseColor })
              : new Cesium.ColorMaterialProperty(baseColor.withAlpha(0.9)),
            clampToGround: true,
          },
        });

        // Label at centroid — subtle, small
        viewer.entities.add({
          id: `notam:label:${zone.notam_id}`,
          position: Cesium.Cartesian3.fromDegrees(clon, clat, 50000),
          label: {
            text: zone.notam_id,
            font: '11px sans-serif',
            fillColor: baseColor.withAlpha(0.85),
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.CENTER,
            horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            showBackground: false,
          },
        });

      } else if (zone.shape === 'circle' && zone.center_lat != null && zone.center_lon != null) {
        const pos = Cesium.Cartesian3.fromDegrees(zone.center_lon, zone.center_lat, 50000);
        const r = (zone.radius_km ?? 20) * 1000;

        viewer.entities.add({
          id: `notam:fill:${zone.notam_id}`,
          position: Cesium.Cartesian3.fromDegrees(zone.center_lon, zone.center_lat),
          ellipse: {
            semiMinorAxis: r,
            semiMajorAxis: r,
            material: new Cesium.ColorMaterialProperty(fillColor),
            outline: true,            // ellipse outline DOES render
            outlineColor: baseColor.withAlpha(0.9),
            outlineWidth: lineWidth,
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          },
        });

        viewer.entities.add({
          id: `notam:label:${zone.notam_id}`,
          position: pos,
          label: {
            text: zone.notam_id,
            font: '11px sans-serif',
            fillColor: baseColor.withAlpha(0.85),
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.CENTER,
            horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            showBackground: false,
          },
        });
      }
    }
  }, [notamZones]);

  // ── Listen for focus events from NotamIngestPanel ──────────────────────────
  useEffect(() => {
    const handler = (e: Event) => {
      const { lat, lon } = (e as CustomEvent<{ lat: number; lon: number }>).detail;
      const viewer = viewerRef.current;
      if (!viewer) return;
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(lon, lat, 2_000_000),
        duration: 1.5,
      });
    };
    window.addEventListener('notam:focus', handler);
    return () => window.removeEventListener('notam:focus', handler);
  }, []);

  // ── Init viewer ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || viewerRef.current) return;

    const token = import.meta.env.VITE_CESIUM_ION_TOKEN as string | undefined;
    if (token && token !== 'your_token_here') Cesium.Ion.defaultAccessToken = token;

    Cesium.Camera.DEFAULT_VIEW_RECTANGLE = Cesium.Rectangle.fromDegrees(-180, -90, 180, 90);
    Cesium.Camera.DEFAULT_VIEW_FACTOR = 0;

    const viewer = new Cesium.Viewer(containerRef.current, {
      terrainProvider: new Cesium.EllipsoidTerrainProvider(),
      baseLayerPicker: false, geocoder: false, homeButton: false,
      sceneModePicker: false, navigationHelpButton: false,
      animation: false, timeline: false, fullscreenButton: false,
      infoBox: false, selectionIndicator: false, shouldAnimate: false,
    });

    viewer.scene.globe.enableLighting = false;
    viewer.scene.fog.enabled = false;
    if (viewer.scene.sun) viewer.scene.sun.show = false;
    if (viewer.scene.moon) viewer.scene.moon.show = false;

    const slowWheel = (e: WheelEvent) => {
      if (!e.isTrusted) return;
      e.stopImmediatePropagation();
      e.preventDefault();
      viewer.canvas.dispatchEvent(new WheelEvent('wheel', {
        bubbles: e.bubbles, cancelable: e.cancelable,
        clientX: e.clientX, clientY: e.clientY,
        deltaX: e.deltaX * 0.25, deltaY: e.deltaY * 0.25,
        deltaZ: e.deltaZ * 0.25, deltaMode: e.deltaMode,
      }));
    };
    viewer.canvas.addEventListener('wheel', slowWheel, { capture: true, passive: false });
    viewer.camera.setView(INIT_VIEW);

    const points    = new Cesium.PointPrimitiveCollection();
    const labels    = new Cesium.LabelCollection();
    const polylines = new Cesium.PolylineCollection();
    viewer.scene.primitives.add(polylines);
    viewer.scene.primitives.add(points);
    viewer.scene.primitives.add(labels);
    pointsRef.current    = points;
    labelsRef.current    = labels;
    polylinesRef.current = polylines;

    // Launch site markers
    const lsPoints = new Cesium.PointPrimitiveCollection();
    const lsLabels = new Cesium.LabelCollection();
    viewer.scene.primitives.add(lsPoints);
    viewer.scene.primitives.add(lsLabels);
    launchSitePointsRef.current = lsPoints;
    launchSiteLabelsRef.current = lsLabels;
    for (const site of LAUNCH_SITES) {
      const cart = Cesium.Cartesian3.fromDegrees(site.lon, site.lat, 0);
      const pt = lsPoints.add({
        position: cart,
        color: LAUNCH_SITE_COLOR,
        pixelSize: 7,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 1,
      });
      launchSitePointMap.current.set(pt, site);
      lsLabels.add({
        position: cart,
        text: `▲ ${site.name}`,
        font: '11px sans-serif',
        fillColor: LAUNCH_SITE_COLOR,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -16),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 12_000_000),
      });
    }

    // Proximity line (hidden until 2+ sats visible)
    proximityLineRef.current = polylines.add({
      positions: [Cesium.Cartesian3.ZERO, Cesium.Cartesian3.ZERO],
      width: 1,
      show: false,
      material: Cesium.Material.fromType('Color', { color: Cesium.Color.WHITE.withAlpha(0.15) }),
    });

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
    handler.setInputAction((e: Cesium.ScreenSpaceEventHandler.MotionEvent) => {
      const picked = viewer.scene.pick(e.endPosition);
      const isSat = Cesium.defined(picked) && Object.values(satRefs.current).some(r => r.point === picked.primitive);
      const isSite = Cesium.defined(picked) && launchSitePointMap.current.has(picked.primitive as Cesium.PointPrimitive);
      viewer.canvas.style.cursor = (isSat || isSite) ? 'pointer' : 'default';
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
    handler.setInputAction((e: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
      const picked = viewer.scene.pick(e.position);
      if (!Cesium.defined(picked)) {
        useAppStore.getState().selectSatellite(null);
        setSelectedLaunchSite(null);
        return;
      }
      const site = launchSitePointMap.current.get(picked.primitive as Cesium.PointPrimitive);
      if (site) { setSelectedLaunchSite(s => s?.name === site.name ? null : site); return; }
      const match = Object.entries(satRefs.current).find(([, r]) => r.point === (picked.primitive as Cesium.PointPrimitive));
      if (match) { setSelectedLaunchSite(null); useAppStore.getState().selectSatellite(match[0]); }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    viewerRef.current = viewer;
    return () => {
      handler.destroy();
      viewer.canvas.removeEventListener('wheel', slowWheel, { capture: true });
      satRefs.current = {};
      proximityLineRef.current = null;
      pointsRef.current = null;
      labelsRef.current = null;
      polylinesRef.current = null;
      launchSitePointsRef.current = null;
      launchSiteLabelsRef.current = null;
      launchSitePointMap.current.clear();
      viewer.destroy();
      viewerRef.current = null;
    };
  }, []);

  // ── Add/remove Cesium primitives when visibility changes ───────────────────
  useEffect(() => {
    const points    = pointsRef.current;
    const labels    = labelsRef.current;
    const polylines = polylinesRef.current;
    if (!points || !labels || !polylines) return;

    const currentIdx = useAppStore.getState().currentTimeIndex;

    // Add newly visible satellites
    for (const id of visibleSatelliteIds) {
      if (satRefs.current[id]) continue; // already added

      const color = satColor(id);
      const posArr = positionsRef.current[id] ?? [];
      const p = posArr[Math.min(currentIdx, posArr.length - 1)] ?? { lat: 0, lon: 0, alt: 400 };
      const cart = Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.alt * 1000);
      const label = satLabelMap.get(id) ?? id;

      const point = points.add({
        position: cart, color, pixelSize: 10,
        outlineColor: Cesium.Color.WHITE, outlineWidth: 1,
      });
      const labelPrim = labels.add({
        position: cart, text: label, font: '13px sans-serif',
        fillColor: Cesium.Color.WHITE, outlineColor: Cesium.Color.BLACK, outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -20),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 30_000_000),
      });
      const orbitLine = polylines.add({
        positions: posArr.length ? orbitPositions(posArr, currentIdx) : [cart, cart],
        width: 1.5,
        material: Cesium.Material.fromType('Color', { color: color.withAlpha(0.35) }),
      });
      satRefs.current[id] = { point, label: labelPrim, orbitLine, color };

      // Always fetch real positions; use mock/existing as placeholder while loading
      getPositions(id).then(({ positions, source }) => {
        if (!positions.length) return;
        positionsRef.current[id] = positions;
        if (source === 'sgp4') setDataSource('sgp4');
        // Update timeline from first visible satellite
        const ids = Array.from(useAppStore.getState().visibleSatelliteIds);
        if (ids[0] === id) {
          const nowIdx = findNowIndex(positions);
          setTimelineMeta({ startTimestamp: positions[0].timestamp, stepMs: STEP_MS, nowIndex: nowIdx, posCount: positions.length });
          useAppStore.getState().setTimeIndex(nowIdx);
        }
        // Update rendered position with real data
        const refs = satRefs.current[id];
        if (refs) {
          const idx = Math.min(useAppStore.getState().currentTimeIndex, positions.length - 1);
          const pp = positions[idx];
          const c = Cesium.Cartesian3.fromDegrees(pp.lon, pp.lat, pp.alt * 1000);
          refs.point.position = c;
          refs.label.position = c;
          refs.orbitLine.positions = orbitPositions(positions, idx);
        }
      });
    }

    // Remove hidden satellites
    for (const id of Object.keys(satRefs.current)) {
      if (visibleSatelliteIds.has(id)) continue;
      const refs = satRefs.current[id];
      points.remove(refs.point);
      labels.remove(refs.label);
      polylines.remove(refs.orbitLine);
      delete satRefs.current[id];
    }

    // Hide proximity line if fewer than 2 sats visible
    if (proximityLineRef.current) {
      proximityLineRef.current.show = Object.keys(satRefs.current).length >= 2;
    }
  }, [visibleSatelliteIds, satLabelMap]);

  // ── Toggle launch site visibility ─────────────────────────────────────────
  useEffect(() => {
    if (launchSitePointsRef.current) launchSitePointsRef.current.show = showLaunchSites;
    if (launchSiteLabelsRef.current) launchSiteLabelsRef.current.show = showLaunchSites;
  }, [showLaunchSites]);

  // ── 30-second real-time poll ───────────────────────────────────────────────
  useEffect(() => {
    const poll = async () => {
      for (const id of useAppStore.getState().visibleSatelliteIds) {
        const pos = await getCurrentPosition(id);
        if (!pos) continue;
        const posArr = positionsRef.current[id];
        if (!posArr?.length) continue;
        const nowIdx = findNowIndex(posArr);
        posArr[nowIdx] = { lat: pos.lat, lon: pos.lon, alt: pos.alt, timestamp: pos.timestamp };
        const currentIdx = useAppStore.getState().currentTimeIndex;
        if (Math.abs(currentIdx - nowIdx) <= 2) {
          const refs = satRefs.current[id];
          if (refs) {
            const cart = Cesium.Cartesian3.fromDegrees(pos.lon, pos.lat, pos.alt * 1000);
            refs.point.position = cart;
            refs.label.position = cart;
          }
        }
      }
    };
    const id = setInterval(poll, 30_000);
    return () => clearInterval(id);
  }, []);

  // ── Update positions, colors, proximity on timeline scrub ─────────────────
  useEffect(() => {
    if (!viewerRef.current) return;

    const ids = Object.keys(satRefs.current);
    const positions: Record<string, Cesium.Cartesian3> = {};

    ids.forEach((id) => {
      const refs = satRefs.current[id];
      if (!refs) return;
      const posArr = positionsRef.current[id] ?? [];
      if (!posArr.length) return;
      const p = posArr[Math.min(currentTimeIndex, posArr.length - 1)];
      const cart = Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.alt * 1000);
      refs.point.position = cart;
      refs.label.position = cart;
      refs.orbitLine.positions = orbitPositions(posArr, currentTimeIndex);
      positions[id] = cart;
    });

    if (ids.length < 2) {
      setDistKm(null);
      return;
    }

    // Build all pairs dynamically
    const pairs: Array<{ a: string; b: string }> = [];
    for (let i = 0; i < ids.length; i++)
      for (let j = i + 1; j < ids.length; j++)
        pairs.push({ a: ids[i], b: ids[j] });

    let closestDist = Infinity;
    let closestPair = pairs[0];
    const pairDists: Record<string, number> = {};

    pairs.forEach((pair) => {
      const pa = positionsRef.current[pair.a]?.[Math.min(currentTimeIndex, (positionsRef.current[pair.a]?.length ?? 1) - 1)];
      const pb = positionsRef.current[pair.b]?.[Math.min(currentTimeIndex, (positionsRef.current[pair.b]?.length ?? 1) - 1)];
      if (pa && pb) {
        const d = distanceBetween(pa, pb);
        pairDists[`${pair.a}-${pair.b}`] = d;
        if (d < closestDist) { closestDist = d; closestPair = pair; }
      }
    });

    if (closestDist < Infinity) {
      setDistKm(closestDist);
      const la = satLabelMap.get(closestPair.a) ?? closestPair.a;
      const lb = satLabelMap.get(closestPair.b) ?? closestPair.b;
      setClosestPairLabel(`${la}↔${lb}`);
    }

    // Color each satellite by its closest neighbor
    ids.forEach((id) => {
      const refs = satRefs.current[id];
      if (!refs) return;
      const minDist = Math.min(
        ...pairs.filter(p => p.a === id || p.b === id)
          .map(p => pairDists[`${p.a}-${p.b}`] ?? Infinity)
      );
      if (minDist < DANGER_KM) {
        refs.point.color = Cesium.Color.fromCssColorString('#ff4444');
        refs.point.pixelSize = 14;
        refs.orbitLine.material = Cesium.Material.fromType('Color', { color: Cesium.Color.fromCssColorString('#ff4444').withAlpha(0.5) });
      } else if (minDist < WARNING_KM) {
        refs.point.color = Cesium.Color.YELLOW;
        refs.point.pixelSize = 12;
        refs.orbitLine.material = Cesium.Material.fromType('Color', { color: Cesium.Color.YELLOW.withAlpha(0.4) });
      } else {
        refs.point.color = refs.color;
        refs.point.pixelSize = 10;
        refs.orbitLine.material = Cesium.Material.fromType('Color', { color: refs.color.withAlpha(0.35) });
      }
    });

    // Proximity line
    const lineColor = proximityColor(closestDist);
    const cartA = positions[closestPair.a];
    const cartB = positions[closestPair.b];
    if (proximityLineRef.current && cartA && cartB) {
      proximityLineRef.current.show = true;
      proximityLineRef.current.positions = [cartA, cartB];
      proximityLineRef.current.material = Cesium.Material.fromType('Color', { color: lineColor });
      proximityLineRef.current.width = closestDist < DANGER_KM ? 2 : closestDist < WARNING_KM ? 1.5 : 1;
    }
  }, [currentTimeIndex, satLabelMap]);

  const level = distKm === null ? null : distKm < DANGER_KM ? 'DANGER' : distKm < WARNING_KM ? 'WARNING' : null;
  const badgeBg = level === 'DANGER' ? '#b91c1c' : level === 'WARNING' ? '#92400e' : '#1f2937';
  const badgeColor = level ? '#fff' : '#6b7280';

  return (
    <div style={{ position: 'relative', height: '100%', width: '100%' }}>
      <div ref={containerRef}
        style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: TIMELINE_H }} />

      {/* SGP4 badge */}
      <div style={{
        position: 'absolute', top: 8, right: 8, zIndex: 10,
        padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
        background: dataSource === 'sgp4' ? '#238636' : '#6e3810',
        color: '#fff', letterSpacing: '0.5px',
      }}>
        {dataSource === 'sgp4' ? '● SGP4' : '○ MOCK'}
      </div>

      {/* Proximity badge — only shown when 2+ satellites visible */}
      {distKm !== null && (
        <div style={{
          position: 'absolute', top: 36, right: 8, zIndex: 10,
          padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
          background: badgeBg, color: badgeColor, letterSpacing: '0.3px',
          minWidth: 120, textAlign: 'right',
        }}>
          {`${closestPairLabel}  ${Math.round(distKm).toLocaleString()} km${level ? `  ⚠ ${level}` : ''}`}
        </div>
      )}

      {/* Launch site info card */}
      {selectedLaunchSite && (
        <div style={{
          position: 'absolute', bottom: TIMELINE_H + 8, left: 8, zIndex: 20,
          background: '#161b22', border: '1px solid #f0a500',
          borderRadius: 8, padding: '12px 14px', width: 280,
          fontFamily: 'inherit', boxShadow: '0 4px 16px #000a',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
            <div>
              <div style={{ color: '#f0a500', fontSize: 13, fontWeight: 700 }}>{selectedLaunchSite.name}</div>
              <div style={{ color: '#8b949e', fontSize: 11, marginTop: 2 }}>{selectedLaunchSite.country} · {selectedLaunchSite.operator}</div>
            </div>
            <button onClick={() => setSelectedLaunchSite(null)} style={{
              background: 'none', border: 'none', color: '#484f58', cursor: 'pointer',
              fontSize: 16, lineHeight: 1, padding: '0 0 0 8px', flexShrink: 0,
            }}>✕</button>
          </div>
          <div style={{ color: '#c9d1d9', fontSize: 11, lineHeight: 1.5, marginBottom: 10 }}>
            {selectedLaunchSite.description}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 10px', fontSize: 11 }}>
            <span style={{ color: '#484f58' }}>First launch</span>
            <span style={{ color: '#e6edf3' }}>{selectedLaunchSite.firstLaunch}</span>
            <span style={{ color: '#484f58' }}>Vehicles</span>
            <span style={{ color: '#e6edf3' }}>{selectedLaunchSite.vehicles}</span>
            <span style={{ color: '#484f58' }}>Inclinations</span>
            <span style={{ color: '#e6edf3' }}>{selectedLaunchSite.inclinations}</span>
            <span style={{ color: '#484f58' }}>Coordinates</span>
            <span style={{ color: '#e6edf3' }}>{selectedLaunchSite.lat.toFixed(4)}°, {selectedLaunchSite.lon.toFixed(4)}°</span>
          </div>
        </div>
      )}

      {/* Launch sites toggle */}
      <button
        onClick={() => setShowLaunchSites(v => !v)}
        style={{
          position: 'absolute', top: 8, left: 8, zIndex: 10,
          background: showLaunchSites ? '#92400e' : '#1f2937',
          border: `1px solid ${showLaunchSites ? '#f0a500' : '#374151'}`,
          borderRadius: 4, color: showLaunchSites ? '#f0a500' : '#6b7280',
          fontSize: 11, fontWeight: 600, padding: '2px 8px', cursor: 'pointer',
          letterSpacing: '0.3px',
        }}
      >
        ▲ Launch Sites
      </button>

      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: TIMELINE_H }}>
        <Timeline
          positionCount={timelineMeta.posCount}
          startTimestamp={timelineMeta.startTimestamp}
          stepMs={timelineMeta.stepMs}
          nowIndex={timelineMeta.nowIndex}
        />
      </div>
    </div>
  );
}
