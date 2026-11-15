import { useMemo, useState } from 'react'
import {
  IconBus,
  IconChevronDown,
  IconCrosshair,
  IconHospital,
  IconNav,
} from './Icons'
import type {
  BootstrapDepot,
  BootstrapPoi,
  CorridorEndpoint,
  RouteComparisonDto,
  TransitCorridorDto,
  VehicleClass,
} from '../lib/api'
import type { CatchmentKey } from '../lib/mock'
import { pluralize } from '../lib/scoring'

interface CorridorTabProps {
  region: CatchmentKey | 'all'
  pois: BootstrapPoi[]
  depots: BootstrapDepot[]
  transit: {
    corridors: TransitCorridorDto[]
    summary: { normal: number; diverted: number; suspended: number }
  }
  activeRoute: RouteComparisonDto | null
  activeRouteLabel: string | null
  activeTransitId: string | null
  onSelectTransit: (c: TransitCorridorDto) => void
  onInspectNodeId: (nodeId: string) => void
  vehicleClass: VehicleClass
  setVehicleClass: (v: VehicleClass) => void
  corridorOrigin: CorridorEndpoint | null
  corridorDest: CorridorEndpoint | null
  onRunCorridor: (o: CorridorEndpoint, d: CorridorEndpoint, v: VehicleClass) => void
  onClearCorridor: () => void
  pickMode: 'inspect' | 'corridor'
  setPickMode: (m: 'inspect' | 'corridor') => void
  showBusRoutes: boolean
  setShowBusRoutes: (b: boolean) => void
  showHospitalCorridors: boolean
  setShowHospitalCorridors: (b: boolean) => void
}

function OverlayToggle({
  label,
  checked,
  onChange,
  icon,
}: {
  label: string
  checked: boolean
  onChange: (next: boolean) => void
  icon: React.ReactNode
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`flex items-center justify-between gap-2 rounded-xl border px-3 py-2 text-xs font-medium cursor-pointer tactile-press ${
        checked
          ? 'border-white/20 bg-white/[0.08] text-[#F4F5F7]'
          : 'border-white/[0.08] bg-white/[0.02] text-[#8E95A2] hover:border-white/[0.18] hover:text-[#F4F5F7]'
      }`}
    >
      <span className="flex items-center gap-2 min-w-0">
        {icon}
        <span className="truncate">{label}</span>
      </span>
      <span
        aria-hidden="true"
        className={`relative inline-flex h-4 w-7 shrink-0 rounded-full transition-colors ${
          checked ? 'bg-[#10B981]' : 'bg-white/[0.15]'
        }`}
      >
        <span
          className={`inline-block h-3 w-3 rounded-full bg-white shadow transform transition-transform mt-0.5 ${
            checked ? 'translate-x-3.5' : 'translate-x-0.5'
          }`}
        />
      </span>
    </button>
  )
}

export function CorridorTab({
  region,
  pois,
  depots,
  transit,
  activeRoute,
  activeRouteLabel,
  activeTransitId,
  onSelectTransit,
  onInspectNodeId,
  vehicleClass,
  setVehicleClass,
  corridorOrigin,
  corridorDest,
  onRunCorridor,
  onClearCorridor,
  pickMode,
  setPickMode,
  showBusRoutes,
  setShowBusRoutes,
  showHospitalCorridors,
  setShowHospitalCorridors,
}: CorridorTabProps) {
  const [selOrigin, setSelOrigin] = useState('')
  const [selDest, setSelDest] = useState('')

  const landmarks = useMemo(() => {
    const out: { node_id: string; label: string; coord: [number, number] }[] = []
    const seenIds = new Set<string>()
    const seenNames = new Set<string>()
    for (const d of depots) {
      if (region !== 'all' && d.region !== region) continue
      if (seenIds.has(d.node_id)) continue
      seenIds.add(d.node_id)
      out.push({ node_id: d.node_id, label: `Depot: ${d.name}`, coord: [d.lng, d.lat] })
    }
    for (const p of pois) {
      if (region !== 'all' && p.catchment !== region) continue
      const nameKey = `${p.catchment}:${p.name.trim().toLowerCase()}`
      if (seenIds.has(p.node_id) || seenNames.has(nameKey)) continue
      seenIds.add(p.node_id)
      seenNames.add(nameKey)
      out.push({
        node_id: p.node_id,
        label: `${p.name} (${p.catchment.toUpperCase()})`,
        coord: [p.lng, p.lat],
      })
    }
    return out.slice(0, 60)
  }, [pois, depots, region])

  const handleCompute = () => {
    const o: CorridorEndpoint | undefined = selOrigin
      ? (() => {
          const l = landmarks.find((x) => x.node_id === selOrigin)
          return l ? { spec: l.node_id, label: l.label, coord: l.coord } : undefined
        })()
      : (corridorOrigin ?? undefined)
    const d: CorridorEndpoint | undefined = selDest
      ? (() => {
          const l = landmarks.find((x) => x.node_id === selDest)
          return l ? { spec: l.node_id, label: l.label, coord: l.coord } : undefined
        })()
      : (corridorDest ?? undefined)
    if (!o || !d || o.spec === d.spec) return
    onRunCorridor(o, d, vehicleClass)
  }

  const effectiveOrigin = selOrigin || (corridorOrigin ? '__map_origin__' : '')
  const effectiveDest = selDest || (corridorDest ? '__map_dest__' : '')
  const canRoute = Boolean((selOrigin || corridorOrigin) && (selDest || corridorDest))

  const selectedTransitObj = transit.corridors.find((c) => c.route_id === activeTransitId)
  const comparisonRoute = activeRoute ?? selectedTransitObj?.route ?? null

  return (
    <div aria-label="Corridor and Transit Safety" className="flex flex-col flex-1 min-h-0 overflow-y-auto p-5 space-y-4">
      {/* Route Origin -> Destination Picker */}
      <section className="hud-card rounded-xl p-4 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-semibold text-[#F4F5F7]">
            <IconNav className="h-3.5 w-3.5 text-[#8E95A2]" />
            <span>Route Comparison</span>
          </div>
          <div className="relative">
            <select
              aria-label="Vehicle profile"
              value={vehicleClass}
              onChange={(e) => setVehicleClass(e.target.value as VehicleClass)}
              className="appearance-none rounded-lg border border-white/[0.08] bg-[#090B0E]/80 pl-2.5 pr-6 py-1 text-[11px] font-medium text-[#F4F5F7] focus:border-white/30 focus:outline-none cursor-pointer"
            >
              <option value="bus" className="bg-[#11141A]">BMTC Bus (25 cm)</option>
              <option value="ambulance" className="bg-[#11141A]">Ambulance (30 cm)</option>
              <option value="pump_truck" className="bg-[#11141A]">Pump Truck (25 cm)</option>
              <option value="fire_engine" className="bg-[#11141A]">Fire Engine (30 cm)</option>
              <option value="civilian" className="bg-[#11141A]">Civilian (20 cm)</option>
            </select>
            <IconChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 h-3 w-3 text-[#8E95A2]" />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-2">
          <div className="relative">
            <select
              aria-label="Corridor origin landmark"
              value={effectiveOrigin}
              onChange={(e) => setSelOrigin(e.target.value === '__map_origin__' ? '' : e.target.value)}
              className="w-full appearance-none rounded-lg border border-white/[0.08] bg-[#090B0E]/80 px-2.5 pr-7 py-1.5 text-xs text-[#F4F5F7] truncate focus:border-white/30 focus:outline-none cursor-pointer"
            >
              <option value="" className="bg-[#11141A]">Origin A…</option>
              {corridorOrigin && !selOrigin && (
                <option value="__map_origin__" className="bg-[#11141A]">
                  Pin A: {corridorOrigin.label}
                </option>
              )}
              {landmarks.map((l) => (
                <option key={`o-${l.node_id}`} value={l.node_id} className="bg-[#11141A]">
                  {l.label}
                </option>
              ))}
            </select>
            <IconChevronDown className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-3 w-3 text-[#8E95A2]" />
          </div>

          <div className="relative">
            <select
              aria-label="Corridor destination landmark"
              value={effectiveDest}
              onChange={(e) => setSelDest(e.target.value === '__map_dest__' ? '' : e.target.value)}
              className="w-full appearance-none rounded-lg border border-white/[0.08] bg-[#090B0E]/80 px-2.5 pr-7 py-1.5 text-xs text-[#F4F5F7] truncate focus:border-white/30 focus:outline-none cursor-pointer"
            >
              <option value="" className="bg-[#11141A]">Destination B…</option>
              {corridorDest && !selDest && (
                <option value="__map_dest__" className="bg-[#11141A]">
                  Pin B: {corridorDest.label}
                </option>
              )}
              {landmarks.map((l) => (
                <option key={`d-${l.node_id}`} value={l.node_id} className="bg-[#11141A]">
                  {l.label}
                </option>
              ))}
            </select>
            <IconChevronDown className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-3 w-3 text-[#8E95A2]" />
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPickMode(pickMode === 'corridor' ? 'inspect' : 'corridor')}
            className={`flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium cursor-pointer tactile-press ${
              pickMode === 'corridor'
                ? 'border-[#10B981]/50 bg-[#10B981]/15 text-[#6EE7B7]'
                : 'border-white/[0.08] bg-white/[0.03] text-[#F4F5F7] hover:border-white/[0.18]'
            }`}
          >
            <IconCrosshair className="h-3.5 w-3.5" />
            <span>
              {pickMode === 'corridor'
                ? corridorOrigin
                  ? 'Click Dest B…'
                  : 'Click Origin A…'
                : 'Pick A → B on Map'}
            </span>
          </button>

          <button
            type="button"
            disabled={!canRoute}
            onClick={handleCompute}
            className="rounded-lg bg-[#F4F5F7] hover:bg-white disabled:opacity-35 px-3.5 py-1.5 text-xs font-semibold text-[#090B0E] cursor-pointer tactile-press"
          >
            Route
          </button>

          {(corridorOrigin || corridorDest || activeRoute) && (
            <button
              type="button"
              onClick={onClearCorridor}
              className="rounded-lg border border-white/[0.08] px-2.5 py-1.5 text-xs text-[#8E95A2] hover:text-[#F4F5F7] hover:border-white/[0.18] cursor-pointer tactile-press"
            >
              Clear
            </button>
          )}
        </div>
      </section>

      {/* Side-by-Side Route Comparison Card */}
      {comparisonRoute && (
        <section aria-label="Route Safety Comparison" className="space-y-2">
          {activeRouteLabel && (
            <div className="text-[11px] font-medium text-[#8E95A2] truncate px-0.5">
              {activeRouteLabel}
            </div>
          )}
          <div className="grid grid-cols-2 gap-2.5">
            {/* Standard Route */}
            <div className="rounded-xl border border-[#38BDF8]/30 bg-[#38BDF8]/[0.07] p-3 space-y-1.5">
              <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[#7DD3FC]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#38BDF8]" />
                <span>Standard Route</span>
              </div>
              <div className="font-mono text-base font-semibold text-[#F4F5F7] tnum">
                {comparisonRoute.standard.eta_min !== null
                  ? `${comparisonRoute.standard.eta_min.toFixed(1)} min`
                  : '—'}
              </div>
              <div className="text-[11px] text-[#FCA5A5]/90 leading-snug tnum">
                {comparisonRoute.standard.flooded_crossings > 0
                  ? `Blocked — ${(comparisonRoute.standard.max_depth_m * 100).toFixed(0)} cm flood at ${pluralize(
                      comparisonRoute.standard.flooded_crossings,
                      'junction',
                    )}`
                  : 'No flooded segments'}
              </div>
            </div>

            {/* UrbanFLOW Safe Corridor */}
            <div
              className={`rounded-xl border p-3 space-y-1.5 ${
                comparisonRoute.reachable
                  ? 'border-[#10B981]/30 bg-[#10B981]/[0.08]'
                  : 'border-[#EF4444]/30 bg-[#EF4444]/[0.08]'
              }`}
            >
              <div
                className={`flex items-center gap-1.5 text-[11px] font-semibold ${
                  comparisonRoute.reachable ? 'text-[#6EE7B7]' : 'text-[#FCA5A5]'
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    comparisonRoute.reachable ? 'bg-[#10B981]' : 'bg-[#EF4444]'
                  }`}
                />
                <span>Safe Corridor</span>
              </div>
              <div className="font-mono text-base font-semibold text-[#F4F5F7] tnum">
                {comparisonRoute.reachable && comparisonRoute.safe.eta_min !== null
                  ? `${comparisonRoute.safe.eta_min.toFixed(1)} min`
                  : 'Blocked'}
              </div>
              <div
                className={`text-[11px] leading-snug tnum ${
                  comparisonRoute.reachable ? 'text-[#6EE7B7]/90' : 'text-[#FCA5A5]/90'
                }`}
              >
                {comparisonRoute.reachable
                  ? comparisonRoute.added_vs_standard_min !== null &&
                    comparisonRoute.added_vs_standard_min > 0
                    ? `Clear · +${comparisonRoute.added_vs_standard_min.toFixed(0)} min detour`
                    : 'Clear · Nominal path'
                  : 'All paths submerged'}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Map Overlay Switches */}
      <div className="grid grid-cols-2 gap-2">
        <OverlayToggle
          label="Bus Routes"
          checked={showBusRoutes}
          onChange={setShowBusRoutes}
          icon={<IconBus className="h-3.5 w-3.5 shrink-0" />}
        />
        <OverlayToggle
          label="Hospitals"
          checked={showHospitalCorridors}
          onChange={setShowHospitalCorridors}
          icon={<IconHospital className="h-3.5 w-3.5 shrink-0" />}
        />
      </div>

      {/* Live BMTC Transit Corridors */}
      <div className="space-y-2.5 pt-1">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium text-[#F4F5F7]">BMTC Commuter Corridors</span>
          <span className="font-mono text-[11px] text-[#8E95A2] tnum">
            {transit.summary.normal} clear · {transit.summary.diverted} diverted ·{' '}
            {transit.summary.suspended} hold
          </span>
        </div>

        <ul className="space-y-2">
          {transit.corridors.map((c) => {
            const active = c.route_id === activeTransitId
            const badgeCls =
              c.status === 'SUSPENDED'
                ? 'border-[#EF4444]/40 bg-[#EF4444]/15 text-[#FCA5A5]'
                : c.status === 'DIVERTED'
                  ? 'border-[#F59E0B]/40 bg-[#F59E0B]/15 text-[#FCD34D]'
                  : 'border-[#10B981]/35 bg-[#10B981]/10 text-[#6EE7B7]'
            const statusText =
              c.status === 'SUSPENDED' ? 'Hold' : c.status === 'DIVERTED' ? 'Diverted' : 'Clear'

            return (
              <li
                key={c.route_id}
                onClick={() => onSelectTransit(c)}
                className={`hud-card rounded-xl p-3.5 space-y-2 cursor-pointer ${
                  active ? '!border-[#10B981]/50 !bg-white/[0.06]' : ''
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-semibold text-[#F4F5F7] truncate" title={c.route_name}>
                      {c.route_name}
                    </div>
                    <div className="text-[11px] text-[#8E95A2] truncate">
                      {c.origin_label} → {c.dest_label}
                    </div>
                  </div>
                  <span
                    className={`shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-semibold ${badgeCls}`}
                  >
                    {statusText}
                  </span>
                </div>

                {c.bottleneck_node && (c.bottleneck_depth_m ?? 0) > 0.08 && (
                  <div className="flex items-center justify-between gap-2 rounded-lg border border-white/[0.08] bg-[#090B0E]/60 px-2.5 py-1.5 text-[11px]">
                    <span className="truncate text-[#FCD34D] tnum">
                      {c.bottleneck_name} ({((c.bottleneck_depth_m ?? 0) * 100).toFixed(0)} cm)
                    </span>
                    <button
                      type="button"
                      onClick={(ev) => {
                        ev.stopPropagation()
                        onInspectNodeId(c.bottleneck_node!)
                      }}
                      className="shrink-0 text-[11px] font-medium text-[#F4F5F7] hover:underline cursor-pointer"
                    >
                      Inspect
                    </button>
                  </div>
                )}

                <div className="flex items-center justify-between text-[11px] font-mono text-[#8E95A2] tnum pt-1 border-t border-white/[0.06]">
                  <span>
                    Std {c.standard_eta_min !== null ? `${c.standard_eta_min.toFixed(1)} min` : '—'} ·
                    Safe {c.safe_eta_min !== null ? `${c.safe_eta_min.toFixed(1)} min` : 'Blocked'}
                  </span>
                  <span className={c.flooded_crossings > 0 ? 'text-[#FCA5A5]' : 'text-[#6EE7B7]'}>
                    {c.flooded_crossings} flooded · max {(c.max_std_depth_m * 100).toFixed(0)} cm
                  </span>
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
