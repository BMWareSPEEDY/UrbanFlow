import { motion } from 'framer-motion'
import { IconNav, IconPin, IconShieldAlert, IconX } from './Icons'
import type { ApiAlertDto, ApiNodeDto, CorridorEndpoint } from '../lib/api'
import { bandBadgeClass, bandHumanLabel } from '../lib/scoring'

interface Props {
  node: ApiNodeDto
  matchingAlert?: ApiAlertDto
  corridorOrigin: CorridorEndpoint | null
  rightOpen: boolean
  onSetOrigin: (n: ApiNodeDto) => void
  onClearOrigin?: () => void
  onRouteToNode: (n: ApiNodeDto) => void
  onDispatchAlert?: (alert: ApiAlertDto) => void
  onClose: () => void
}

export function NodeInspector({
  node,
  matchingAlert,
  corridorOrigin,
  rightOpen,
  onSetOrigin,
  onClearOrigin,
  onRouteToNode,
  onDispatchAlert,
  onClose,
}: Props) {
  const depthCm = (node.depth_m * 100).toFixed(0)
  const canDispatch =
    Boolean(matchingAlert && matchingAlert.feasible && matchingAlert.dispatch_status === 'PENDING' && onDispatchAlert)

  return (
    <motion.aside
      aria-label="Node Inspector"
      initial={{ opacity: 0, y: 8, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, scale: 0.97 }}
      transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
      className={`fixed z-20 w-[288px] xl:w-[320px] max-w-[calc(100vw-32px)] hud-glass rounded-2xl p-4 text-xs text-[#F4F5F7] space-y-3.5 ${
        rightOpen ? 'top-[108px] left-4 lg:left-auto lg:right-[432px] lg:top-[76px] 2xl:top-4' : 'top-[108px] left-4 sm:left-auto sm:right-4 sm:top-[76px]'
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span
              className={`rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${bandBadgeClass(
                node.band,
              )}`}
            >
              {bandHumanLabel(node.band)}
            </span>
            <span className="text-[11px] font-medium uppercase tracking-wide text-[#8E95A2]">
              {node.catchment}
            </span>
            {node.barrier_locked && (
              <span className="inline-flex items-center gap-1 rounded-md border border-[#EF4444]/40 bg-[#EF4444]/15 px-1.5 py-0.5 text-[10px] font-medium text-[#FCA5A5]">
                <IconShieldAlert className="h-2.5 w-2.5" />
                Locked
              </span>
            )}
          </div>
          <h3 className="text-sm font-semibold text-[#F4F5F7] truncate" title={node.name}>
            {node.name}
          </h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close inspector"
          className="shrink-0 rounded-lg p-1 text-[#8E95A2] hover:bg-white/[0.08] hover:text-[#F4F5F7] cursor-pointer tactile-press"
        >
          <IconX className="h-4 w-4" />
        </button>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-3 gap-2 font-mono tnum">
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-2.5 py-2">
          <div className="text-[10px] font-sans text-[#8E95A2]">Depth</div>
          <div
            className={`mt-0.5 text-[13px] font-semibold whitespace-nowrap ${
              node.depth_m >= 0.25
                ? 'text-[#EF4444]'
                : node.depth_m >= 0.08
                  ? 'text-[#F59E0B]'
                  : 'text-[#F4F5F7]'
            }`}
          >
            {depthCm} cm
          </div>
        </div>
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-2.5 py-2">
          <div className="text-[10px] font-sans text-[#8E95A2]">Elevation</div>
          <div className="mt-0.5 text-[13px] font-semibold text-[#F4F5F7] whitespace-nowrap">
            {node.elevation.toFixed(1)} m
          </div>
        </div>
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-2.5 py-2">
          <div className="text-[10px] font-sans text-[#8E95A2]">Sink / Peak</div>
          <div className="mt-0.5 text-[13px] font-semibold text-[#F4F5F7] whitespace-nowrap">
            {node.sink.toFixed(1)} · {node.ttp_min.toFixed(0)}m
          </div>
        </div>
      </div>

      {/* Action Footer */}
      <div className="pt-2.5 border-t border-white/[0.08] space-y-2">
        {canDispatch && matchingAlert && onDispatchAlert && (
          <button
            type="button"
            onClick={() => onDispatchAlert(matchingAlert)}
            className={`w-full rounded-xl px-3 py-2 text-xs font-semibold cursor-pointer tactile-press ${
              matchingAlert.priority === 'P1'
                ? 'bg-[#EF4444] hover:bg-[#DC2626] text-white'
                : 'bg-[#F4F5F7] hover:bg-white text-[#090B0E]'
            }`}
          >
            {matchingAlert.unit_class === 'pump'
              ? `Dispatch Nearest Pump (${matchingAlert.eta_min?.toFixed(0) ?? '—'}m)`
              : `Dispatch ${matchingAlert.action_label} (${matchingAlert.eta_min?.toFixed(0) ?? '—'}m)`}
          </button>
        )}

        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => onSetOrigin(node)}
            className="flex items-center justify-center gap-1.5 rounded-xl border border-white/[0.08] bg-white/[0.04] hover:border-white/[0.18] px-2.5 py-1.5 text-[11px] font-medium text-[#F4F5F7] cursor-pointer tactile-press"
          >
            <IconPin className="h-3 w-3 text-[#8E95A2]" />
            Set Origin A
          </button>
          <button
            type="button"
            disabled={!corridorOrigin || corridorOrigin.spec === node.id}
            onClick={() => onRouteToNode(node)}
            title={
              !corridorOrigin
                ? 'Set Origin A first'
                : corridorOrigin.spec === node.id
                  ? 'Destination matches Origin A'
                  : 'Compute flood-safe route to this junction'
            }
            className="flex items-center justify-center gap-1.5 rounded-xl border border-white/[0.08] bg-white/[0.04] hover:border-white/[0.18] disabled:opacity-35 px-2.5 py-1.5 text-[11px] font-medium text-[#F4F5F7] cursor-pointer tactile-press"
          >
            <IconNav className="h-3 w-3 text-[#10B981]" />
            Route Here
          </button>
        </div>
        {corridorOrigin && (
          <div className="flex items-center justify-between gap-2 text-[11px] text-[#8E95A2]">
            <span className="truncate">Origin A: {corridorOrigin.label}</span>
            {onClearOrigin && (
              <button
                type="button"
                onClick={onClearOrigin}
                className="shrink-0 text-[10px] font-medium text-[#8E95A2] hover:text-[#F4F5F7] cursor-pointer"
              >
                Clear
              </button>
            )}
          </div>
        )}
      </div>
    </motion.aside>
  )
}
