import { useState } from 'react'

interface TactileSliderProps {
  value: number
  min: number
  max: number
  step?: number
  onChange: (value: number) => void
  ariaLabel: string
  ticks?: number[]
  className?: string
}

export function TactileSlider({
  value,
  min,
  max,
  step = 5,
  onChange,
  ariaLabel,
  ticks = [20, 45, 70, 95, 120],
  className = 'w-32',
}: TactileSliderProps) {
  const [dragging, setDragging] = useState(false)
  const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100))

  // Semantic storm severity fill: crisp white (light) -> amber (heavy) -> vermilion (cloudburst)
  const fillColor =
    value >= 90
      ? 'bg-[#EF4444]'
      : value >= 60
        ? 'bg-[#F59E0B]'
        : 'bg-[#F4F5F7]'

  return (
    <div className={`relative flex items-center h-6 select-none ${className}`}>
      {/* Base precision track */}
      <div className="relative h-1 w-full rounded-full bg-white/[0.12]">
        {/* Subtle calibration tick marks */}
        {ticks.map((t) => {
          const tickPct = ((t - min) / (max - min)) * 100
          if (tickPct <= 0 || tickPct >= 100) return null
          return (
            <span
              key={t}
              aria-hidden="true"
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 h-2 w-[1px] bg-white/[0.18] pointer-events-none"
              style={{ left: `${tickPct}%` }}
            />
          )
        })}

        {/* Active level fill */}
        <div
          className={`absolute inset-y-0 left-0 rounded-full transition-colors duration-150 ${fillColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Physical Braun-inspired thumb indicator */}
      <div
        aria-hidden="true"
        className={`pointer-events-none absolute top-1/2 -translate-y-1/2 -translate-x-1/2 h-3.5 w-3.5 rounded-full border border-[#090B0E] bg-[#F4F5F7] shadow-[0_1px_4px_rgba(0,0,0,0.65)] transition-transform duration-100 ${
          dragging ? 'scale-125 ring-4 ring-white/15' : 'scale-100'
        }`}
        style={{ left: `${pct}%` }}
      />

      {/* Native accessible range overlay for keyboard, drag & Playwright compatibility */}
      <input
        type="range"
        aria-label={ariaLabel}
        min={min}
        max={max}
        step={step}
        value={value}
        onPointerDown={() => setDragging(true)}
        onPointerUp={() => setDragging(false)}
        onPointerCancel={() => setDragging(false)}
        onBlur={() => setDragging(false)}
        onChange={(e) => onChange(Number(e.target.value))}
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer m-0"
      />
    </div>
  )
}
