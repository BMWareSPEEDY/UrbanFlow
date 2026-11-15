export type Mode = 'normal' | 'red_alert'
export type Band = 'dry' | 'watch' | 'barrier' | 'pump'
export type Priority = 'P1' | 'P2' | 'P3' | 'suppressed'

export const THRESHOLDS: Record<
  Mode,
  { alertFloor: number; barrier: number; pump: number }
> = {
  normal: { alertFloor: 0.08, barrier: 0.15, pump: 0.30 },
  red_alert: { alertFloor: 0.08, barrier: 0.09, pump: 0.25 },
}

export const ASSET_WEIGHT: Record<string, number> = {
  underpass: 1.0,
  transit_hub: 0.95,
  hospital: 0.95,
  fire_station: 0.9,
  power_substation: 0.85,
  school: 0.7,
  arterial: 0.6,
  watercourse: 0.55,
  street: 0.25,
}

export const BAND_RGBA: Record<Band, [number, number, number, number]> = {
  dry: [38, 43, 53, 85],
  watch: [245, 158, 11, 215],
  barrier: [245, 125, 11, 235],
  pump: [239, 68, 68, 250],
}

export const ROUTE_RGBA = {
  standard: [56, 189, 248, 240] as [number, number, number, number],
  floodedSegment: [255, 86, 86, 255] as [number, number, number, number],
  safe: [16, 185, 129, 245] as [number, number, number, number],
  interStub: [16, 185, 129, 245] as [number, number, number, number],
  depot: [244, 245, 247, 215] as [number, number, number, number],
  poi: [142, 149, 162, 140] as [number, number, number, number],
  busRoute: [142, 149, 162, 135] as [number, number, number, number],
  hospital: [16, 185, 129, 230] as [number, number, number, number],
}

export function bandFromDepth(depthM: number, mode: Mode): Band {
  const th = THRESHOLDS[mode]
  if (depthM >= th.pump) return 'pump'
  if (depthM >= th.barrier) return 'barrier'
  if (depthM >= th.alertFloor) return 'watch'
  return 'dry'
}

export const band = bandFromDepth

export function consequenceScore(opts: {
  depthM: number
  asset: number
  vulnerability: number
  network: number
}): number {
  const { depthM, asset, vulnerability, network } = opts
  const s = Math.max(0, Math.min(1, (depthM - 0.05) / 0.35))
  const a = Math.max(0, Math.min(1, asset))
  const v = Math.max(0, Math.min(1, vulnerability))
  const n = Math.max(0, Math.min(1, network))
  return Math.round(1000 * (0.45 * s + 0.3 * a + 0.15 * v + 0.1 * n)) / 10
}

export function priority(score: number): Priority {
  if (score >= 70) return 'P1'
  if (score >= 50) return 'P2'
  if (score >= 30) return 'P3'
  return 'suppressed'
}

export function edgeColorRgba(depthM: number, mode: Mode): [number, number, number, number] {
  if (depthM < 0.02) return [38, 43, 53, 75]
  const b = bandFromDepth(depthM, mode)
  if (b === 'dry') return [58, 65, 80, 110]
  return BAND_RGBA[b]
}

export function bandBadgeClass(bandVal: Band): string {
  switch (bandVal) {
    case 'pump':
      return 'bg-[#EF4444]/15 text-[#FCA5A5] border-[#EF4444]/40'
    case 'barrier':
      return 'bg-[#F59E0B]/15 text-[#FCD34D] border-[#F59E0B]/40'
    case 'watch':
      return 'bg-[#F59E0B]/10 text-[#FDE68A] border-[#F59E0B]/30'
    default:
      return 'bg-white/[0.04] text-[#8E95A2] border-white/[0.08]'
  }
}

export function priorityBadgeClass(p: Priority): string {
  switch (p) {
    case 'P1':
      return 'bg-[#EF4444] text-white'
    case 'P2':
      return 'bg-[#F59E0B] text-[#090B0E]'
    case 'P3':
      return 'bg-white/15 text-[#F4F5F7]'
    default:
      return 'bg-white/[0.06] text-[#8E95A2]'
  }
}

export function bandHumanLabel(b: Band): string {
  switch (b) {
    case 'pump':
      return 'Critical'
    case 'barrier':
      return 'Submerged'
    case 'watch':
      return 'Watch'
    default:
      return 'Clear'
  }
}

export function formatMinutes(min: number | null | undefined, compact = false): string {
  if (min === null || min === undefined || !Number.isFinite(min)) return '—'
  const rounded = Math.max(0, Math.round(min))
  if (compact) return `${String(rounded).padStart(2, '0')}m`
  return `${min.toFixed(1)}m`
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`
}
