/**
 * Deterministic mock scene for the UI shell (M0/M4).
 *
 * This is scaffolding so the dashboard can be built and its frame-rate budget
 * proven before the Python service exists. Every shape here mirrors the real
 * `/api/v1/scenario` payload, so swapping `mockScene()` for `fetchScenario()`
 * is a one-line change in App.tsx.
 *
 * Geography is real (the five Bengaluru catchments, D-14); depths are synthetic.
 * Names are taken from the production JUNCTION_NAMES table in app.py:740.
 */

import {
  ASSET_WEIGHT,
  band,
  consequenceScore,
  priority,
  type Band,
  type Mode,
  type Priority,
} from './scoring'

export type CatchmentKey = 'hsr' | 'bellandur' | 'whitefield' | 'ecity' | 'koramangala'

export interface CatchmentDef {
  key: CatchmentKey
  name: string
  short: string
  center: [number, number]
  nodes: number
  peak: number // synthetic depth peak multiplier 0..1
  names: string[]
}

export const CATCHMENTS: CatchmentDef[] = [
  {
    key: 'hsr',
    name: 'HSR Layout',
    short: 'HSR',
    center: [77.6389, 12.9116],
    nodes: 1379,
    peak: 0.62,
    names: [
      'Silk Board Underpass Ramp',
      '14th Main & 17th Cross Corridor',
      'Sector 6 Low-Lying Sag',
      'Agara Lake Outfall Channel',
      'Sector 7 Storm Canal Choke',
    ],
  },
  {
    key: 'bellandur',
    name: 'Bellandur & ORR',
    short: 'BLR',
    center: [77.6702, 12.9307],
    nodes: 1507,
    peak: 0.95,
    names: [
      'Central Mall Bellandur Underpass',
      'Bellandur Lake Inflow Canal',
      'EcoSpace Tech Park Main Gate',
      'Kadubeesanahalli Low Road',
      'ORR Northbound Surcharge Dip',
    ],
  },
  {
    key: 'whitefield',
    name: 'Whitefield / ITPB',
    short: 'WFD',
    center: [77.7499, 12.9698],
    nodes: 1797,
    peak: 0.78,
    names: [
      'Kundalahalli Gate Underpass',
      'Channasandra Railway Bridge Underpass',
      'ITPB Main Gate Boulevard',
      'Varthur Lake Inflow Channel',
      'Hope Farm Junction Corridor',
    ],
  },
  {
    key: 'ecity',
    name: 'Electronic City',
    short: 'ECT',
    center: [77.6599, 12.8452],
    nodes: 3337,
    peak: 0.55,
    names: [
      'Hosur Road Underpass Portal',
      'Electronic City Tollgate Ramp',
      'Velankani Drive Low-Lying Road',
      'Phase 2 Transit Hub',
      'Doddathoguru Lake Outfall Canal',
    ],
  },
  {
    key: 'koramangala',
    name: 'Koramangala',
    short: 'KRM',
    center: [77.6245, 12.9352],
    nodes: 4416,
    peak: 0.71,
    names: [
      'Sony World Junction Corridor',
      'Ejipura Canal Outfall Surcharge',
      'Passport Seva Kendra Underpass',
      'Koramangala Valley Storm Trunk',
      'ST Bed Layout Ground Floor Sag',
    ],
  },
]

export interface Road {
  id: string
  path: [number, number][]
  depth: number
  highway: string
  catchment: CatchmentKey
}

export interface SceneNode {
  id: string
  position: [number, number]
  depth: number
  band: Band
  priority: Priority
  score: number
  name: string
  assets: string[]
  elevation: number
  sink: number
  network: number
  swmmDeltaCm: number
  status: 'MATCH' | 'OVER' | 'UNDER'
  catchment: CatchmentKey
}

export interface Alert extends SceneNode {
  action: string
  actionLabel: string
  unit: string
  depot: string
  etaMin: number
  ttpMin: number
  addedMinutes: number
  feasible: boolean
}

export interface Scene {
  roads: Road[]
  nodes: SceneNode[]
  alerts: Alert[]
  suppressed: number
  criticalNodes: number
  blockedKm: number
  totalEdges: number
}

/**
 * Asset inference from the junction name — the same fallback strategy the Python
 * service uses when Overpass is unavailable (D-04). The production JUNCTION_NAMES
 * table already encodes POI semantics in plain English, so the mock uses it too.
 */
function inferAsset(lowerName: string): string | null {
  if (/underpass|bridge|railway|subway/.test(lowerName)) return 'underpass'
  if (/hospital|clinic|health/.test(lowerName)) return 'hospital'
  if (/transit|station|metro|tech park|mall|hub/.test(lowerName)) return 'transit_hub'
  if (/lake|canal|outfall|channel|drain/.test(lowerName)) return 'watercourse'
  if (/substation|power|grid/.test(lowerName)) return 'power_substation'
  return null
}

/** Deterministic LCG so the scene is stable across reloads and screenshots. */
function lcg(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 4294967296
  }
}

const COLS = 24
const ROWS = 16
const DX = 0.0017
const DY = 0.00135

/** Synthetic depth field: gaussian around a hotspot per catchment, scaled by rain. */
function depthAt(
  lng: number,
  lat: number,
  c: CatchmentDef,
  rain: number,
  rand: () => number,
): number {
  const dLng = (lng - c.center[0]) / 0.019
  const dLat = (lat - c.center[1]) / 0.014
  const dist = Math.sqrt(dLng * dLng + dLat * dLat)
  const intensity = 0.06 + Math.max(0, (rain - 20) / 100) * 0.62
  const falloff = Math.exp(-Math.pow(dist / 0.55, 2))
  const noise = (rand() - 0.5) * 0.035
  return Math.max(0, Math.min(1.2, intensity * c.peak * falloff + noise))
}

export function mockScene(rain: number, mode: Mode, regionFilter: CatchmentKey | 'all'): Scene {
  const roads: Road[] = []
  const nodes: SceneNode[] = []
  let edgeIndex = 0

  for (const c of CATCHMENTS) {
    const rand = lcg(
      c.key.split('').reduce((a, ch) => a + ch.charCodeAt(0), 0) + rain * 31,
    )
    const grid: number[][] = []

    for (let col = 0; col < COLS; col++) {
      grid[col] = []
      for (let row = 0; row < ROWS; row++) {
        const lng = c.center[0] + (col - (COLS - 1) / 2) * DX
        const lat = c.center[1] + (row - (ROWS - 1) / 2) * DY
        const depth = depthAt(lng, lat, c, rain, rand)
        grid[col][row] = depth

        const b = band(depth, mode)
        const nameIdx = (col * 7 + row * 3) % c.names.length
        const junctionName = c.names[nameIdx] ?? `${c.short} Junction ${col}-${row}`
        const inferred = inferAsset(junctionName.toLowerCase())
        const assets: string[] = depth > 0.1 && inferred ? [inferred] : []

        const asset = assets.length
          ? Math.max(...assets.map((a) => ASSET_WEIGHT[a] ?? 0.25))
          : 0.25
        const vulnerability = Math.min(
          1,
          0.45 * (depth > 0.18 ? 1 : 0) + 0.35 * Math.min(1, depth / 0.3) + 0.2 * 0,
        )
        const network = ((col * 13 + row * 29) % 100) / 100
        const score = consequenceScore({
          depthM: depth,
          asset,
          vulnerability,
          network,
        })

        if (depth > 0.02) {
          nodes.push({
            id: `${c.key}-${col}-${row}`,
            position: [lng, lat],
            depth,
            band: b,
            priority: priority(score),
            score,
            name: junctionName,
            assets,
            elevation: 880 + (1 - row / ROWS) * 18 + rand() * 2,
            sink: Math.min(0.4, depth * 0.7),
            network,
            swmmDeltaCm: Math.round((rand() * 8 - 3) * 10) / 10,
            status: 'MATCH',
            catchment: c.key,
          })
        }
      }
    }

    for (let col = 0; col < COLS; col++) {
      for (let row = 0; row < ROWS; row++) {
        const lng = c.center[0] + (col - (COLS - 1) / 2) * DX
        const lat = c.center[1] + (row - (ROWS - 1) / 2) * DY
        const d = grid[col][row]
        if (col < COLS - 1) {
          roads.push({
            id: `e${edgeIndex++}`,
            path: [
              [lng, lat],
              [lng + DX, lat],
            ],
            depth: d,
            highway: row % 5 === 0 ? 'primary' : 'residential',
            catchment: c.key,
          })
        }
        if (row < ROWS - 1) {
          roads.push({
            id: `e${edgeIndex++}`,
            path: [
              [lng, lat],
              [
                c.center[0] + (col - (COLS - 1) / 2) * DX,
                lat + DY,
              ],
            ],
            depth: d,
            highway: col % 6 === 0 ? 'secondary' : 'residential',
            catchment: c.key,
          })
        }
      }
    }
  }

  const visible = regionFilter === 'all' ? nodes : nodes.filter((n) => n.catchment === regionFilter)
  const visibleRoads =
    regionFilter === 'all' ? roads : roads.filter((r) => r.catchment === regionFilter)

  const flagged = visible.filter((n) => n.depth >= 0.08)
  const ranked = [...flagged].sort((a, b) => b.score - a.score)

  // One alert per asset, not per node. A single underpass spans dozens of
  // grid nodes; dispatching three pumps to the same ramp is the classic
  // failure mode of a per-node alert feed.
  const seen = new Set<string>()
  const unique: SceneNode[] = []
  for (const n of ranked) {
    const key = `${n.catchment}:${n.name}`
    if (seen.has(key)) continue
    seen.add(key)
    unique.push(n)
    if (unique.length >= 6) break
  }
  const top = unique

  const alerts: Alert[] = top.map((n, i) => {
    const primary = n.assets[0]
    // A barrier only makes sense at an underpass. A flooded hospital access road
    // needs a pump, not a gate — consequence and remedy are different questions.
    const accessCritical =
      primary === 'hospital' || primary === 'transit_hub' || primary === 'power_substation'
    const isPump = n.band === 'pump' || (accessCritical && n.band !== 'watch')
    const isBarrier = !isPump && n.band === 'barrier' && primary === 'underpass'
    return {
      ...n,
      action: isPump ? 'pump_dispatch' : isBarrier ? 'barrier_closure' : 'pre_position',
      actionLabel: isPump ? 'Active pumping' : isBarrier ? 'Barrier closure' : 'Pre-position',
      unit: isPump
        ? `PUMP-${String(i + 1).padStart(2, '0')}`
        : `BAR-${String(i + 3).padStart(2, '0')}`,
      depot: ['DEP-HSR-01', 'DEP-BLR-02', 'DEP-WFD-01', 'DEP-ECT-02', 'DEP-KRM-01'][i % 5]!,
      etaMin: 7 + i * 3,
      ttpMin: 18 + i * 6,
      addedMinutes: 2 + (i % 4),
      feasible: 7 + i * 3 + 10 <= 18 + i * 6,
    }
  })

  const blocked = visibleRoads.filter((r) => r.depth >= 0.25)
  const blockedKm = Math.round((blocked.length * 34) / 100) / 10 // ~34 m per synthetic block

  return {
    roads: visibleRoads,
    nodes: visible,
    alerts,
    suppressed: Math.max(0, ranked.length - 6),
    criticalNodes: flagged.filter((n) => n.band === 'pump').length,
    blockedKm,
    totalEdges: visibleRoads.length,
  }
}

export const DEPOTS = CATCHMENTS.map((c, i) => ({
  id: `DEP-${c.short}-0${(i % 2) + 1}`,
  name: `${c.name} Yard`,
  position: [c.center[0] - 0.004, c.center[1] + 0.005] as [number, number],
  pumps: i < 2 ? 3 : 2,
}))

export const AUDIT_SEED = [
  'INFER  region=all rain=95mm/hr dur=60m mode=red_alert  nodes=12436  412ms',
  'TRIAGE P1=6 P2=9 P3=24  suppressed=318',
  'GATE   BAR-11 → PENDING_CLOSE  node=bellandur-8-6 d=0.21m  veto 60s',
  'OPER   system  barrier BAR-11 closed  cause=depth>=0.09  sim=14:02:09Z',
]
