import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  IconAlert,
  IconArrowRight,
  IconChevronDown,
  UrbanFlowLogo,
} from './Icons'
import { TactileSlider } from './TactileSlider'
import type { CatchmentKey } from '../lib/mock'
import type { Mode } from '../lib/scoring'

export interface CommandConfig {
  operator: string
  region: CatchmentKey | 'all'
  rain: number
  duration: number
  mode: Mode
  pumps: number
  barriers: number
  wardens: number
}

export const DEFAULT_CONFIG: CommandConfig = {
  operator: 'duty-officer',
  region: 'all',
  rain: 95,
  duration: 60,
  mode: 'normal',
  pumps: 12,
  barriers: 8,
  wardens: 6,
}

const REGIONS: { key: CatchmentKey | 'all'; label: string }[] = [
  { key: 'all', label: 'All Bengaluru · 5 Catchments' },
  { key: 'hsr', label: 'HSR Layout · Residential' },
  { key: 'bellandur', label: 'Bellandur & ORR · Lake Basin' },
  { key: 'whitefield', label: 'Whitefield · ITPB Corridor' },
  { key: 'ecity', label: 'Electronic City · Tech Corridor' },
  { key: 'koramangala', label: 'Koramangala & Indiranagar' },
]

interface Props {
  initial?: CommandConfig | null
  busy?: boolean
  error?: string | null
  onSubmit: (cfg: CommandConfig) => void
}

function InventoryField({
  label,
  hint,
  value,
  max,
  onChange,
}: {
  label: string
  hint: string
  value: number
  max: number
  onChange: (n: number) => void
}) {
  const clamp = (raw: number) =>
    Number.isFinite(raw) ? Math.max(0, Math.min(max, Math.round(raw))) : 0

  return (
    <div className="hud-card rounded-xl p-3.5 flex flex-col justify-between gap-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-[#F4F5F7]">{label}</span>
        <span className="text-[11px] font-mono text-[#8E95A2] tnum">0–{max}</span>
      </div>

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => onChange(clamp(value - 1))}
          disabled={value <= 0}
          aria-label={`Decrease ${label}`}
          className="h-8 w-8 shrink-0 rounded-lg border border-white/[0.08] bg-white/[0.03] text-sm font-mono text-[#F4F5F7] hover:border-white/[0.18] hover:bg-white/[0.06] disabled:opacity-30 cursor-pointer tactile-press"
        >
          −
        </button>
        <input
          type="number"
          aria-label={label}
          min={0}
          max={max}
          step={1}
          value={value}
          onChange={(e) => onChange(clamp(Number(e.target.value)))}
          className="h-8 w-full min-w-0 rounded-lg border border-white/[0.08] bg-[#090B0E]/80 px-2 text-center font-mono text-sm font-semibold text-[#F4F5F7] tnum focus:border-white/30 focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
        />
        <button
          type="button"
          onClick={() => onChange(clamp(value + 1))}
          disabled={value >= max}
          aria-label={`Increase ${label}`}
          className="h-8 w-8 shrink-0 rounded-lg border border-white/[0.08] bg-white/[0.03] text-sm font-mono text-[#F4F5F7] hover:border-white/[0.18] hover:bg-white/[0.06] disabled:opacity-30 cursor-pointer tactile-press"
        >
          +
        </button>
      </div>

      <span className="text-[11px] text-[#8E95A2] leading-tight">{hint}</span>
    </div>
  )
}

export function SetupScreen({ initial, busy = false, error, onSubmit }: Props) {
  const seed = initial ?? DEFAULT_CONFIG
  const [operator, setOperator] = useState(seed.operator)
  const [region, setRegion] = useState<CatchmentKey | 'all'>(seed.region)
  const [rain, setRain] = useState(seed.rain)
  const [duration, setDuration] = useState(seed.duration)
  const [mode, setMode] = useState<Mode>(seed.mode)
  const [pumps, setPumps] = useState(seed.pumps)
  const [barriers, setBarriers] = useState(seed.barriers)
  const [wardens, setWardens] = useState(seed.wardens)

  const oversized = pumps > 18

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({
      operator: operator.trim() || 'duty-officer',
      region,
      rain: Math.max(20, Math.min(120, Math.round(rain))),
      duration,
      mode,
      pumps: Math.max(0, Math.min(30, Math.round(pumps))),
      barriers: Math.max(0, Math.min(24, Math.round(barriers))),
      wardens: Math.max(0, Math.min(24, Math.round(wardens))),
    })
  }

  return (
    <div className="h-screen w-screen overflow-y-auto bg-[#090B0E] setup-grid text-[#F4F5F7] flex items-center justify-center p-4 sm:p-6">
      <motion.form
        onSubmit={handleSubmit}
        initial={{ opacity: 0, y: 12, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, scale: 0.97 }}
        transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}
        className="hud-glass w-full max-w-2xl rounded-2xl p-6 sm:p-8 space-y-6 my-auto"
      >
        {/* Brand & Title */}
        <div className="flex items-start justify-between gap-4 border-b border-white/[0.08] pb-5">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-[#F4F5F7]">
              <UrbanFlowLogo className="h-5 w-5 shrink-0" />
              <span className="text-sm font-semibold tracking-[-0.015em]">UrbanFLOW</span>
            </div>
            <h1 className="text-xl sm:text-2xl font-semibold tracking-[-0.02em] text-[#F4F5F7]">
              Configure shift fleet &amp; storm parameters
            </h1>
            <p className="text-xs sm:text-sm text-[#8E95A2]">
              HydroGINE flood telemetry and dispatch routing across 12,436 Bengaluru street junctions.
            </p>
          </div>
        </div>

        {/* Fleet Inventory */}
        <div className="space-y-2.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-[#F4F5F7]">Available Shift Fleet</span>
            <span className="text-[11px] text-[#8E95A2]">
              Set to 0 to simulate resource scarcity
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <InventoryField
              label="Mobile Pumps"
              hint="1,500 L/min @ 6 depots"
              value={pumps}
              max={30}
              onChange={setPumps}
            />
            <InventoryField
              label="Flood Barriers"
              hint="Underpass locks · 60s veto"
              value={barriers}
              max={24}
              onChange={setBarriers}
            />
            <InventoryField
              label="Traffic Wardens"
              hint="Diversion & transit crews"
              value={wardens}
              max={24}
              onChange={setWardens}
            />
          </div>

          {oversized && (
            <div className="flex items-center gap-2 rounded-xl border border-[#F59E0B]/30 bg-[#F59E0B]/10 px-3 py-2 text-xs text-[#FCD34D]">
              <IconAlert className="h-3.5 w-3.5 shrink-0" />
              <span>
                Oversized pump pool ({pumps} &gt; 18 nominal): scarcity warnings may rarely appear.
              </span>
            </div>
          )}
        </div>

        {/* Jurisdiction & Operator */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block space-y-1.5">
            <span className="block text-xs font-medium text-[#8E95A2]">Operational Catchment</span>
            <div className="relative">
              <select
                aria-label="Operational Jurisdiction"
                value={region}
                onChange={(e) => setRegion(e.target.value as CatchmentKey | 'all')}
                className="w-full appearance-none rounded-xl border border-white/[0.08] bg-[#090B0E]/85 px-3 py-2.5 pr-8 text-xs font-medium text-[#F4F5F7] focus:border-white/30 focus:outline-none cursor-pointer"
              >
                {REGIONS.map((r) => (
                  <option key={r.key} value={r.key} className="bg-[#11141A] text-[#F4F5F7]">
                    {r.label}
                  </option>
                ))}
              </select>
              <IconChevronDown className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[#8E95A2]" />
            </div>
          </label>

          <label className="block space-y-1.5">
            <span className="block text-xs font-medium text-[#8E95A2]">Operator ID</span>
            <input
              type="text"
              aria-label="Operator ID"
              value={operator}
              maxLength={48}
              onChange={(e) => setOperator(e.target.value)}
              className="w-full rounded-xl border border-white/[0.08] bg-[#090B0E]/85 px-3 py-2.5 text-xs font-mono text-[#F4F5F7] focus:border-white/30 focus:outline-none"
            />
          </label>
        </div>

        {/* Storm Forcing & Margin */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-[#8E95A2]">Rainfall Rate</span>
              <span
                className={`font-mono font-semibold tnum ${
                  rain >= 90
                    ? 'text-[#EF4444]'
                    : rain >= 60
                      ? 'text-[#F59E0B]'
                      : 'text-[#F4F5F7]'
                }`}
              >
                {rain} mm/hr
              </span>
            </div>
            <TactileSlider
              value={rain}
              min={20}
              max={120}
              step={5}
              onChange={setRain}
              ariaLabel="Rainfall intensity"
              className="w-full"
            />
          </div>

          <div className="space-y-1.5">
            <span className="block text-xs font-medium text-[#8E95A2]">Storm Duration</span>
            <div className="grid grid-cols-4 gap-1 rounded-xl border border-white/[0.08] bg-[#090B0E]/75 p-1">
              {[15, 30, 60, 120].map((d) => {
                const active = duration === d
                return (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setDuration(d)}
                    className={`rounded-lg py-1.5 text-xs font-mono tnum transition-colors cursor-pointer ${
                      active
                        ? 'bg-white/[0.12] text-[#F4F5F7] font-semibold'
                        : 'text-[#8E95A2] hover:text-[#F4F5F7]'
                    }`}
                  >
                    {d}m
                  </button>
                )
              })}
            </div>
          </div>

          <div className="space-y-1.5">
            <span className="block text-xs font-medium text-[#8E95A2]">Safety Margin</span>
            <div className="grid grid-cols-2 gap-1 rounded-xl border border-white/[0.08] bg-[#090B0E]/75 p-1">
              <button
                type="button"
                onClick={() => setMode('normal')}
                className={`rounded-lg py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                  mode === 'normal'
                    ? 'bg-white/[0.12] text-[#F4F5F7]'
                    : 'text-[#8E95A2] hover:text-[#F4F5F7]'
                }`}
              >
                Standard
              </button>
              <button
                type="button"
                onClick={() => setMode('red_alert')}
                className={`rounded-lg py-1.5 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 cursor-pointer ${
                  mode === 'red_alert'
                    ? 'bg-[#EF4444]/20 text-[#FCA5A5] ring-1 ring-[#EF4444]/40 font-semibold'
                    : 'text-[#8E95A2] hover:text-[#F4F5F7]'
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    mode === 'red_alert' ? 'bg-[#EF4444]' : 'bg-[#8E95A2]/50'
                  }`}
                />
                Red-Alert
              </button>
            </div>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-[#EF4444]/40 bg-[#EF4444]/10 px-3.5 py-2.5 text-xs text-[#FCA5A5]">
            {error}
          </div>
        )}

        {/* Submit Footer */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-4 border-t border-white/[0.08]">
          <div className="text-xs text-[#8E95A2] font-mono tnum">
            {pumps}P · {barriers}B · {wardens}W ·{' '}
            {mode === 'red_alert' ? 'Red-Alert (9 / 25 cm)' : 'Standard (15 / 30 cm)'}
          </div>
          <button
            type="submit"
            disabled={busy}
            className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl bg-[#F4F5F7] hover:bg-white disabled:opacity-50 px-5 py-2.5 text-sm font-semibold text-[#090B0E] cursor-pointer tactile-press"
          >
            <span>{busy ? 'Initializing…' : 'Enter Command Center'}</span>
            <IconArrowRight className="h-4 w-4 shrink-0" />
          </button>
        </div>
      </motion.form>
    </div>
  )
}
