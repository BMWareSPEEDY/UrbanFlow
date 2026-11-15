import { useMemo, useState } from 'react'
import { IconFastForward } from './Icons'
import type { FleetSummaryDto, FleetUnitDto } from '../lib/api'
import { formatMinutes } from '../lib/scoring'

interface FleetTabProps {
  fleet: FleetSummaryDto | null
  simClockMin?: number
  onTick5m: () => void
}

type FleetFilter = 'all' | 'active' | 'idle'

function unitStatusTone(state: string): { dot: string; label: string } {
  switch (state) {
    case 'IDLE':
      return { dot: 'bg-[#10B981]', label: 'Available' }
    case 'EN_ROUTE':
      return { dot: 'bg-[#F59E0B]', label: 'En Route' }
    case 'DEWATERING':
    case 'ON_SITE':
      return { dot: 'bg-[#EF4444]', label: state === 'DEWATERING' ? 'Dewatering' : 'On Site' }
    case 'PENDING_CLOSE':
      return { dot: 'bg-[#F59E0B]', label: 'Locking' }
    case 'CLOSED':
      return { dot: 'bg-[#EF4444]', label: 'Locked' }
    case 'RETURNING':
      return { dot: 'bg-[#8E95A2]', label: 'Returning' }
    case 'STANDBY':
      return { dot: 'bg-[#8E95A2]', label: 'Standby' }
    default:
      return { dot: 'bg-[#8E95A2]', label: state }
  }
}

export function FleetTab({ fleet, simClockMin = 0, onTick5m }: FleetTabProps) {
  const [filter, setFilter] = useState<FleetFilter>('all')

  const counts = fleet?.counts ?? {
    pump: { total: 0, idle: 0, active: 0, standby: 0 },
    barrier: { total: 0, idle: 0, active: 0, standby: 0 },
    warden: { total: 0, idle: 0, active: 0, standby: 0 },
  }

  const units = useMemo(() => {
    const all = fleet?.units ?? []
    if (filter === 'active') return all.filter((u) => u.state !== 'IDLE' && u.state !== 'STANDBY')
    if (filter === 'idle') return all.filter((u) => u.state === 'IDLE')
    return all
  }, [fleet?.units, filter])

  return (
    <div aria-label="Fleet and Resources" className="flex flex-col flex-1 min-h-0">
      {/* Resource Pools Summary */}
      <div className="px-5 py-4 border-b border-white/[0.08] space-y-3 shrink-0">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-[#F4F5F7]">Shift Resource Pools</span>
            <span className="font-mono text-[11px] text-[#8E95A2] tnum">
              T+{String(Math.round(simClockMin)).padStart(3, '0')}m
            </span>
          </div>
          <button
            type="button"
            onClick={onTick5m}
            title="Advance active deployments by 5 minutes"
            className="inline-flex items-center gap-1 rounded-lg border border-white/[0.08] bg-white/[0.04] hover:border-white/[0.18] px-2.5 py-1 text-[11px] font-mono text-[#F4F5F7] cursor-pointer tactile-press"
          >
            <IconFastForward className="h-3 w-3 text-[#8E95A2]" />
            <span>+5m Step</span>
          </button>
        </div>

        <div className="grid grid-cols-3 gap-2 font-mono tnum">
          {(
            [
              ['Pumps', counts.pump],
              ['Barriers', counts.barrier],
              ['Wardens', counts.warden],
            ] as [string, typeof counts.pump][]
          ).map(([label, pool]) => (
            <div
              key={label}
              className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-3 py-2.5"
            >
              <div className="text-[11px] font-sans text-[#8E95A2]">{label}</div>
              <div className="mt-1 flex items-baseline gap-1">
                <span
                  className={`text-base font-semibold ${
                    pool.idle === 0 && pool.total > 0 ? 'text-[#EF4444]' : 'text-[#F4F5F7]'
                  }`}
                >
                  {pool.idle}
                </span>
                <span className="text-xs text-[#8E95A2]">/ {pool.total}</span>
              </div>
              <div className="mt-0.5 text-[10px] font-sans text-[#8E95A2]">
                {pool.active} deployed
              </div>
            </div>
          ))}
        </div>

        <div className="flex gap-1.5">
          {(
            [
              ['all', 'All Units'],
              ['active', 'Deployed'],
              ['idle', 'Available'],
            ] as [FleetFilter, string][]
          ).map(([k, lbl]) => (
            <button
              key={k}
              type="button"
              onClick={() => setFilter(k)}
              className={`rounded-lg px-2.5 py-1 text-[11px] font-medium border cursor-pointer tactile-press ${
                filter === k
                  ? 'border-white/25 bg-white/[0.1] text-[#F4F5F7]'
                  : 'border-white/[0.08] text-[#8E95A2] hover:border-white/[0.18] hover:text-[#F4F5F7]'
              }`}
            >
              {lbl}
            </button>
          ))}
        </div>
      </div>

      {/* Inventory Rows */}
      <ul className="flex-1 min-h-0 overflow-y-auto p-5 space-y-2">
        {units.length === 0 ? (
          <li className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-5 text-center text-xs text-[#8E95A2]">
            {fleet && fleet.units.length === 0
              ? 'No unit telemetry entries available in current session.'
              : 'No units match this filter.'}
          </li>
        ) : (
          units.map((u: FleetUnitDto) => {
            const tone = unitStatusTone(u.state)
            const isActive = u.state !== 'IDLE' && u.state !== 'STANDBY'
            return (
              <li
                key={u.unit_id}
                className="hud-card rounded-xl px-3.5 py-3 flex items-center justify-between gap-3"
              >
                <div className="min-w-0 flex-1 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${tone.dot}`} />
                    <span className="font-mono text-xs font-semibold text-[#F4F5F7] tnum">
                      {u.unit_id}
                    </span>
                    <span className="text-[11px] text-[#8E95A2] truncate">{u.spec}</span>
                  </div>
                  <div className="text-[11px] text-[#8E95A2] truncate pl-3.5">
                    {isActive && u.target_name ? (
                      <span className="text-[#F4F5F7]/90">→ {u.target_name}</span>
                    ) : (
                      <span>{u.depot_name}</span>
                    )}
                  </div>
                </div>

                <div className="shrink-0 text-right space-y-0.5">
                  <div className="text-[11px] font-medium text-[#F4F5F7]">{tone.label}</div>
                  <div className="font-mono text-[11px] text-[#8E95A2] tnum">
                    {u.state === 'PENDING_CLOSE'
                      ? `${Math.ceil(u.veto_remaining_sec)}s`
                      : isActive && u.remaining_min > 0
                        ? formatMinutes(u.remaining_min, true)
                        : u.home_catchment.toUpperCase()}
                  </div>
                </div>
              </li>
            )
          })
        )}
      </ul>
    </div>
  )
}
