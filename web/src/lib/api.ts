import type { Band, Mode, Priority } from './scoring'
import type { CatchmentKey } from './mock'

export type Perspective = 'dispatch' | 'transit'
export type DismissReason = 'false_alarm' | 'already_handled' | 'insufficient_confidence'
export type VehicleClass = 'pump_truck' | 'bus' | 'ambulance' | 'fire_engine' | 'warden' | 'civilian'

export interface CorridorEndpoint {
  spec: string | { lat: number; lng: number }
  label: string
  coord?: [number, number] // [lng, lat]
}

export const API_BASE =
  typeof window !== 'undefined' && window.location.port === '8000'
    ? '/api/v1'
    : 'http://127.0.0.1:8000/api/v1'

export interface BootstrapRoad {
  id: string
  path: [number, number][]
  highway: string
  catchment: CatchmentKey
  length_m: number
}

export interface BootstrapPoi {
  id: string
  name: string
  category: string
  catchment: CatchmentKey
  node_id: string
  lat: number
  lng: number
}

export interface BootstrapDepot {
  id: string
  name: string
  region: CatchmentKey
  node_id: string
  lat: number
  lng: number
  elevation: number
  asset_classes: string[]
}

export interface ScenarioPreset {
  id: string
  label: string
  rain_mm_hr: number
  duration_min: number
  mode: Mode
  description: string
}

export interface CatchmentMeta {
  key: CatchmentKey
  short: string
  name: string
  centroid: [number, number]
  bounds: [number, number, number, number]
  nodes: number
  edges: number
}

export interface BootstrapResponse {
  simulation: boolean
  version: string
  catchments: Record<CatchmentKey, CatchmentMeta>
  roads: BootstrapRoad[]
  pois: BootstrapPoi[]
  depots: BootstrapDepot[]
  presets: ScenarioPreset[]
  config: {
    thresholds: Record<Mode, { alert_floor: number; barrier: number; pump: number }>
    fleet_limits: Record<'pumps' | 'barriers' | 'wardens', [number, number]>
    default_fleet: { pumps: number; barriers: number; wardens: number }
  }
}

export interface FleetPoolCount {
  total: number
  idle: number
  active: number
  standby: number
}

export interface FleetUnitDto {
  unit_id: string
  unit_class: 'pump' | 'barrier' | 'warden'
  spec: string
  depot_id: string
  depot_name: string
  home_node_id: string
  home_catchment: CatchmentKey
  current_node_id: string
  current_catchment: CatchmentKey
  state: string
  assigned_alert_id: string | null
  target_node_id: string | null
  target_name: string | null
  target_catchment: CatchmentKey | null
  eta_min: number
  remaining_min: number
  veto_remaining_sec: number
  inter_catchment: boolean
}

export interface FleetSummaryDto {
  counts: {
    pump: FleetPoolCount
    barrier: FleetPoolCount
    warden: FleetPoolCount
  }
  units: FleetUnitDto[]
  fleet_oversized: boolean
}

export interface RouteLegDto {
  reachable: boolean
  path_nodes: string[]
  coords: [number, number][]
  flooded_segments: [number, number][][]
  eta_min: number | null
  distance_m: number | null
  flooded_crossings: number
  max_depth_m: number
}

export interface RouteComparisonDto {
  reachable: boolean
  reason: string | null
  vehicle: VehicleClass
  origin_node: string
  dest_node: string
  origin_catchment?: CatchmentKey
  dest_catchment?: CatchmentKey
  inter_catchment: boolean
  penalty_min: number
  stub_coords: [number, number][] | null
  standard: RouteLegDto
  safe: RouteLegDto
  added_vs_standard_min: number | null
  origin_snap_m?: number
  dest_snap_m?: number
}

export interface ApiNodeDto {
  id: string
  catchment: CatchmentKey
  position: [number, number]
  depth_m: number
  depth: number
  band: Band
  priority: Priority
  score: number
  name: string
  assets: string[]
  primary_asset: string
  elevation: number
  sink: number
  sink_ratio: number
  network: number
  is_basement: boolean
  swmm_depth_m: number
  swmmDeltaCm: number
  status: 'MATCH' | 'OVER' | 'UNDER'
  ttp_min: number
  barrier_locked?: boolean
}

export interface ApiAlertDto extends ApiNodeDto {
  alert_id: string
  affected_nodes: number
  cluster_node_ids: string[]
  extent_m: number
  action: 'pump_dispatch' | 'barrier_closure' | 'warden_diversion' | 'monitor'
  action_label: string
  unit_class: 'pump' | 'barrier' | 'warden' | 'none'
  underpass_poi_id: string | null
  ttp_source: string
  mode: Mode
  deploy_where: string
  deploy_what: string
  deploy_when: string
  dispatch_status: 'PENDING' | 'ASSIGNED' | 'DISMISSED' | 'INFEASIBLE'
  unit_state?: string
  unit: string | null
  depot: string | null
  eta_min: number | null
  remaining_min?: number
  addedMinutes: number
  feasible: boolean
  infeasible_reason: string | null
  infeasible_message: string | null
  inter_catchment: boolean
  veto_remaining_sec: number
  dismiss_reason?: string
  route?: RouteComparisonDto | null
}

export interface TransitCorridorDto {
  route_id: string
  route_name: string
  catchment: CatchmentKey | 'all'
  status: 'NORMAL' | 'DIVERTED' | 'SUSPENDED'
  directive: string
  origin_label: string
  dest_label: string
  origin_node: string
  dest_node: string
  bottleneck_node?: string | null
  bottleneck_name?: string | null
  bottleneck_depth_m?: number
  flooded_crossings: number
  barrier_conflicts: number
  max_std_depth_m: number
  standard_eta_min: number | null
  safe_eta_min: number | null
  added_vs_standard_min: number | null
  route: RouteComparisonDto
}

export interface AuditEventDto {
  seq: number
  ts: string
  sim: string
  session_id: string
  actor: string
  action: string
  token: 'system' | 'operator' | 'warn'
  msg: string
  alert?: string | null
  unit?: string | null
  eta_min?: number | null
  inter_catchment?: boolean
  config_hash: string
}

export interface ScenarioResponse {
  simulation: boolean
  scenario_key: string
  region: CatchmentKey | 'all'
  rain_mmhr: number
  duration_min: number
  mode: Mode
  sim_clock_min: number
  sim_ts: string
  alerts: ApiAlertDto[]
  nodes: ApiNodeDto[]
  edge_depths: Record<string, number>
  stats: {
    inference_latency_ms: number
    triage_wall_ms: number
    raw_above_floor: number
    raw_eligible: number
    dedup_alerts: number
    total_clusters?: number
    suppressed: number
    critical_nodes: number
    blocked_km: number
    total_edges: number
    mean_eta_min: number
  }
  fleet: FleetSummaryDto | null
  transit: {
    corridors: TransitCorridorDto[]
    summary: { normal: number; diverted: number; suspended: number }
  }
}

export interface SessionResponse {
  simulation: boolean
  session_id: string
  operator: string
  region: CatchmentKey | 'all'
  rain_mmhr: number
  duration_min: number
  mode: Mode
  sim_clock_min: number
  sim_ts: string
  config_hash: string
  fleet_config: { pumps: number; barriers: number; wardens: number }
  fleet: FleetSummaryDto
  log_entry?: AuditEventDto
}

async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const msg = (data as { message?: string; error?: string }).message || `HTTP ${res.status}`
    throw new Error(msg)
  }
  return data as T
}

export function fetchBootstrap(): Promise<BootstrapResponse> {
  return jsonRequest<BootstrapResponse>('/bootstrap')
}

export function createSessionApi(payload: {
  operator: string
  region: CatchmentKey | 'all'
  rain: number
  duration: number
  mode: Mode
  pumps: number
  barriers: number
  wardens: number
}): Promise<SessionResponse> {
  return jsonRequest<SessionResponse>('/session', {
    method: 'POST',
    body: JSON.stringify({
      operator: payload.operator,
      region: payload.region,
      rain_mmhr: payload.rain,
      duration_min: payload.duration,
      mode: payload.mode,
      fleet: {
        pumps: payload.pumps,
        barriers: payload.barriers,
        wardens: payload.wardens,
      },
    }),
  })
}

export function fetchScenarioApi(
  params: {
    session_id?: string
    region: CatchmentKey | 'all'
    rain_mmhr: number
    duration_min: number
    mode: Mode
  },
  signal?: AbortSignal,
): Promise<ScenarioResponse> {
  return jsonRequest<ScenarioResponse>('/scenario', {
    method: 'POST',
    body: JSON.stringify(params),
    signal,
  })
}

export function dispatchAlertApi(
  session_id: string,
  alert_id: string,
  unit_id?: string,
): Promise<{
  ok: boolean
  feasible?: boolean
  reason?: string
  message?: string
  unit?: FleetUnitDto
  route?: RouteComparisonDto | null
  fleet: FleetSummaryDto
  transit: ScenarioResponse['transit']
  log_entry: AuditEventDto
}> {
  return jsonRequest('/dispatch', {
    method: 'POST',
    body: JSON.stringify({ session_id, alert_id, unit_id }),
  })
}

export function dismissAlertApi(
  session_id: string,
  alert_id: string,
  reason: DismissReason,
  node_id?: string,
  cluster_node_ids?: string[],
): Promise<{
  ok: boolean
  calibration?: {
    reason: DismissReason
    node_count: number
    depth_multiplier: number
    summary: string
  }
  log_entry: AuditEventDto
}> {
  return jsonRequest('/dismiss', {
    method: 'POST',
    body: JSON.stringify({
      session_id,
      alert_id,
      reason,
      node_id,
      cluster_node_ids,
    }),
  })
}

export function vetoBarrierApi(
  session_id: string,
  unit_id: string,
): Promise<{
  ok: boolean
  unit: FleetUnitDto
  fleet: FleetSummaryDto
  log_entry: AuditEventDto
}> {
  return jsonRequest('/veto', {
    method: 'POST',
    body: JSON.stringify({ session_id, unit_id }),
  })
}

export function reopenBarrierApi(
  session_id: string,
  unit_id: string,
): Promise<{
  ok: boolean
  unit: FleetUnitDto
  fleet: FleetSummaryDto
  log_entry: AuditEventDto
}> {
  return jsonRequest('/reopen', {
    method: 'POST',
    body: JSON.stringify({ session_id, unit_id }),
  })
}

export function tickClockApi(
  session_id: string,
  minutes: number,
): Promise<{
  ok: boolean
  sim_clock_min: number
  sim_ts: string
  fleet: FleetSummaryDto
  transit: ScenarioResponse['transit']
  log_entries: AuditEventDto[]
}> {
  return jsonRequest('/tick', {
    method: 'POST',
    body: JSON.stringify({ session_id, minutes }),
  })
}

export function routeCorridorApi(params: {
  session_id?: string
  origin: string | { lat: number; lng: number }
  dest: string | { lat: number; lng: number }
  vehicle: VehicleClass
  rain_mmhr: number
  duration_min: number
  mode?: Mode
  region?: CatchmentKey | 'all'
}): Promise<RouteComparisonDto> {
  return jsonRequest<RouteComparisonDto>('/route', {
    method: 'POST',
    body: JSON.stringify(params),
  })
}

export function fetchNodeInspectApi(
  nodeId: string,
  params: { session_id?: string; rain_mmhr: number; duration_min: number; mode: Mode },
): Promise<{ node: ApiNodeDto }> {
  const qs = new URLSearchParams({
    rain_mmhr: String(params.rain_mmhr),
    duration_min: String(params.duration_min),
    mode: params.mode,
    ...(params.session_id ? { session_id: params.session_id } : {}),
  })
  return jsonRequest<{ node: ApiNodeDto }>(`/node/${encodeURIComponent(nodeId)}?${qs.toString()}`)
}

export function fetchLogsApi(
  session_id: string,
  since: number = 0,
): Promise<{ latest_seq: number; events: AuditEventDto[] }> {
  return jsonRequest(`/log?session_id=${encodeURIComponent(session_id)}&since=${since}`)
}
