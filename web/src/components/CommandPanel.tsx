import { motion } from 'framer-motion'
import { CorridorTab } from './CorridorTab'
import { DispatchTab } from './DispatchTab'
import { FleetTab } from './FleetTab'
import { IconChevronRight, IconPanelRight } from './Icons'
import type {
  ApiAlertDto,
  BootstrapDepot,
  BootstrapPoi,
  CorridorEndpoint,
  DismissReason,
  FleetSummaryDto,
  RouteComparisonDto,
  TransitCorridorDto,
  VehicleClass,
} from '../lib/api'
import type { CatchmentKey } from '../lib/mock'

export type CommandTab = 'dispatch' | 'corridors' | 'fleet'

interface CommandPanelProps {
  open: boolean
  onToggleOpen: (next: boolean) => void
  activeTab: CommandTab
  setActiveTab: (t: CommandTab) => void
  region: CatchmentKey | 'all'
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
  onInspectNodeId: (nodeId: string) => void
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
  fleet: FleetSummaryDto | null
  simClockMin?: number
  onTick5m: () => void
}

const TABS: { id: CommandTab; label: string }[] = [
  { id: 'dispatch', label: 'Dispatch' },
  { id: 'corridors', label: 'Corridors' },
  { id: 'fleet', label: 'Fleet' },
]

export function CommandPanel(props: CommandPanelProps) {
  const { open, onToggleOpen, activeTab, setActiveTab } = props
  const activeAlertCount = props.alerts.filter((a) => a.dispatch_status !== 'DISMISSED').length
  const disruptedCorridors = props.transit.summary.diverted + props.transit.summary.suspended

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => onToggleOpen(true)}
        aria-label="Open Command Panel"
        title="Open Command Panel (\)"
        className="fixed top-4 right-4 z-20 hud-glass rounded-xl px-3.5 py-2 inline-flex items-center gap-2 text-xs font-medium text-[#F4F5F7] hover:border-white/20 cursor-pointer tactile-press"
      >
        <IconPanelRight className="h-3.5 w-3.5 text-[#8E95A2]" />
        <span>Command</span>
        {activeAlertCount > 0 && (
          <span className="font-mono text-[10px] tnum rounded-md bg-white/[0.08] px-1.5 py-0.5 text-[#F4F5F7]">
            {activeAlertCount}
          </span>
        )}
      </button>
    )
  }

  return (
    <motion.aside
      aria-label="Command Drawer"
      initial={{ opacity: 0, x: 18 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: 'spring', bounce: 0, duration: 0.32 }}
      className="fixed z-20 hud-glass rounded-2xl flex flex-col overflow-hidden bottom-3 left-3 right-3 h-[52vh] md:left-auto md:top-4 md:right-4 md:bottom-4 md:h-auto md:w-[400px]"
    >
      {/* Segmented 3-Tab Header */}
      <div className="px-4 pt-3.5 pb-3 border-b border-white/[0.08] flex items-center justify-between gap-2 shrink-0">
        <div
          role="tablist"
          aria-label="Command workflows"
          className="relative flex-1 grid grid-cols-3 rounded-xl border border-white/[0.08] bg-[#090B0E]/75 p-1"
        >
          {TABS.map((t) => {
            const active = activeTab === t.id
            const badge =
              t.id === 'dispatch' && activeAlertCount > 0
                ? activeAlertCount
                : t.id === 'corridors' && disruptedCorridors > 0
                  ? disruptedCorridors
                  : null
            return (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setActiveTab(t.id)}
                className={`relative z-10 rounded-lg py-1.5 text-xs font-medium transition-colors cursor-pointer inline-flex items-center justify-center gap-1.5 ${
                  active ? 'text-[#090B0E] font-semibold' : 'text-[#8E95A2] hover:text-[#F4F5F7]'
                }`}
              >
                {active && (
                  <motion.span
                    layoutId="command-tab-pill"
                    transition={{ type: 'spring', bounce: 0, duration: 0.28 }}
                    className="absolute inset-0 rounded-lg bg-[#F4F5F7] -z-10"
                  />
                )}
                <span>{t.label}</span>
                {badge !== null && (
                  <span
                    className={`font-mono text-[10px] tnum rounded px-1 leading-4 ${
                      active
                        ? 'bg-[#090B0E]/12 text-[#090B0E]'
                        : t.id === 'corridors'
                          ? 'bg-[#F59E0B]/15 text-[#F59E0B]'
                          : 'bg-white/[0.07] text-[#8E95A2]'
                    }`}
                  >
                    {badge}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        <button
          type="button"
          onClick={() => onToggleOpen(false)}
          aria-label="Collapse command panel"
          title="Collapse panel (\)"
          className="shrink-0 h-8 w-8 inline-flex items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.03] text-[#8E95A2] hover:border-white/[0.18] hover:text-[#F4F5F7] cursor-pointer tactile-press"
        >
          <IconChevronRight className="h-4 w-4" />
        </button>
      </div>

      {/* Active Tab Content */}
      {activeTab === 'dispatch' && (
        <DispatchTab
          loading={props.loading}
          alerts={props.alerts}
          selectedAlertId={props.selectedAlertId}
          dismissFeedback={props.dismissFeedback}
          onClearDismissFeedback={props.onClearDismissFeedback}
          onSelectAlert={props.onSelectAlert}
          onLocateAlert={props.onLocateAlert}
          onApproveDispatch={props.onApproveDispatch}
          onDismissAlert={props.onDismissAlert}
          onVetoBarrier={props.onVetoBarrier}
          onReopenBarrier={props.onReopenBarrier}
        />
      )}

      {activeTab === 'corridors' && (
        <CorridorTab
          region={props.region}
          pois={props.pois}
          depots={props.depots}
          transit={props.transit}
          activeRoute={props.activeRoute}
          activeRouteLabel={props.activeRouteLabel}
          activeTransitId={props.activeTransitId}
          onSelectTransit={props.onSelectTransit}
          onInspectNodeId={props.onInspectNodeId}
          vehicleClass={props.vehicleClass}
          setVehicleClass={props.setVehicleClass}
          corridorOrigin={props.corridorOrigin}
          corridorDest={props.corridorDest}
          onRunCorridor={props.onRunCorridor}
          onClearCorridor={props.onClearCorridor}
          pickMode={props.pickMode}
          setPickMode={props.setPickMode}
          showBusRoutes={props.showBusRoutes}
          setShowBusRoutes={props.setShowBusRoutes}
          showHospitalCorridors={props.showHospitalCorridors}
          setShowHospitalCorridors={props.setShowHospitalCorridors}
        />
      )}

      {activeTab === 'fleet' && (
        <FleetTab fleet={props.fleet} simClockMin={props.simClockMin} onTick5m={props.onTick5m} />
      )}
    </motion.aside>
  )
}
