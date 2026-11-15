import {
  IconChevronDown,
  IconSliders,
  UrbanFlowLogo,
} from './Icons'
import { TactileSlider } from './TactileSlider'
import type { CatchmentKey } from '../lib/mock'
import type { Mode } from '../lib/scoring'

interface ControlIslandProps {
  region: CatchmentKey | 'all'
  setRegion: (r: CatchmentKey | 'all') => void
  rain: number
  setRain: (v: number) => void
  mode: Mode
  setMode: (m: Mode) => void
  degraded: boolean
  onReconfigure: () => void
}

export function ControlIsland({
  region,
  setRegion,
  rain,
  setRain,
  mode,
  setMode,
  degraded,
  onReconfigure,
}: ControlIslandProps) {
  const rainColor =
    rain >= 90 ? 'text-[#EF4444]' : rain >= 60 ? 'text-[#F59E0B]' : 'text-[#F4F5F7]'

  return (
    <header
      aria-label="Storm and Catchment Controls"
      className="fixed top-4 left-4 z-20 max-w-[calc(100vw-32px)] lg:max-w-[calc(100vw-448px)]"
    >
      <div className="hud-glass rounded-2xl px-3.5 py-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        {/* 1. Minimalist Brand Mark + Quiet Reconfigure Trigger */}
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex items-center gap-2 text-[#F4F5F7]">
            <UrbanFlowLogo className="h-4 w-4 shrink-0" />
            <span className="text-[13px] font-semibold tracking-[-0.015em]">UrbanFLOW</span>
          </div>
          {degraded && (
            <span
              title="Offline fallback active — local simulation running"
              className="h-1.5 w-1.5 rounded-full bg-[#F59E0B]"
            />
          )}
          <button
            type="button"
            onClick={onReconfigure}
            aria-label="Reconfigure session"
            title="Reconfigure fleet & storm setup"
            className="rounded-lg p-1 text-[#8E95A2] hover:text-[#F4F5F7] hover:bg-white/[0.06] cursor-pointer tactile-press"
          >
            <IconSliders className="h-3.5 w-3.5" />
          </button>
        </div>

        <span aria-hidden="true" className="hidden sm:block h-4 w-px bg-white/[0.08]" />

        {/* 2. Catchment Switcher */}
        <div className="relative shrink-0">
          <select
            aria-label="Catchment"
            value={region}
            onChange={(e) => setRegion(e.target.value as CatchmentKey | 'all')}
            className="appearance-none rounded-lg border border-white/[0.08] bg-white/[0.04] hover:border-white/[0.18] pl-2.5 pr-7 py-1 text-xs font-medium text-[#F4F5F7] focus:border-white/30 focus:outline-none cursor-pointer transition-colors"
          >
            <option value="all" className="bg-[#11141A] text-[#F4F5F7]">
              All Bengaluru
            </option>
            <option value="hsr" className="bg-[#11141A] text-[#F4F5F7]">
              HSR Layout
            </option>
            <option value="bellandur" className="bg-[#11141A] text-[#F4F5F7]">
              Bellandur &amp; ORR
            </option>
            <option value="whitefield" className="bg-[#11141A] text-[#F4F5F7]">
              Whitefield
            </option>
            <option value="ecity" className="bg-[#11141A] text-[#F4F5F7]">
              Electronic City
            </option>
            <option value="koramangala" className="bg-[#11141A] text-[#F4F5F7]">
              Koramangala
            </option>
          </select>
          <IconChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 h-3 w-3 text-[#8E95A2]" />
        </div>

        <span aria-hidden="true" className="hidden md:block h-4 w-px bg-white/[0.08]" />

        {/* 3. Tactile Rainfall Simulator Slider */}
        <div className="flex items-center gap-2.5 shrink-0">
          <span className="text-[11px] font-medium text-[#8E95A2]">Rain</span>
          <TactileSlider
            value={rain}
            min={20}
            max={120}
            step={5}
            onChange={setRain}
            ariaLabel="Rainfall intensity"
            className="w-24 sm:w-28"
          />
          <span className={`font-mono text-xs font-semibold tnum w-[62px] text-right ${rainColor}`}>
            {rain} mm/hr
          </span>
        </div>

        <span aria-hidden="true" className="hidden md:block h-4 w-px bg-white/[0.08]" />

        {/* 4. Safety Margin Toggle */}
        <button
          type="button"
          role="switch"
          aria-checked={mode === 'red_alert'}
          aria-label="Red-Alert Safety Margin"
          onClick={() => setMode(mode === 'normal' ? 'red_alert' : 'normal')}
          title="Standard (15 / 30 cm) vs Red-Alert Conservative Margin (9 / 25 cm)"
          className={`flex items-center gap-2 rounded-lg border px-2.5 py-1 text-xs font-medium cursor-pointer tactile-press shrink-0 ${
            mode === 'red_alert'
              ? 'border-[#EF4444]/50 bg-[#EF4444]/15 text-[#FCA5A5]'
              : 'border-white/[0.08] bg-white/[0.04] text-[#8E95A2] hover:border-white/[0.18] hover:text-[#F4F5F7]'
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full transition-colors ${
              mode === 'red_alert' ? 'bg-[#EF4444]' : 'bg-[#8E95A2]/60'
            }`}
          />
          <span>{mode === 'red_alert' ? 'Red-Alert' : 'Standard'}</span>
        </button>
      </div>
    </header>
  )
}
