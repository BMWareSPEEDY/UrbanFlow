import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, MotionConfig, motion } from 'framer-motion'
import { CommandPanel, type CommandTab } from './components/CommandPanel'
import { ControlIsland } from './components/ControlIsland'
import { MapCanvas } from './components/MapCanvas'
import { NodeInspector } from './components/NodeInspector'
import { DEFAULT_CONFIG, SetupScreen, type CommandConfig } from './components/SetupScreen'
import {
  createSessionApi,
  dismissAlertApi,
  dispatchAlertApi,
  fetchBootstrap,
  fetchNodeInspectApi,
  fetchScenarioApi,
  reopenBarrierApi,
  routeCorridorApi,
  tickClockApi,
  vetoBarrierApi,
  type ApiAlertDto,
  type ApiNodeDto,
  type BootstrapResponse,
  type CorridorEndpoint,
  type DismissReason,
  type FleetSummaryDto,
  type RouteComparisonDto,
  type ScenarioResponse,
  type TransitCorridorDto,
  type VehicleClass,
} from './lib/api'
import { DEPOTS, mockScene, type CatchmentKey } from './lib/mock'
import type { Mode } from './lib/scoring'

const MOCK_REGIONS: CatchmentKey[] = ['hsr', 'bellandur', 'whitefield', 'ecity', 'koramangala']
function catchmentForMockDepot(i: number): CatchmentKey {
  return MOCK_REGIONS[i % MOCK_REGIONS.length]
}

const ACTIVE_UNIT_STATES = new Set([
  'PENDING_CLOSE',
  'EN_ROUTE',
  'DEWATERING',
  'ON_SITE',
  'RETURNING',
])

function buildMockFallback(
  cfg: CommandConfig,
  rain: number,
  mode: Mode,
  region: CatchmentKey | 'all',
  simClockMin: number,
): {
  bootstrap: Partial<BootstrapResponse>
  scenario: ScenarioResponse
} {
  const sc = mockScene(rain, mode, region)
  const edgeDepths: Record<string, number> = {}
  const roads = sc.roads.map((r) => {
    edgeDepths[r.id] = r.depth
    return {
      id: r.id,
      path: r.path,
      highway: r.highway,
      catchment: r.catchment,
      length_m: 120,
    }
  })

  const nodes: ApiNodeDto[] = sc.nodes.map((n) => ({
    ...n,
    depth_m: n.depth,
    primary_asset: n.assets[0] ?? 'street',
    sink_ratio: Math.min(1, n.sink / 0.5),
    is_basement: false,
    swmm_depth_m: n.depth - n.swmmDeltaCm / 100,
    ttp_min: 22,
  }))

  const alerts: ApiAlertDto[] = sc.alerts.map((a, idx) => {
    const uclass =
      a.action === 'barrier' || a.action === 'barrier_closure'
        ? 'barrier'
        : a.band === 'watch'
          ? 'warden'
          : 'pump'
    const pool = uclass === 'pump' ? cfg.pumps : uclass === 'barrier' ? cfg.barriers : cfg.wardens
    const ok = idx < pool
    return {
      ...a,
      depth_m: a.depth,
      primary_asset: a.assets[0] ?? 'street',
      sink_ratio: Math.min(1, a.sink / 0.5),
      is_basement: false,
      swmm_depth_m: a.depth - a.swmmDeltaCm / 100,
      alert_id: `MOCK-${a.id}`,
      affected_nodes: 1,
      cluster_node_ids: [a.id],
      extent_m: 0,
      action:
        uclass === 'barrier'
          ? 'barrier_closure'
          : uclass === 'warden'
            ? 'warden_diversion'
            : 'pump_dispatch',
      action_label: a.actionLabel,
      unit_class: uclass,
      underpass_poi_id: null,
      ttp_min: a.ttpMin,
      ttp_source: 'playback',
      mode,
      deploy_where: `${a.name} (${a.catchment.toUpperCase()})`,
      deploy_what: a.actionLabel,
      deploy_when: ok
        ? `Deploy NOW · ETA ${a.etaMin.toFixed(0)}m vs peak ${a.ttpMin.toFixed(0)}m`
        : `SHORTAGE · Exhausted (${pool} configured)`,
      dispatch_status: ok ? 'PENDING' : 'INFEASIBLE',
      eta_min: ok ? a.etaMin : null,
      infeasible_reason: ok ? null : 'no_unit',
      infeasible_message: ok ? null : `0 ${uclass}s available (${pool} configured)`,
      inter_catchment: false,
      veto_remaining_sec: 0,
      feasible: ok,
    }
  })

  return {
    bootstrap: {
      roads,
      pois: [],
      depots: DEPOTS.map((d, i) => ({
        id: `DEP-${i + 1}`,
        name: d.name,
        region: catchmentForMockDepot(i),
        node_id: d.id,
        lat: d.position[1],
        lng: d.position[0],
        elevation: 895,
        asset_classes: ['pump', 'warden'],
      })),
      catchments: undefined,
    },
    scenario: {
      simulation: true,
      scenario_key: `mock|${region}|${rain}|${mode}`,
      region,
      rain_mmhr: rain,
      duration_min: cfg.duration,
      mode,
      sim_clock_min: simClockMin,
      sim_ts: `T+${String(Math.round(simClockMin)).padStart(3, '0')}m`,
      alerts,
      nodes,
      edge_depths: edgeDepths,
      stats: {
        inference_latency_ms: 85.5,
        triage_wall_ms: 14,
        raw_above_floor: nodes.length,
        raw_eligible: alerts.length,
        dedup_alerts: alerts.length,
        suppressed: sc.suppressed,
        critical_nodes: sc.criticalNodes,
        blocked_km: sc.blockedKm,
        total_edges: sc.totalEdges,
        mean_eta_min: 9.4,
      },
      fleet: {
        counts: {
          pump: { total: cfg.pumps, idle: cfg.pumps, active: 0, standby: 0 },
          barrier: { total: cfg.barriers, idle: cfg.barriers, active: 0, standby: 0 },
          warden: { total: cfg.wardens, idle: cfg.wardens, active: 0, standby: 0 },
        },
        units: [],
        fleet_oversized: cfg.pumps > 18,
      },
      transit: {
        corridors: [],
        summary: { normal: 0, diverted: 0, suspended: 0 },
      },
    },
  }
}

export function App() {
  const isMock =
    typeof window !== 'undefined' && window.location.search.includes('mock=1')

  const [config, setConfig] = useState<CommandConfig | null>(null)
  const [setupBusy, setSetupBusy] = useState(false)
  const [setupError, setSetupError] = useState<string | null>(null)
  const [degraded, setDegraded] = useState(false)

  const [bootstrap, setBootstrap] = useState<BootstrapResponse | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [scenario, setScenario] = useState<ScenarioResponse | null>(null)
  const [fleet, setFleet] = useState<FleetSummaryDto | null>(null)

  const [activeTab, setActiveTab] = useState<CommandTab>('dispatch')
  const [rightOpen, setRightOpen] = useState(true)

  const [rain, setRain] = useState(DEFAULT_CONFIG.rain)
  const [duration, setDuration] = useState(DEFAULT_CONFIG.duration)
  const [mode, setMode] = useState<Mode>(DEFAULT_CONFIG.mode)
  const [region, setRegion] = useState<CatchmentKey | 'all'>(DEFAULT_CONFIG.region)
  const [simClockMin, setSimClockMin] = useState(0)

  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null)
  const [inspectedNode, setInspectedNode] = useState<ApiNodeDto | null>(null)
  const [activeRoute, setActiveRoute] = useState<RouteComparisonDto | null>(null)
  const [activeRouteLabel, setActiveRouteLabel] = useState<string | null>(null)
  const [activeTransitId, setActiveTransitId] = useState<string | null>(null)

  const [pickMode, setPickMode] = useState<'inspect' | 'corridor'>('inspect')
  const [vehicleClass, setVehicleClass] = useState<VehicleClass>('bus')
  const [corridorOrigin, setCorridorOrigin] = useState<CorridorEndpoint | null>(null)
  const [corridorDest, setCorridorDest] = useState<CorridorEndpoint | null>(null)
  const [showBusRoutes, setShowBusRoutes] = useState(false)
  const [showHospitalCorridors, setShowHospitalCorridors] = useState(false)
  const [focusTarget, setFocusTarget] = useState<{
    lng: number
    lat: number
    zoom?: number
    seq: number
  } | null>(null)
  const [focusRouteSeq, setFocusRouteSeq] = useState(0)
  const [dismissFeedback, setDismissFeedback] = useState<string | null>(null)
  const dismissTimerRef = useRef<number | null>(null)

  const scenarioSeqRef = useRef(0)

  // Load static roads/POIs/depots once
  useEffect(() => {
    if (isMock) return
    let cancelled = false
    fetchBootstrap()
      .then((b) => {
        if (!cancelled) setBootstrap(b)
      })
      .catch(() => {
        if (!cancelled) setDegraded(true)
      })
    return () => {
      cancelled = true
    }
  }, [isMock])

  // Session creation from SetupScreen
  const handleEnterCommand = async (cfg: CommandConfig) => {
    setSetupBusy(true)
    setSetupError(null)
    setRain(cfg.rain)
    setDuration(cfg.duration)
    setMode(cfg.mode)
    setRegion(cfg.region)
    setSimClockMin(0)
    setActiveRoute(null)
    setActiveRouteLabel(null)
    setActiveTransitId(null)
    setSelectedAlertId(null)
    setInspectedNode(null)
    setActiveTab('dispatch')
    setRightOpen(true)

    if (isMock) {
      setConfig(cfg)
      setSetupBusy(false)
      return
    }

    try {
      const ses = await createSessionApi(cfg)
      setSessionId(ses.session_id)
      setFleet(ses.fleet)
      setDegraded(false)
      setConfig(cfg)
    } catch (err) {
      setDegraded(true)
      setSetupError(
        `Backend API unreachable (${(err as Error).message}). Entering offline simulation.`,
      )
      setConfig(cfg)
    } finally {
      setSetupBusy(false)
    }
  }

  // Scenario update (debounced on rain/duration changes, instant on region/mode)
  useEffect(() => {
    if (!config) return
    if (isMock || degraded || !sessionId) {
      const fb = buildMockFallback(config, rain, mode, region, simClockMin)
      setScenario(fb.scenario)
      setFleet(fb.scenario.fleet)
      return
    }

    const reqId = ++scenarioSeqRef.current
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const sc = await fetchScenarioApi(
          {
            session_id: sessionId,
            region,
            rain_mmhr: rain,
            duration_min: duration,
            mode,
          },
          controller.signal,
        )
        if (scenarioSeqRef.current !== reqId) return
        setScenario(sc)
        if (sc.fleet) setFleet(sc.fleet)
        setSimClockMin(sc.sim_clock_min)
      } catch (err) {
        if ((err as Error).name === 'AbortError') return
        setDegraded(true)
      }
    }, 90)

    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [config, isMock, degraded, sessionId, region, rain, duration, mode])

  const hasActiveDeployment = useMemo(
    () => Boolean(fleet?.units.some((u) => ACTIVE_UNIT_STATES.has(u.state))),
    [fleet],
  )
  const hasPendingClose = useMemo(
    () => Boolean(fleet?.units.some((u) => u.state === 'PENDING_CLOSE')),
    [fleet],
  )

  const refreshScenarioNow = useCallback(async () => {
    if (!sessionId || degraded || isMock) return
    try {
      const sc = await fetchScenarioApi({
        session_id: sessionId,
        region,
        rain_mmhr: rain,
        duration_min: duration,
        mode,
      })
      setScenario(sc)
      if (sc.fleet) setFleet(sc.fleet)
    } catch {
      // Keep current scenario state cleanly
    }
  }, [sessionId, degraded, isMock, region, rain, duration, mode])

  // Quietly advance simulation clock when any unit is actively deployed
  const tickInFlightRef = useRef(false)
  useEffect(() => {
    if (!hasActiveDeployment || !config || !sessionId || degraded || isMock) return
    const deltaMin = hasPendingClose ? 0.1 : 0.5
    const id = window.setInterval(async () => {
      if (tickInFlightRef.current) return
      tickInFlightRef.current = true
      try {
        const tk = await tickClockApi(sessionId, deltaMin)
        setSimClockMin(tk.sim_clock_min)
        setFleet(tk.fleet)
        setScenario((prev) =>
          prev
            ? {
                ...prev,
                fleet: tk.fleet,
                transit: tk.transit,
                sim_ts: tk.sim_ts,
                sim_clock_min: tk.sim_clock_min,
              }
            : prev,
        )
      } catch {
        // Stop quiet background tick errors gracefully
      } finally {
        tickInFlightRef.current = false
      }
    }, 1000)
    return () => window.clearInterval(id)
  }, [hasActiveDeployment, hasPendingClose, config, sessionId, degraded, isMock])

  // Sync alert status/progress with live fleet unit updates
  const mergedAlerts = useMemo(() => {
    const raw = scenario?.alerts ?? []
    if (!fleet?.units?.length) return raw
    const byAlertId = new Map(
      fleet.units
        .filter((u) => u.assigned_alert_id)
        .map((u) => [u.assigned_alert_id!, u]),
    )
    return raw.map((a) => {
      const u = byAlertId.get(a.alert_id)
      if (!u) return a
      return {
        ...a,
        dispatch_status: 'ASSIGNED' as const,
        unit: u.unit_id,
        unit_state: u.state,
        remaining_min: u.remaining_min,
        veto_remaining_sec: u.veto_remaining_sec,
      }
    })
  }, [scenario?.alerts, fleet?.units])

  const handleTick5m = async () => {
    if (!sessionId || degraded || isMock) {
      setSimClockMin((m) => m + 5)
      return
    }
    try {
      const tk = await tickClockApi(sessionId, 5.0)
      setSimClockMin(tk.sim_clock_min)
      setFleet(tk.fleet)
      setScenario((prev) =>
        prev
          ? {
              ...prev,
              fleet: tk.fleet,
              transit: tk.transit,
              sim_ts: tk.sim_ts,
              sim_clock_min: tk.sim_clock_min,
            }
          : prev,
      )
      await refreshScenarioNow()
    } catch {
      // Ignore step failure safely
    }
  }

  const recoverSession = useCallback(async (): Promise<string | null> => {
    if (!config || degraded || isMock) return null
    try {
      const ses = await createSessionApi({
        operator: config.operator,
        region,
        rain,
        duration,
        mode,
        pumps: config.pumps,
        barriers: config.barriers,
        wardens: config.wardens,
      })
      setSessionId(ses.session_id)
      setFleet(ses.fleet)
      return ses.session_id
    } catch {
      return null
    }
  }, [config, degraded, isMock, region, rain, duration, mode])

  const handleApproveDispatch = useCallback(
    async (a: ApiAlertDto) => {
      if (!sessionId || degraded || isMock) {
        const prefix =
          a.unit_class === 'barrier' ? 'BAR-01' : a.unit_class === 'warden' ? 'WRD-01' : 'PUMP-01'
        setScenario((prev) =>
          prev
            ? {
                ...prev,
                alerts: prev.alerts.map((x) =>
                  x.alert_id === a.alert_id
                    ? {
                        ...x,
                        dispatch_status: 'ASSIGNED',
                        unit: x.unit ?? prefix,
                        unit_state: a.unit_class === 'barrier' ? 'PENDING_CLOSE' : 'EN_ROUTE',
                        remaining_min: x.eta_min ?? 8,
                        veto_remaining_sec: a.unit_class === 'barrier' ? 60 : 0,
                      }
                    : x,
                ),
              }
            : prev,
        )
        return
      }
      let activeSid = sessionId
      let res
      try {
        res = await dispatchAlertApi(activeSid, a.alert_id)
      } catch {
        const recovered = await recoverSession()
        if (!recovered) return
        activeSid = recovered
        res = await dispatchAlertApi(activeSid, a.alert_id)
      }
      setFleet(res.fleet)
      if (res.route) {
        setActiveRoute(res.route)
        setActiveRouteLabel(`${res.unit?.unit_id ?? 'Unit'} → ${a.name}`)
      }
      await refreshScenarioNow()
    },
    [sessionId, degraded, isMock, recoverSession, refreshScenarioNow],
  )

  const showDismissNotice = (text: string) => {
    setDismissFeedback(text)
    if (dismissTimerRef.current !== null) {
      window.clearTimeout(dismissTimerRef.current)
    }
    dismissTimerRef.current = window.setTimeout(() => {
      setDismissFeedback(null)
    }, 8000)
  }

  const handleDismissAlert = async (a: ApiAlertDto, reason: DismissReason) => {
    const clusterIds = Array.from(new Set([a.id, ...(a.cluster_node_ids ?? [])]))
    const mult = reason === 'insufficient_confidence' ? 0.5 : 0.0
    setScenario((prev) =>
      prev
        ? {
            ...prev,
            alerts: prev.alerts.map((x) =>
              x.alert_id === a.alert_id
                ? { ...x, dispatch_status: 'DISMISSED', dismiss_reason: reason }
                : x,
            ),
            nodes: prev.nodes.map((n) =>
              clusterIds.includes(n.id)
                ? {
                    ...n,
                    depth_m: Number((n.depth_m * mult).toFixed(4)),
                    band: n.depth_m * mult < 0.02 ? 'dry' : n.band,
                  }
                : n,
            ),
          }
        : prev,
    )
    if (selectedAlertId === a.alert_id) setSelectedAlertId(null)
    if (!sessionId || degraded || isMock) {
      showDismissNotice(
        reason === 'false_alarm'
          ? `False alarm logged · Cleared ${clusterIds.length} cluster junction(s)`
          : reason === 'already_handled'
            ? `Crew handled · Cleared ${clusterIds.length} junction(s)`
            : `Confidence adjusted · Halved depth (0.5x) on ${clusterIds.length} junction(s)`,
      )
      return
    }
    let activeSid = sessionId
    let res
    try {
      res = await dismissAlertApi(activeSid, a.alert_id, reason, a.id, a.cluster_node_ids)
    } catch {
      const recovered = await recoverSession()
      if (!recovered) return
      activeSid = recovered
      res = await dismissAlertApi(activeSid, a.alert_id, reason, a.id, a.cluster_node_ids)
    }
    if (res.calibration?.summary) {
      showDismissNotice(res.calibration.summary)
    }
    await refreshScenarioNow()
    if (corridorOrigin && corridorDest) {
      try {
        const rt = await routeCorridorApi({
          session_id: activeSid,
          origin: corridorOrigin.spec,
          dest: corridorDest.spec,
          vehicle: vehicleClass,
          rain_mmhr: rain,
          duration_min: duration,
          mode,
          region,
        })
        setActiveRoute(rt)
      } catch {
        // Keep current route safely
      }
    }
  }

  const handleVetoBarrier = async (unitId: string) => {
    if (!sessionId || degraded || isMock) return
    try {
      const res = await vetoBarrierApi(sessionId, unitId)
      setFleet(res.fleet)
      await refreshScenarioNow()
    } catch {
      // Ignore veto error
    }
  }

  const handleReopenBarrier = async (unitId: string) => {
    if (!sessionId || degraded || isMock) return
    try {
      const res = await reopenBarrierApi(sessionId, unitId)
      setFleet(res.fleet)
      await refreshScenarioNow()
    } catch {
      // Ignore reopen error
    }
  }

  const runCorridorRoute = useCallback(
    async (orig: CorridorEndpoint, dest: CorridorEndpoint, veh: VehicleClass) => {
      if (degraded || isMock) return
      setCorridorOrigin(orig)
      setCorridorDest(dest)
      try {
        const rt = await routeCorridorApi({
          session_id: sessionId ?? undefined,
          origin: orig.spec,
          dest: dest.spec,
          vehicle: veh,
          rain_mmhr: rain,
          duration_min: duration,
          mode,
          region,
        })
        setActiveRoute(rt)
        setActiveRouteLabel(`${orig.label} → ${dest.label}`)
        setFocusRouteSeq(Date.now())
      } catch {
        // Keep UI calm on routing failure
      }
    },
    [degraded, isMock, sessionId, rain, duration, mode, region],
  )

  const inspectNodeById = useCallback(
    async (nodeId: string) => {
      if (!nodeId) return
      const localMatch = scenario?.nodes.find((n) => n.id === nodeId)
      if (localMatch) {
        setInspectedNode(localMatch)
        return
      }
      if (!degraded && !isMock) {
        try {
          const res = await fetchNodeInspectApi(nodeId, {
            session_id: sessionId ?? undefined,
            rain_mmhr: rain,
            duration_min: duration,
            mode,
          })
          setInspectedNode(res.node)
        } catch {
          // Ignore unknown click
        }
      }
    },
    [scenario, degraded, isMock, sessionId, rain, duration, mode],
  )

  const handleClickMapNode = useCallback(
    async (nodeId: string, coord?: { lat: number; lng: number }, labelHint?: string) => {
      if (pickMode === 'corridor') {
        const spec: CorridorEndpoint['spec'] | undefined = nodeId || coord
        if (!spec) return
        const localNode = nodeId ? scenario?.nodes.find((n) => n.id === nodeId) : undefined
        const resolvedCoord: [number, number] | undefined = coord
          ? [coord.lng, coord.lat]
          : localNode?.position
        const label =
          labelHint ||
          localNode?.name ||
          (nodeId ? `Junction ${nodeId.slice(-5)}` : `${coord!.lat.toFixed(4)}, ${coord!.lng.toFixed(4)}`)
        const endpoint: CorridorEndpoint = { spec, label, coord: resolvedCoord }

        if (!corridorOrigin || corridorDest) {
          setCorridorDest(null)
          setCorridorOrigin(endpoint)
          return
        }
        await runCorridorRoute(corridorOrigin, endpoint, vehicleClass)
        setPickMode('inspect')
        return
      }

      await inspectNodeById(nodeId)
    },
    [pickMode, corridorOrigin, corridorDest, vehicleClass, scenario, runCorridorRoute, inspectNodeById],
  )

  const handleSelectAlert = (a: ApiAlertDto) => {
    setSelectedAlertId(a.alert_id)
    setInspectedNode(a)
    if (a.route) {
      setActiveRoute(a.route)
      setActiveRouteLabel(`${a.unit ?? a.action_label} → ${a.name}`)
      if (
        a.route.inter_catchment &&
        (a.route.stub_coords?.length ?? 0) <= 2 &&
        sessionId &&
        !degraded &&
        !isMock
      ) {
        routeCorridorApi({
          session_id: sessionId,
          origin: a.route.origin_node,
          dest: a.route.dest_node,
          vehicle: a.route.vehicle === 'warden' ? 'warden' : 'pump_truck',
          rain_mmhr: rain,
          duration_min: duration,
          mode,
          region,
        })
          .then((rt) => {
            if (rt.reachable || rt.standard.coords.length >= 2) {
              setActiveRoute(rt)
            }
          })
          .catch(() => {
            /* keep existing route preview on transient failure */
          })
      }
    }
    if (a.position) {
      setFocusTarget({ lng: a.position[0], lat: a.position[1], zoom: 14.3, seq: Date.now() })
    }
  }

  const handleLocateAlert = (a: ApiAlertDto) => {
    setSelectedAlertId(a.alert_id)
    setInspectedNode(a)
    if (a.position) {
      setFocusTarget({ lng: a.position[0], lat: a.position[1], zoom: 14.4, seq: Date.now() })
    }
  }

  const handleSelectTransit = (c: TransitCorridorDto) => {
    setActiveTransitId(c.route_id)
    setActiveRoute(c.route)
    setActiveRouteLabel(c.route_name)
    setActiveTab('corridors')
    setFocusRouteSeq(Date.now())
  }

  const handleReconfigure = () => {
    setSessionId(null)
    setScenario(null)
    setFleet(null)
    setActiveRoute(null)
    setActiveRouteLabel(null)
    setSelectedAlertId(null)
    setActiveTransitId(null)
    setInspectedNode(null)
    setCorridorOrigin(null)
    setCorridorDest(null)
    setDegraded(false)
    setSimClockMin(0)
    setConfig(null)
  }

  // Keyboard shortcuts: 1-6 select top alerts, Enter dispatches, Esc clears, R toggles Red-Alert
  useEffect(() => {
    if (!config) return
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
      const visible = mergedAlerts.filter((a) => a.dispatch_status !== 'DISMISSED')
      if (e.key >= '1' && e.key <= '6') {
        const idx = Number(e.key) - 1
        if (visible[idx]) handleSelectAlert(visible[idx])
      } else if (e.key === 'Enter' && selectedAlertId) {
        const hit = visible.find((a) => a.alert_id === selectedAlertId)
        if (hit && hit.feasible && hit.dispatch_status === 'PENDING') {
          e.preventDefault()
          handleApproveDispatch(hit)
        }
      } else if (e.key === 'Escape') {
        setInspectedNode(null)
        setSelectedAlertId(null)
        setActiveRoute(null)
        setActiveRouteLabel(null)
        setActiveTransitId(null)
        setCorridorOrigin(null)
        setCorridorDest(null)
        setPickMode('inspect')
      } else if (e.key === '\\') {
        setRightOpen((v) => !v)
      } else if (e.key === 'r' || e.key === 'R') {
        setMode((m) => (m === 'normal' ? 'red_alert' : 'normal'))
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [config, mergedAlerts, selectedAlertId, handleApproveDispatch])

  const roads = useMemo(() => {
    if (bootstrap?.roads?.length) return bootstrap.roads
    if (config) return buildMockFallback(config, rain, mode, region, 0).bootstrap.roads ?? []
    return []
  }, [bootstrap, config, rain, mode, region])

  const activeAlerts = mergedAlerts.filter((a) => a.dispatch_status !== 'DISMISSED')
  const matchingInspectorAlert = inspectedNode
    ? activeAlerts.find((a) => a.id === inspectedNode.id)
    : undefined

  return (
    <MotionConfig reducedMotion="user">
      <AnimatePresence mode="wait">
        {!config ? (
          <SetupScreen
            key="setup"
            initial={DEFAULT_CONFIG}
            busy={setupBusy}
            error={setupError}
            onSubmit={handleEnterCommand}
          />
        ) : (
          <motion.div
            key="command"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="relative h-screen w-screen overflow-hidden bg-[#090B0E] text-[#F4F5F7]"
          >
            {/* Full-Bleed 3D Map Canvas */}
            <main className="relative h-full w-full">
              <MapCanvas
                roads={roads}
                edgeDepths={scenario?.edge_depths ?? {}}
                nodes={scenario?.nodes ?? []}
                alerts={activeAlerts}
                depots={bootstrap?.depots ?? []}
                pois={bootstrap?.pois ?? []}
                transitCorridors={scenario?.transit.corridors ?? []}
                showBusRoutes={showBusRoutes}
                showHospitalCorridors={showHospitalCorridors}
                catchments={bootstrap?.catchments ?? {}}
                mode={mode}
                region={region}
                activeRoute={activeRoute}
                activeRouteLabel={activeRouteLabel}
                onClearRoute={() => {
                  setActiveRoute(null)
                  setActiveRouteLabel(null)
                  setActiveTransitId(null)
                  setSelectedAlertId(null)
                  setCorridorOrigin(null)
                  setCorridorDest(null)
                }}
                selectedNodeId={inspectedNode?.id ?? null}
                onClickNode={handleClickMapNode}
                pickMode={pickMode}
                onCancelPick={() => setPickMode('inspect')}
                corridorOrigin={corridorOrigin}
                corridorDest={corridorDest}
                focusTarget={focusTarget}
                focusRouteSeq={focusRouteSeq}
                rightOpen={rightOpen}
                onSelectTransit={handleSelectTransit}
              />
            </main>

            {/* Surface 1: Top-Left Compact Floating Control Island */}
            <ControlIsland
              region={region}
              setRegion={setRegion}
              rain={rain}
              setRain={setRain}
              mode={mode}
              setMode={setMode}
              degraded={degraded}
              onReconfigure={handleReconfigure}
            />

            {/* Floating Node Inspector Popover */}
            <AnimatePresence>
              {inspectedNode && (
                <NodeInspector
                  node={inspectedNode}
                  matchingAlert={matchingInspectorAlert}
                  corridorOrigin={corridorOrigin}
                  rightOpen={rightOpen}
                  onSetOrigin={(n) => {
                    setCorridorDest(null)
                    setCorridorOrigin({ spec: n.id, label: n.name, coord: n.position })
                  }}
                  onClearOrigin={() => setCorridorOrigin(null)}
                  onRouteToNode={(n) => {
                    if (!corridorOrigin) return
                    runCorridorRoute(
                      corridorOrigin,
                      { spec: n.id, label: n.name, coord: n.position },
                      vehicleClass,
                    )
                  }}
                  onDispatchAlert={handleApproveDispatch}
                  onClose={() => {
                    setInspectedNode(null)
                    setSelectedAlertId(null)
                  }}
                />
              )}
            </AnimatePresence>

            {/* Surface 2: Right-Side Floating Command Panel */}
            <CommandPanel
              open={rightOpen}
              onToggleOpen={setRightOpen}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
              region={region}
              loading={!scenario}
              alerts={mergedAlerts}
              selectedAlertId={selectedAlertId}
              dismissFeedback={dismissFeedback}
              onClearDismissFeedback={() => setDismissFeedback(null)}
              onSelectAlert={handleSelectAlert}
              onLocateAlert={handleLocateAlert}
              onApproveDispatch={handleApproveDispatch}
              onDismissAlert={handleDismissAlert}
              onVetoBarrier={handleVetoBarrier}
              onReopenBarrier={handleReopenBarrier}
              onInspectNodeId={inspectNodeById}
              pois={bootstrap?.pois ?? []}
              depots={bootstrap?.depots ?? []}
              transit={
                scenario?.transit ?? {
                  corridors: [],
                  summary: { normal: 0, diverted: 0, suspended: 0 },
                }
              }
              activeRoute={activeRoute}
              activeRouteLabel={activeRouteLabel}
              activeTransitId={activeTransitId}
              onSelectTransit={handleSelectTransit}
              vehicleClass={vehicleClass}
              setVehicleClass={setVehicleClass}
              corridorOrigin={corridorOrigin}
              corridorDest={corridorDest}
              onRunCorridor={runCorridorRoute}
              onClearCorridor={() => {
                setCorridorOrigin(null)
                setCorridorDest(null)
                setActiveRoute(null)
                setActiveRouteLabel(null)
              }}
              pickMode={pickMode}
              setPickMode={setPickMode}
              showBusRoutes={showBusRoutes}
              setShowBusRoutes={setShowBusRoutes}
              showHospitalCorridors={showHospitalCorridors}
              setShowHospitalCorridors={setShowHospitalCorridors}
              fleet={fleet}
              simClockMin={simClockMin}
              onTick5m={handleTick5m}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </MotionConfig>
  )
}

export default App
