import { useEffect, useMemo, useRef, useState } from 'react'
import { FlyToInterpolator, WebMercatorViewport } from '@deck.gl/core'
import DeckGL from '@deck.gl/react'
import { ColumnLayer, PathLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import Map from 'react-map-gl/maplibre'
import 'maplibre-gl/dist/maplibre-gl.css'
import { IconX } from './Icons'
import type {
  ApiAlertDto,
  ApiNodeDto,
  BootstrapDepot,
  BootstrapPoi,
  BootstrapRoad,
  CatchmentMeta,
  CorridorEndpoint,
  RouteComparisonDto,
  TransitCorridorDto,
} from '../lib/api'
import type { CatchmentKey } from '../lib/mock'
import { BAND_RGBA, ROUTE_RGBA, THRESHOLDS, edgeColorRgba, type Mode } from '../lib/scoring'

const BASEMAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

interface Props {
  roads: BootstrapRoad[]
  edgeDepths: Record<string, number>
  nodes: ApiNodeDto[]
  alerts: ApiAlertDto[]
  depots: BootstrapDepot[]
  pois: BootstrapPoi[]
  transitCorridors: TransitCorridorDto[]
  showBusRoutes: boolean
  showHospitalCorridors: boolean
  catchments: Partial<Record<CatchmentKey, CatchmentMeta>>
  mode: Mode
  region: CatchmentKey | 'all'
  activeRoute: RouteComparisonDto | null
  activeRouteLabel: string | null
  onClearRoute: () => void
  selectedNodeId: string | null
  onClickNode: (nodeId: string, coord?: { lat: number; lng: number }, labelHint?: string) => void
  pickMode: 'inspect' | 'corridor'
  onCancelPick: () => void
  corridorOrigin: CorridorEndpoint | null
  corridorDest: CorridorEndpoint | null
  focusTarget: { lng: number; lat: number; zoom?: number; seq: number } | null
  focusRouteSeq?: number
  rightOpen?: boolean
  onSelectTransit?: (c: TransitCorridorDto) => void
}

interface ViewState {
  longitude: number
  latitude: number
  zoom: number
  pitch: number
  bearing: number
  transitionDuration?: number
  transitionInterpolator?: FlyToInterpolator
}

const DEFAULT_VIEW: ViewState = {
  longitude: 77.67,
  latitude: 12.92,
  zoom: 11.4,
  pitch: 45,
  bearing: -12,
}

/** Split a polyline into crisp dashed segments in WGS84 degrees without extra Deck.gl extensions. */
function buildDashedSegments(
  coords: [number, number][],
  dashDeg = 0.0009,
  gapDeg = 0.0006,
): [number, number][][] {
  if (coords.length < 2) return []
  const segments: [number, number][][] = []
  let drawing = true
  let distLeft = dashDeg
  let currentDash: [number, number][] = [coords[0]]

  for (let i = 1; i < coords.length; i++) {
    let [x0, y0] = coords[i - 1]
    const [x1, y1] = coords[i]
    let segLen = Math.hypot(x1 - x0, y1 - y0)
    if (segLen < 1e-9) continue

    while (segLen > 1e-9) {
      if (segLen <= distLeft) {
        if (drawing) currentDash.push([x1, y1])
        distLeft -= segLen
        segLen = 0
      } else {
        const t = distLeft / segLen
        const nx = x0 + (x1 - x0) * t
        const ny = y0 + (y1 - y0) * t
        if (drawing) {
          currentDash.push([nx, ny])
          if (currentDash.length >= 2) segments.push(currentDash)
          currentDash = []
        } else {
          currentDash = [[nx, ny]]
        }
        x0 = nx
        y0 = ny
        segLen -= distLeft
        drawing = !drawing
        distLeft = drawing ? dashDeg : gapDeg
      }
    }
  }
  if (drawing && currentDash.length >= 2) {
    segments.push(currentDash)
  }
  return segments
}

export function MapCanvas({
  roads,
  edgeDepths,
  nodes,
  alerts,
  depots,
  pois,
  transitCorridors,
  showBusRoutes,
  showHospitalCorridors,
  catchments,
  mode,
  region,
  activeRoute,
  activeRouteLabel,
  onClearRoute,
  selectedNodeId,
  onClickNode,
  pickMode,
  onCancelPick,
  corridorOrigin,
  corridorDest,
  focusTarget,
  focusRouteSeq,
  rightOpen = true,
  onSelectTransit,
}: Props) {
  const [viewState, setViewState] = useState<ViewState>(DEFAULT_VIEW)
  const [hoverInfo, setHoverInfo] = useState<{ text: string; x: number; y: number } | null>(null)
  const [size, setSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 })

  const containerRef = useRef<HTMLDivElement>(null)
  const dragStartRef = useRef<{ x: number; y: number } | null>(null)
  const lastLayerPickTsRef = useRef(0)
  const lastRegionRef = useRef<CatchmentKey | 'all'>('all')
  const onClickNodeRef = useRef(onClickNode)
  onClickNodeRef.current = onClickNode
  const onSelectTransitRef = useRef(onSelectTransit)
  onSelectTransitRef.current = onSelectTransit

  // Track viewport size for radar pulse projection
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const update = () => {
      const rect = el.getBoundingClientRect()
      setSize({ width: rect.width, height: rect.height })
    }
    update()
    const obs = new ResizeObserver(update)
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  // Gentle camera flyTo ONLY on explicit region switch
  useEffect(() => {
    if (lastRegionRef.current === region) return
    lastRegionRef.current = region
    if (region === 'all') {
      setViewState({
        ...DEFAULT_VIEW,
        transitionDuration: 700,
        transitionInterpolator: new FlyToInterpolator(),
      })
      return
    }
    const meta = catchments[region]
    if (meta) {
      setViewState((vs) => ({
        ...vs,
        latitude: meta.centroid[0],
        longitude: meta.centroid[1],
        zoom: 13.0,
        pitch: 45,
        transitionDuration: 700,
        transitionInterpolator: new FlyToInterpolator(),
      }))
    }
  }, [region, catchments])

  // Smooth animated flyTo when clicking a directive or Locate button, framed in open canvas area
  useEffect(() => {
    if (!focusTarget) return
    const targetZoom = focusTarget.zoom ?? 14.2
    if (size.width > 0 && size.height > 0 && size.width >= 768 && rightOpen) {
      const vp = new WebMercatorViewport({
        width: size.width,
        height: size.height,
        longitude: focusTarget.lng,
        latitude: focusTarget.lat,
        zoom: targetZoom,
        pitch: 45,
        bearing: -12,
      })
      const delta = 0.0045
      const fitted = vp.fitBounds(
        [
          [focusTarget.lng - delta, focusTarget.lat - delta],
          [focusTarget.lng + delta, focusTarget.lat + delta],
        ],
        { padding: { top: 84, bottom: 96, left: 60, right: 432 } },
      )
      setViewState((vs) => ({
        ...vs,
        longitude: fitted.longitude,
        latitude: fitted.latitude,
        zoom: Math.min(14.8, fitted.zoom, targetZoom),
        pitch: 45,
        bearing: -12,
        transitionDuration: 650,
        transitionInterpolator: new FlyToInterpolator(),
      }))
      return
    }
    setViewState((vs) => ({
      ...vs,
      longitude: focusTarget.lng,
      latitude: focusTarget.lat,
      zoom: targetZoom,
      pitch: 45,
      bearing: -12,
      transitionDuration: 650,
      transitionInterpolator: new FlyToInterpolator(),
    }))
  }, [focusTarget, rightOpen, size.width, size.height])

  // Smoothly frame full route bounds when a bus corridor or A->B route is chosen
  useEffect(() => {
    if (!focusRouteSeq || !activeRoute || size.width <= 0 || size.height <= 0) return
    const allPts: [number, number][] = [
      ...(activeRoute.stub_coords ?? []),
      ...activeRoute.standard.coords,
      ...activeRoute.safe.coords,
    ]
    if (allPts.length < 2) return
    let minLng = Infinity
    let maxLng = -Infinity
    let minLat = Infinity
    let maxLat = -Infinity
    for (const [lng, lat] of allPts) {
      if (lng < minLng) minLng = lng
      if (lng > maxLng) maxLng = lng
      if (lat < minLat) minLat = lat
      if (lat > maxLat) maxLat = lat
    }
    if (!Number.isFinite(minLng) || !Number.isFinite(minLat)) return
    const padLng = Math.max(0.0025, (maxLng - minLng) * 0.12)
    const padLat = Math.max(0.0025, (maxLat - minLat) * 0.12)
    const vp = new WebMercatorViewport({
      width: size.width,
      height: size.height,
      longitude: (minLng + maxLng) / 2,
      latitude: (minLat + maxLat) / 2,
      zoom: 13.0,
      pitch: 45,
      bearing: -12,
    })
    const padding =
      size.width >= 768
        ? { top: 88, bottom: 96, left: 64, right: rightOpen ? 440 : 64 }
        : { top: 170, bottom: Math.round(size.height * 0.54), left: 32, right: 32 }
    const fitted = vp.fitBounds(
      [
        [minLng - padLng, minLat - padLat],
        [maxLng + padLng, maxLat + padLat],
      ],
      { padding },
    )
    setViewState((vs) => ({
      ...vs,
      longitude: fitted.longitude,
      latitude: fitted.latitude,
      zoom: Math.min(14.8, Math.max(11.6, fitted.zoom)),
      pitch: 45,
      bearing: -12,
      transitionDuration: 650,
      transitionInterpolator: new FlyToInterpolator(),
    }))
  }, [focusRouteSeq, activeRoute, rightOpen, size.width, size.height])

  const filteredRoads = useMemo(() => {
    if (region === 'all') return roads
    return roads.filter((r) => r.catchment === region)
  }, [roads, region])

  const filteredNodes = useMemo(() => {
    if (region === 'all') return nodes
    return nodes.filter((n) => n.catchment === region)
  }, [nodes, region])

  const alertFloor = THRESHOLDS[mode].alertFloor

  // 3D water-column extrusion dataset: only flooded junctions so safe areas stay uncluttered
  const wetNodes = useMemo(() => {
    return filteredNodes
      .filter((n) => n.depth_m >= alertFloor || n.id === selectedNodeId)
      .slice()
      .sort((a, b) => a.depth_m - b.depth_m)
  }, [filteredNodes, alertFloor, selectedNodeId])

  const extrudedNodes = useMemo(() => {
    const isOverview = region === 'all' && viewState.zoom < 12.2
    const minDepth = isOverview ? 0.35 : alertFloor
    const maxCols = isOverview ? 120 : 220
    const eligible = wetNodes.filter((n) => n.depth_m >= minDepth || n.id === selectedNodeId)
    return eligible.length > maxCols ? eligible.slice(-maxCols) : eligible
  }, [wetNodes, region, viewState.zoom, alertFloor, selectedNodeId])

  const selectedNodeObj = useMemo(
    () => (selectedNodeId ? filteredNodes.find((n) => n.id === selectedNodeId) ?? null : null),
    [filteredNodes, selectedNodeId],
  )

  const filteredPois = useMemo(() => {
    if (region === 'all') return pois
    return pois.filter((p) => p.catchment === region)
  }, [pois, region])

  const hospitalPois = useMemo(
    () => filteredPois.filter((p) => p.category === 'hospital' || p.category === 'fire_station'),
    [filteredPois],
  )

  // Critical >= 0.30 m alerts for calm concentric radar pulse markers
  const criticalRadarAlerts = useMemo(() => {
    return alerts
      .filter((a) => a.depth_m >= 0.3 && (region === 'all' || a.catchment === region))
      .slice(0, 10)
  }, [alerts, region])

  // Project critical hazard coordinates into screen pixels for CSS radar rings
  const radarPins = useMemo(() => {
    if (size.width <= 0 || size.height <= 0 || criticalRadarAlerts.length === 0) return []
    const vp = new WebMercatorViewport({
      width: size.width,
      height: size.height,
      longitude: viewState.longitude,
      latitude: viewState.latitude,
      zoom: viewState.zoom,
      pitch: viewState.pitch ?? 0,
      bearing: viewState.bearing ?? 0,
    })
    return criticalRadarAlerts
      .map((a) => {
        if (!a.position) return null
        const [x, y] = vp.project([a.position[0], a.position[1]])
        if (!Number.isFinite(x) || !Number.isFinite(y)) return null
        if (x < -40 || x > size.width + 40 || y < -40 || y > size.height + 40) return null
        return { id: a.alert_id, x, y }
      })
      .filter((p): p is { id: string; x: number; y: number } => p !== null)
  }, [criticalRadarAlerts, size, viewState])

  const roadsLayer = useMemo(
    () =>
      new PathLayer<BootstrapRoad>({
        id: 'roads-layer',
        data: filteredRoads,
        getPath: (d) => d.path,
        getColor: (d) => edgeColorRgba(edgeDepths[d.id] ?? 0, mode),
        getWidth: (d) => {
          const depth = edgeDepths[d.id] ?? 0
          if (depth >= 0.25) return 4.5
          if (depth >= 0.08) return 2.8
          return 1.2
        },
        widthMinPixels: 1,
        widthMaxPixels: 5,
        updateTriggers: {
          getColor: [edgeDepths, mode],
          getWidth: [edgeDepths],
        },
      }),
    [filteredRoads, edgeDepths, mode],
  )

  const busOverlayLayer = useMemo(() => {
    if (!showBusRoutes || transitCorridors.length === 0) return null
    const basePaths = transitCorridors
      .filter((c) => c.route.standard.coords.length >= 2)
      .map((c) => ({
        corridor: c,
        id: `${c.route_id}-std`,
        name: c.route_name,
        status: c.status,
        path: c.route.standard.coords,
      }))
    const detourPaths = transitCorridors
      .filter((c) => c.route.safe.coords.length >= 2)
      .map((c) => ({
        corridor: c,
        id: `${c.route_id}-safe`,
        name: c.route_name,
        status: c.status,
        path:
          c.route.inter_catchment && c.route.stub_coords?.length
            ? [...c.route.stub_coords, ...c.route.safe.coords]
            : c.route.safe.coords,
      }))

    return [
      new PathLayer({
        id: 'bus-corridors-std-overlay',
        data: basePaths,
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: (d: { status: TransitCorridorDto['status'] }) =>
          d.status === 'SUSPENDED'
            ? [239, 68, 68, 210]
            : d.status === 'DIVERTED'
              ? [245, 158, 11, 145]
              : [16, 185, 129, 175],
        getWidth: (d: { status: TransitCorridorDto['status'] }) =>
          d.status === 'SUSPENDED' ? 5 : 3.5,
        widthMinPixels: 2.5,
        widthMaxPixels: 7,
        parameters: { depthCompare: 'always' },
        pickable: true,
        onClick: (info) => {
          const obj = info.object as { corridor?: TransitCorridorDto } | undefined
          if (obj?.corridor && onSelectTransitRef.current) {
            lastLayerPickTsRef.current = performance.now()
            onSelectTransitRef.current(obj.corridor)
            return true
          }
          return false
        },
        onHover: (info) => {
          const obj = info.object as { name?: string; status?: string } | undefined
          setHoverInfo(
            obj?.name
              ? {
                  text: `${obj.name} · ${
                    obj.status === 'SUSPENDED'
                      ? 'Held (Submerged)'
                      : obj.status === 'DIVERTED'
                        ? 'Regular path flooded (Click to inspect detour)'
                        : 'Clear'
                  }`,
                  x: info.x,
                  y: info.y,
                }
              : null,
          )
        },
      }),
      new PathLayer({
        id: 'bus-corridors-safe-overlay',
        data: detourPaths,
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: () => [16, 185, 129, 235],
        getWidth: 5.5,
        widthMinPixels: 3,
        widthMaxPixels: 8,
        parameters: { depthCompare: 'always' },
        pickable: true,
        onClick: (info) => {
          const obj = info.object as { corridor?: TransitCorridorDto } | undefined
          if (obj?.corridor && onSelectTransitRef.current) {
            lastLayerPickTsRef.current = performance.now()
            onSelectTransitRef.current(obj.corridor)
            return true
          }
          return false
        },
        onHover: (info) => {
          const obj = info.object as { name?: string; status?: string } | undefined
          setHoverInfo(
            obj?.name
              ? { text: `${obj.name} · Safe Detour (${obj.status})`, x: info.x, y: info.y }
              : null,
          )
        },
      }),
    ]
  }, [showBusRoutes, transitCorridors])

  const hospitalOverlayLayer = useMemo(() => {
    if (!showHospitalCorridors || hospitalPois.length === 0) return null
    return new ScatterplotLayer<BootstrapPoi>({
      id: 'hospital-corridors-overlay',
      data: hospitalPois,
      getPosition: (d) => [d.lng, d.lat],
      getFillColor: ROUTE_RGBA.hospital,
      getLineColor: [244, 245, 247, 230],
      stroked: true,
      lineWidthMinPixels: 1.5,
      getRadius: 70,
      radiusMinPixels: 6,
      radiusMaxPixels: 11,
      pickable: true,
      onClick: (info) => {
        if (info.object) {
          lastLayerPickTsRef.current = performance.now()
          onClickNodeRef.current(
            info.object.node_id,
            { lat: info.object.lat, lng: info.object.lng },
            info.object.name,
          )
          return true
        }
        return false
      },
      onHover: (info) =>
        setHoverInfo(
          info.object
            ? { text: `${info.object.name} (${info.object.category})`, x: info.x, y: info.y }
            : null,
        ),
    })
  }, [showHospitalCorridors, hospitalPois])

  const depotsLayer = useMemo(
    () =>
      new ScatterplotLayer<BootstrapDepot>({
        id: 'depots-layer',
        data: depots,
        getPosition: (d) => [d.lng, d.lat],
        getFillColor: ROUTE_RGBA.depot,
        getLineColor: [9, 11, 14, 230],
        stroked: true,
        lineWidthMinPixels: 1.5,
        getRadius: 48,
        radiusMinPixels: 4.5,
        radiusMaxPixels: 7.5,
        pickable: true,
        onClick: (info) => {
          if (info.object) {
            lastLayerPickTsRef.current = performance.now()
            onClickNodeRef.current(
              info.object.node_id,
              { lat: info.object.lat, lng: info.object.lng },
              info.object.name,
            )
            return true
          }
          return false
        },
        onHover: (info) =>
          setHoverInfo(
            info.object ? { text: `Depot · ${info.object.name}`, x: info.x, y: info.y } : null,
          ),
      }),
    [depots],
  )

  const floodNodesLayer = useMemo(
    () =>
      new ScatterplotLayer<ApiNodeDto>({
        id: 'flood-nodes-layer',
        data: wetNodes,
        getPosition: (d) => d.position,
        getRadius: (d) => (d.depth_m >= 0.3 ? 34 : 22),
        radiusMinPixels: 2.5,
        radiusMaxPixels: 7.5,
        getFillColor: (d) => {
          const c = BAND_RGBA[d.band] ?? BAND_RGBA.watch
          return [c[0], c[1], c[2], 210] as [number, number, number, number]
        },
        pickable: true,
        updateTriggers: {
          getFillColor: [mode],
          getRadius: [wetNodes],
        },
        onClick: (info) => {
          if (info.object) {
            lastLayerPickTsRef.current = performance.now()
            onClickNodeRef.current(
              info.object.id,
              { lat: info.object.position[1], lng: info.object.position[0] },
              info.object.name,
            )
            return true
          }
          return false
        },
        onHover: (info) =>
          setHoverInfo(
            info.object
              ? {
                  text: `${info.object.name} · ${(info.object.depth_m * 100).toFixed(0)} cm`,
                  x: info.x,
                  y: info.y,
                }
              : null,
          ),
      }),
    [wetNodes, mode],
  )

  const floodColumnsLayer = useMemo(
    () =>
      new ColumnLayer<ApiNodeDto>({
        id: 'flood-columns-layer',
        data: extrudedNodes,
        diskResolution: 6,
        radius: region === 'all' && viewState.zoom < 12.2 ? 32 : 22,
        extruded: true,
        elevationScale: 1,
        getPosition: (d) => d.position,
        getElevation: (d) => Math.max(16, Math.min(240, d.depth_m * 260)),
        getFillColor: (d) => {
          const c = BAND_RGBA[d.band] ?? BAND_RGBA.watch
          const baseAlpha = d.depth_m >= 0.3 ? 160 : 125
          return [c[0], c[1], c[2], activeRoute ? Math.round(baseAlpha * 0.45) : baseAlpha] as [
            number,
            number,
            number,
            number,
          ]
        },
        getLineColor: (d) =>
          d.id === selectedNodeId ? [244, 245, 247, 255] : [255, 255, 255, activeRoute ? 18 : 35],
        stroked: true,
        lineWidthMinPixels: 0.75,
        pickable: true,
        updateTriggers: {
          getFillColor: [mode, Boolean(activeRoute)],
          getElevation: [extrudedNodes],
          getLineColor: [selectedNodeId, Boolean(activeRoute)],
        },
        onClick: (info) => {
          if (info.object) {
            lastLayerPickTsRef.current = performance.now()
            onClickNodeRef.current(
              info.object.id,
              { lat: info.object.position[1], lng: info.object.position[0] },
              info.object.name,
            )
            return true
          }
          return false
        },
        onHover: (info) =>
          setHoverInfo(
            info.object
              ? {
                  text: `${info.object.name} · ${(info.object.depth_m * 100).toFixed(0)} cm`,
                  x: info.x,
                  y: info.y,
                }
              : null,
          ),
      }),
    [extrudedNodes, mode, region, viewState.zoom, selectedNodeId, activeRoute],
  )

  const selectedRingLayer = useMemo(() => {
    if (!selectedNodeObj?.position) return null
    return new ScatterplotLayer<ApiNodeDto>({
      id: 'selected-node-ring',
      data: [selectedNodeObj],
      getPosition: (d) => d.position,
      filled: false,
      stroked: true,
      getLineColor: [244, 245, 247, 245],
      lineWidthMinPixels: 2.5,
      getRadius: 72,
      radiusMinPixels: 10,
      radiusMaxPixels: 18,
      parameters: { depthCompare: 'always' },
      pickable: false,
    })
  }, [selectedNodeObj])

  const routeLayers = useMemo(() => {
    const out: unknown[] = []
    let stdFull: [number, number][] = []
    let safeFull: [number, number][] = []

    if (activeRoute) {
      stdFull = activeRoute.standard.coords.slice()
      if (
        activeRoute.inter_catchment &&
        activeRoute.stub_coords &&
        activeRoute.stub_coords.length > 0 &&
        stdFull.length > 0
      ) {
        const [ox, oy] = activeRoute.stub_coords[0]
        const [sx, sy] = stdFull[0]
        if (Math.hypot(ox - sx, oy - sy) > 1e-4) {
          stdFull = [[ox, oy], ...stdFull]
        }
      }

      if (activeRoute.safe.coords.length >= 2) {
        safeFull =
          activeRoute.inter_catchment && activeRoute.stub_coords?.length
            ? [...activeRoute.stub_coords, ...activeRoute.safe.coords]
            : activeRoute.safe.coords
      }

      // 1. Standard (shortest/naive) route casing + crisp red dashes
      if (stdFull.length >= 2) {
        out.push(
          new PathLayer({
            id: 'route-std-casing',
            data: [{ path: stdFull }],
            getPath: (d: { path: [number, number][] }) => d.path,
            getColor: [9, 11, 14, 225],
            getWidth: 9.5,
            widthMinPixels: 4.5,
            parameters: { depthCompare: 'always' },
          }),
        )
        const dashed = buildDashedSegments(stdFull, 0.00035, 0.00022)
        if (dashed.length > 0) {
          out.push(
            new PathLayer({
              id: 'route-std-dashed',
              data: dashed.map((path) => ({ path })),
              getPath: (d: { path: [number, number][] }) => d.path,
              getColor: ROUTE_RGBA.standard,
              getWidth: 6,
              widthMinPixels: 3,
              parameters: { depthCompare: 'always' },
            }),
          )
        }
      }

      // 2. Highlight submerged segments & bottleneck midpoints along standard route
      if (activeRoute.standard.flooded_segments.length > 0) {
        out.push(
          new PathLayer({
            id: 'route-flooded-layer',
            data: activeRoute.standard.flooded_segments.map((seg) => ({ path: seg })),
            getPath: (d: { path: [number, number][] }) => d.path,
            getColor: ROUTE_RGBA.floodedSegment,
            getWidth: 10.5,
            widthMinPixels: 4.5,
            parameters: { depthCompare: 'always' },
          }),
        )
        const bottlenecks = activeRoute.standard.flooded_segments
          .filter((s) => s.length >= 1)
          .map((s) => s[Math.floor(s.length / 2)])
        if (bottlenecks.length > 0) {
          out.push(
            new ScatterplotLayer({
              id: 'route-flooded-nodes',
              data: bottlenecks.map((pos) => ({ pos })),
              getPosition: (d: { pos: [number, number] }) => d.pos,
              getFillColor: [239, 68, 68, 255],
              getLineColor: [9, 11, 14, 255],
              stroked: true,
              lineWidthMinPixels: 1.5,
              getRadius: 28,
              radiusMinPixels: 4,
              radiusMaxPixels: 7,
              parameters: { depthCompare: 'always' },
              pickable: false,
            }),
          )
        }
      }

      // 3. Safe flood-free corridor (dark halo + vibrant solid emerald line on top)
      if (safeFull.length >= 2) {
        out.push(
          new PathLayer({
            id: 'route-safe-casing',
            data: [{ path: safeFull }],
            getPath: (d: { path: [number, number][] }) => d.path,
            getColor: [9, 11, 14, 240],
            getWidth: 11,
            widthMinPixels: 5.5,
            parameters: { depthCompare: 'always' },
          }),
          new PathLayer({
            id: 'route-safe-layer',
            data: [{ path: safeFull }],
            getPath: (d: { path: [number, number][] }) => d.path,
            getColor: ROUTE_RGBA.safe,
            getWidth: 7,
            widthMinPixels: 3.5,
            parameters: { depthCompare: 'always' },
          }),
        )
      }
    }

    const startCoord =
      corridorOrigin?.coord ??
      (stdFull.length >= 1 ? stdFull[0] : safeFull.length >= 1 ? safeFull[0] : undefined)
    const endCoord =
      corridorDest?.coord ??
      (stdFull.length >= 2
        ? stdFull[stdFull.length - 1]
        : safeFull.length >= 2
          ? safeFull[safeFull.length - 1]
          : undefined)

    const pins: { pos: [number, number]; tag: string; color: [number, number, number, number] }[] = []
    if (startCoord) {
      pins.push({ pos: startCoord, tag: 'A', color: [244, 245, 247, 255] })
    }
    if (endCoord) {
      pins.push({
        pos: endCoord,
        tag: 'B',
        color: activeRoute?.reachable === false ? [239, 68, 68, 255] : [16, 185, 129, 255],
      })
    }
    if (pins.length > 0) {
      out.push(
        new ScatterplotLayer({
          id: 'corridor-pins-layer',
          data: pins,
          getPosition: (d: { pos: [number, number] }) => d.pos,
          getFillColor: (d: { color: [number, number, number, number] }) => d.color,
          getLineColor: [9, 11, 14, 255],
          stroked: true,
          lineWidthMinPixels: 2,
          getRadius: 72,
          radiusMinPixels: 10,
          radiusMaxPixels: 14,
          parameters: { depthCompare: 'always' },
          pickable: false,
        }),
        new TextLayer({
          id: 'corridor-pin-labels',
          data: pins,
          getPosition: (d: { pos: [number, number] }) => d.pos,
          getText: (d: { tag: string }) => d.tag,
          getColor: [9, 11, 14, 255],
          getSize: 12,
          fontWeight: 700,
          fontFamily: 'Inter, system-ui, sans-serif',
          characterSet: ['A', 'B'],
          fontSettings: { sdf: true, fontSize: 64, buffer: 8 },
          getTextAnchor: 'middle',
          getAlignmentBaseline: 'center',
          parameters: { depthCompare: 'always' },
          pickable: false,
        }),
      )
    }
    return out
  }, [activeRoute, corridorOrigin, corridorDest])

  const layers = useMemo(
    () =>
      [
        roadsLayer,
        ...(busOverlayLayer ?? []),
        hospitalOverlayLayer,
        depotsLayer,
        floodNodesLayer,
        floodColumnsLayer,
        selectedRingLayer,
        ...routeLayers,
      ].filter(Boolean),
    [
      roadsLayer,
      busOverlayLayer,
      hospitalOverlayLayer,
      depotsLayer,
      floodNodesLayer,
      floodColumnsLayer,
      selectedRingLayer,
      routeLayers,
    ],
  )

  return (
    <div
      ref={containerRef}
      className="relative h-full w-full overflow-hidden bg-[#090B0E]"
      onMouseDown={(e) => {
        dragStartRef.current = { x: e.clientX, y: e.clientY }
      }}
      onMouseLeave={() => setHoverInfo(null)}
      onClick={(e) => {
        if (pickMode !== 'corridor') return
        const target = e.target as HTMLElement | null
        if (target?.closest('[data-map-hud="true"], button, select, input, a')) return
        if (performance.now() - lastLayerPickTsRef.current < 120) return
        const start = dragStartRef.current
        if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) >= 6) return
        const el = containerRef.current
        if (!el) return
        const rect = el.getBoundingClientRect()
        if (rect.width <= 0 || rect.height <= 0) return
        const vp = new WebMercatorViewport({
          width: rect.width,
          height: rect.height,
          longitude: viewState.longitude,
          latitude: viewState.latitude,
          zoom: viewState.zoom,
          pitch: viewState.pitch ?? 0,
          bearing: viewState.bearing ?? 0,
        })
        const [lng, lat] = vp.unproject([e.clientX - rect.left, e.clientY - rect.top])
        if (Number.isFinite(lat) && Number.isFinite(lng)) {
          lastLayerPickTsRef.current = performance.now()
          onClickNodeRef.current('', { lat, lng })
        }
      }}
    >
      <DeckGL
        viewState={viewState}
        controller={true}
        layers={layers as never[]}
        onViewStateChange={(evt) => setViewState(evt.viewState as ViewState)}
        onClick={(info) => {
          if (info.picked) return
          if (performance.now() - lastLayerPickTsRef.current < 120) return
          if (pickMode === 'corridor' && info.coordinate) {
            lastLayerPickTsRef.current = performance.now()
            onClickNodeRef.current(
              '',
              { lat: info.coordinate[1], lng: info.coordinate[0] },
            )
          }
        }}
        getCursor={() => (pickMode === 'corridor' ? 'crosshair' : hoverInfo ? 'pointer' : 'grab')}
      >
        <Map mapStyle={BASEMAP_STYLE} reuseMaps />
      </DeckGL>

      {/* Concentric radar pulse markers for >= 30 cm critical flood nodes */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden z-[5]">
        {radarPins.map((pin) => (
          <div
            key={pin.id}
            className="absolute"
            style={{ left: `${pin.x}px`, top: `${pin.y}px` }}
          >
            <span className="radar-ring absolute h-8 w-8 rounded-full border border-[#EF4444]/75" />
            <span className="radar-ring-delay absolute h-8 w-8 rounded-full border border-[#EF4444]/45" />
          </div>
        ))}
      </div>

      {/* Near-cursor minimal tooltip */}
      {hoverInfo && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed z-30 hud-glass rounded-lg px-2.5 py-1 text-xs font-medium text-[#F4F5F7] tnum whitespace-nowrap"
          style={{
            left: `${Math.min(Math.max(12, hoverInfo.x + 14), Math.max(12, size.width - 260))}px`,
            top: `${Math.min(Math.max(12, hoverInfo.y - 34), Math.max(12, size.height - 44))}px`,
          }}
        >
          {hoverInfo.text}
        </div>
      )}

      {/* Corridor Picker Prompt */}
      {pickMode === 'corridor' && (
        <div
          data-map-hud="true"
          className="fixed bottom-5 left-1/2 -translate-x-1/2 z-30 hud-glass rounded-full px-4 py-2 flex items-center gap-3 text-xs text-[#F4F5F7]"
        >
          <span className="h-2 w-2 rounded-full bg-[#10B981]" />
          <span className="font-medium">
            {corridorOrigin
              ? `Origin locked (${corridorOrigin.label}) — click map for Destination B`
              : 'Click any street junction on the map to set Origin A'}
          </span>
          <button
            type="button"
            onClick={onCancelPick}
            className="rounded-full border border-white/[0.12] bg-white/[0.06] hover:bg-white/[0.12] px-2.5 py-0.5 text-[11px] font-medium cursor-pointer tactile-press"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Clear Route Legend Card when a route is drawn */}
      {activeRoute && pickMode !== 'corridor' && (
        <div
          data-map-hud="true"
          className="fixed top-[108px] left-3 right-3 md:top-auto md:bottom-4 md:left-4 md:right-auto md:max-w-md z-10 hud-glass rounded-xl px-3.5 py-2.5 text-xs text-[#F4F5F7] flex items-start gap-3"
        >
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="font-medium text-[#F4F5F7] truncate">
              {activeRouteLabel || 'Corridor Route'}
            </div>
            <div className="flex flex-col gap-1 font-mono text-[11px] tnum">
              <div className="flex items-center gap-2 text-[#7DD3FC]">
                <span
                  aria-hidden="true"
                  className="inline-block w-4 h-0.5 border-t-2 border-dashed border-[#38BDF8] shrink-0"
                />
                <span>
                  Standard Route:{' '}
                  {activeRoute.standard.eta_min !== null
                    ? `${activeRoute.standard.eta_min.toFixed(1)} min`
                    : 'Blocked'}{' '}
                  · {activeRoute.standard.flooded_crossings} flooded
                </span>
              </div>
              <div
                className={`flex items-center gap-2 ${
                  activeRoute.reachable ? 'text-[#6EE7B7]' : 'text-[#EF4444]'
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`inline-block w-4 h-0.5 rounded-full shrink-0 ${
                    activeRoute.reachable ? 'bg-[#10B981]' : 'bg-[#EF4444]/60'
                  }`}
                />
                <span>
                  Safe Detour:{' '}
                  {activeRoute.reachable && activeRoute.safe.eta_min !== null
                    ? `${activeRoute.safe.eta_min.toFixed(1)} min · Dry corridor`
                    : 'Impassable (no dry path)'}
                </span>
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClearRoute}
            aria-label="Clear active route"
            className="shrink-0 rounded-lg p-1 text-[#8E95A2] hover:text-[#F4F5F7] hover:bg-white/[0.08] cursor-pointer tactile-press"
          >
            <IconX className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  )
}
