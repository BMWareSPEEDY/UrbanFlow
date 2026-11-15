import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import {
  IconAlert,
  IconCheck,
  IconCrosshair,
  IconShieldAlert,
  IconX,
} from './Icons'
import type { ApiAlertDto, DismissReason } from '../lib/api'
import { bandBadgeClass, formatMinutes, pluralize, priorityBadgeClass } from '../lib/scoring'

type FilterKey = 'all' | 'p1' | 'pump' | 'barrier' | 'shortage'

interface DispatchTabProps {
  loading: boolean
  alerts: ApiAlertDto[]
  selectedAlertId: string | null
  dismissFeedback?: string | null
  onClearDismissFeedback?: () => void
  onSelectAlert: (a: ApiAlertDto) => void
  onLocateAlert: (a: ApiAlertDto) => void
  onApproveDispatch: (a: ApiAlertDto) => void
  onDismissAlert: (a: ApiAlertDto, reason: DismissReason) => void
  onVetoBarrier: (unitId: string) => void
  onReopenBarrier: (unitId: string) => void
}

const DISMISS_OPTIONS: { key: DismissReason; label: string }[] = [
  { key: 'false_alarm', label: 'False alarm (drain clear)' },
  { key: 'already_handled', label: 'Handled by ward crew' },
  { key: 'insufficient_confidence', label: 'Low sensor confidence' },
]

function unitProgressPct(a: ApiAlertDto): number {
  if (a.unit_state === 'CLOSED' || a.unit_state === 'DEWATERING' || a.unit_state === 'ON_SITE') {
    return 100
  }
  if (a.unit_state === 'PENDING_CLOSE') {
    const pct = ((60 - Math.max(0, Math.min(60, a.veto_remaining_sec))) / 60) * 100
    return Math.max(10, Math.min(100, pct))
  }
  if (a.eta_min && a.eta_min > 0 && a.remaining_min !== undefined) {
    const elapsed = Math.max(0, a.eta_min - a.remaining_min)
    return Math.max(12, Math.min(98, (elapsed / a.eta_min) * 100))
  }
  return 35
}

function formatUnitState(state?: string): string {
  switch (state) {
    case 'EN_ROUTE':
      return 'En Route'
    case 'DEWATERING':
      return 'Dewatering'
    case 'ON_SITE':
      return 'On Site'
    case 'PENDING_CLOSE':
      return 'Locking'
    case 'CLOSED':
      return 'Locked'
    case 'RETURNING':
      return 'Returning'
    default:
      return state ? state.replace(/_/g, ' ') : 'Active'
  }
}

export function DispatchTab({
  loading,
  alerts,
  selectedAlertId,
  dismissFeedback,
  onClearDismissFeedback,
  onSelectAlert,
  onLocateAlert,
  onApproveDispatch,
  onDismissAlert,
  onVetoBarrier,
  onReopenBarrier,
}: DispatchTabProps) {
  const [filter, setFilter] = useState<FilterKey>('all')
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)

  const filteredAlerts = useMemo(() => {
    const active = alerts.filter((a) => a.dispatch_status !== 'DISMISSED')
    switch (filter) {
      case 'p1':
        return active.filter((a) => a.priority === 'P1')
      case 'pump':
        return active.filter((a) => a.unit_class === 'pump')
      case 'barrier':
        return active.filter((a) => a.unit_class === 'barrier')
      case 'shortage':
        return active.filter((a) => !a.feasible && a.dispatch_status !== 'ASSIGNED')
      default:
        return active
    }
  }, [alerts, filter])

  const visibleAlerts = showAll ? filteredAlerts : filteredAlerts.slice(0, 8)

  return (
    <div aria-label="Live Dispatch Queue" className="flex flex-col flex-1 min-h-0">
      {/* Compact Filter Strip */}
      <div className="px-5 py-3 border-b border-white/[0.08] space-y-2.5 shrink-0">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium text-[#F4F5F7]">Priority Directives</span>
          <span className="font-mono text-[11px] text-[#8E95A2] tnum">
            {pluralize(filteredAlerts.length, 'active alert')}
          </span>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {(
            [
              ['all', 'All'],
              ['p1', 'Critical'],
              ['pump', 'Pumps'],
              ['barrier', 'Barriers'],
              ['shortage', 'Shortages'],
            ] as [FilterKey, string][]
          ).map(([k, lbl]) => {
            const active = filter === k
            return (
              <button
                key={k}
                type="button"
                onClick={() => setFilter(k)}
                className={`rounded-lg px-2.5 py-1 text-[11px] font-medium border cursor-pointer tactile-press ${
                  active
                    ? 'border-white/25 bg-white/[0.1] text-[#F4F5F7]'
                    : 'border-white/[0.08] bg-transparent text-[#8E95A2] hover:border-white/[0.18] hover:text-[#F4F5F7]'
                }`}
              >
                {lbl}
              </button>
            )
          })}
        </div>
      </div>

      {/* Calibration Feedback Banner */}
      {dismissFeedback && (
        <div className="mx-5 mt-3 rounded-xl border border-[#10B981]/35 bg-[#10B981]/10 px-3.5 py-2.5 text-[11px] text-[#6EE7B7] flex items-start justify-between gap-2 shrink-0">
          <div className="flex items-start gap-2 min-w-0">
            <IconCheck className="h-3.5 w-3.5 shrink-0 mt-0.5 text-[#10B981]" />
            <span className="leading-snug">{dismissFeedback}</span>
          </div>
          {onClearDismissFeedback && (
            <button
              type="button"
              onClick={onClearDismissFeedback}
              aria-label="Close calibration notice"
              className="shrink-0 rounded p-0.5 text-[#6EE7B7]/80 hover:text-white cursor-pointer"
            >
              <IconX className="h-3 w-3" />
            </button>
          )}
        </div>
      )}

      {/* Scrollable Queue */}
      <ul className="flex-1 min-h-0 overflow-y-auto p-5 space-y-3">
        {loading && visibleAlerts.length === 0 ? (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <li
                key={i}
                className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-4 space-y-3 animate-pulse"
              >
                <div className="flex justify-between gap-3">
                  <div className="h-4 w-2/3 rounded bg-white/[0.06]" />
                  <div className="h-4 w-12 rounded bg-white/[0.06]" />
                </div>
                <div className="h-3 w-1/2 rounded bg-white/[0.05]" />
                <div className="h-8 w-full rounded-lg bg-white/[0.05]" />
              </li>
            ))}
          </div>
        ) : visibleAlerts.length === 0 ? (
          <li className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-6 text-center space-y-1.5">
            <IconCheck className="h-5 w-5 text-[#10B981] mx-auto" />
            <div className="text-xs font-medium text-[#F4F5F7]">No active directives</div>
            <div className="text-[11px] text-[#8E95A2]">
              {filter === 'all'
                ? 'All monitored junctions are below intervention threshold.'
                : 'No alerts match this filter.'}
            </div>
          </li>
        ) : (
          visibleAlerts.map((a) => {
            const selected = a.alert_id === selectedAlertId
            const depthCm = (a.depth_m * 100).toFixed(0)
            const assigned = a.dispatch_status === 'ASSIGNED'
            const infeasible = !a.feasible && !assigned
            const isEmergency = a.priority === 'P1'

            return (
              <motion.li
                key={a.alert_id}
                layout="position"
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.16, ease: [0.2, 0.8, 0.2, 1] }}
                onClick={() => onSelectAlert(a)}
                className={`hud-card rounded-xl p-4 space-y-3 cursor-pointer ${
                  selected ? '!border-white/30 !bg-white/[0.06]' : ''
                }`}
              >
                  {/* Top Row: Name + Depth Badge */}
                  <div className="flex items-start justify-between gap-2.5">
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span
                          className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${priorityBadgeClass(
                            a.priority,
                          )}`}
                        >
                          {a.priority}
                        </span>
                        <h3
                          className="text-[13px] font-semibold text-[#F4F5F7] truncate"
                          title={a.name}
                        >
                          {a.name}
                        </h3>
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] text-[#8E95A2]">
                        <span className="uppercase">{a.catchment}</span>
                        {a.affected_nodes > 1 && (
                          <>
                            <span aria-hidden="true">·</span>
                            <span className="tnum">
                              {pluralize(a.affected_nodes, 'node')}
                            </span>
                          </>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        type="button"
                        onClick={(ev) => {
                          ev.stopPropagation()
                          onLocateAlert(a)
                        }}
                        aria-label={`Locate ${a.name} on map`}
                        title="Center map on junction"
                        className="rounded-lg p-1 text-[#8E95A2] hover:text-[#F4F5F7] hover:bg-white/[0.08] cursor-pointer tactile-press"
                      >
                        <IconCrosshair className="h-3.5 w-3.5" />
                      </button>
                      <span
                        className={`shrink-0 whitespace-nowrap rounded-lg border px-2 py-0.5 font-mono text-xs font-semibold tnum ${bandBadgeClass(
                          a.band,
                        )}`}
                      >
                        {depthCm} cm
                      </span>
                    </div>
                  </div>

                  {/* Middle Row: Recommended Action & ETA */}
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="text-[#F4F5F7]/90 font-medium truncate">
                      {a.action_label}
                      {a.depot ? (
                        <span className="text-[#8E95A2] font-normal"> · {a.depot}</span>
                      ) : null}
                    </span>

                    <span className="shrink-0 whitespace-nowrap font-mono text-xs tnum text-[#8E95A2]">
                      {assigned && a.remaining_min !== undefined
                        ? `ETA ${formatMinutes(a.remaining_min, true)}`
                        : a.eta_min !== null
                          ? `ETA ${formatMinutes(a.eta_min, true)}`
                          : 'No route'}
                    </span>
                  </div>

                  {/* Action / State Footer */}
                  {infeasible ? (
                    <div className="rounded-lg border border-[#EF4444]/30 bg-[#EF4444]/10 px-3 py-2 text-[11px] text-[#FCA5A5] flex items-start gap-2">
                      <IconAlert className="h-3.5 w-3.5 shrink-0 mt-0.5 text-[#EF4444]" />
                      <span className="leading-snug">
                        {a.infeasible_message || 'No eligible unit available in pool.'}
                      </span>
                    </div>
                  ) : assigned ? (
                    <div className="pt-2.5 border-t border-white/[0.08] space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="h-1.5 w-1.5 rounded-full bg-[#10B981] shrink-0" />
                          <span className="font-mono text-[11px] font-semibold text-[#F4F5F7] truncate tnum">
                            {a.unit} · {formatUnitState(a.unit_state)}
                          </span>
                        </div>

                        {a.unit_state === 'PENDING_CLOSE' && a.unit && (
                          <button
                            type="button"
                            onClick={(ev) => {
                              ev.stopPropagation()
                              onVetoBarrier(a.unit!)
                            }}
                            className="shrink-0 rounded-lg border border-[#F59E0B]/40 bg-[#F59E0B]/15 hover:bg-[#F59E0B]/25 px-2.5 py-1 text-[11px] font-mono font-semibold text-[#FCD34D] tnum cursor-pointer tactile-press"
                          >
                            Veto ({Math.ceil(a.veto_remaining_sec)}s)
                          </button>
                        )}
                        {a.unit_state === 'CLOSED' && a.unit && (
                          <button
                            type="button"
                            onClick={(ev) => {
                              ev.stopPropagation()
                              onReopenBarrier(a.unit!)
                            }}
                            className="shrink-0 rounded-lg border border-white/[0.14] bg-white/[0.06] hover:bg-white/[0.12] px-2.5 py-1 text-[11px] font-medium text-[#F4F5F7] cursor-pointer tactile-press"
                          >
                            Reopen barrier
                          </button>
                        )}
                      </div>

                      <div className="h-1 w-full rounded-full bg-white/[0.08] overflow-hidden">
                        <div
                          className="h-full rounded-full bg-[#10B981] transition-all duration-300"
                          style={{ width: `${unitProgressPct(a)}%` }}
                        />
                      </div>
                    </div>
                  ) : (
                    <div
                      className="flex items-center gap-2 pt-2.5 border-t border-white/[0.08] relative"
                      onClick={(ev) => ev.stopPropagation()}
                    >
                      <button
                        type="button"
                        onClick={() => onApproveDispatch(a)}
                        className={`flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold cursor-pointer tactile-press ${
                          isEmergency
                            ? 'bg-[#EF4444] hover:bg-[#DC2626] text-white'
                            : 'bg-[#F4F5F7] hover:bg-white text-[#090B0E]'
                        }`}
                      >
                        {a.unit_class === 'barrier' && <IconShieldAlert className="h-3.5 w-3.5" />}
                        <span>Dispatch Unit</span>
                      </button>

                      <div className="relative">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            setOpenMenuId(openMenuId === a.alert_id ? null : a.alert_id)
                          }}
                          aria-label={`Dismiss ${a.name}`}
                          aria-expanded={openMenuId === a.alert_id}
                          title="Dismiss alert"
                          className="h-8 w-8 inline-flex items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.03] hover:border-white/[0.18] hover:bg-white/[0.08] text-[#8E95A2] hover:text-[#F4F5F7] cursor-pointer tactile-press"
                        >
                          <IconX className="h-3.5 w-3.5" />
                        </button>
                        {openMenuId === a.alert_id && (
                          <div className="absolute right-0 bottom-full mb-1.5 z-30 w-52 hud-glass rounded-xl py-1.5 shadow-2xl">
                            {DISMISS_OPTIONS.map((opt) => (
                              <button
                                key={opt.key}
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setOpenMenuId(null)
                                  onDismissAlert(a, opt.key)
                                }}
                                className="w-full text-left px-3 py-1.5 text-xs text-[#F4F5F7] hover:bg-white/[0.08] cursor-pointer"
                              >
                                {opt.label}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
              </motion.li>
            )
          })
        )}

        {filteredAlerts.length > 8 && (
          <li className="pt-1">
            <button
              type="button"
              onClick={() => setShowAll((s) => !s)}
              className="w-full rounded-xl border border-white/[0.08] bg-white/[0.03] hover:border-white/[0.18] py-2 text-xs font-medium text-[#8E95A2] hover:text-[#F4F5F7] cursor-pointer tactile-press"
            >
              {showAll
                ? 'Show top 8 directives'
                : `Show all ${filteredAlerts.length} directives (+${filteredAlerts.length - 8} more)`}
            </button>
          </li>
        )}
      </ul>
    </div>
  )
}
