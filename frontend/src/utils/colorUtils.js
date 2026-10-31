
import { getAgentColor } from '@/config/agentColors'

export function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function toRgb(hex) {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
}

function toHex(rgb) {
  return `#${rgb.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')}`
}

function luminance(hex) {
  const [r, g, b] = toRgb(hex).map((v) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrastRatio(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

export function compositeOver(fg, bg, alpha) {
  const f = toRgb(fg)
  const b = toRgb(bg)
  return toHex(f.map((v, i) => alpha * v + (1 - alpha) * b[i]))
}

export function ensureContrast(fg, bg, min = 4.5) {
  let out = fg
  for (let t = 0.05; contrastRatio(out, bg) < min && t <= 1; t += 0.05) {
    out = compositeOver('#ffffff', fg, t)
  }
  return out
}

export const BADGE_SURFACE = '#1e3147'

const ROLE_BADGE_SURFACE = compositeOver('#ffffff', '#283c51', 0.04)

export function tintedStyle(hex) {
  return { backgroundColor: hexToRgba(hex, 0.15), color: hex }
}

export function accessibleTintedStyle(hex) {
  const tint = compositeOver(hex, BADGE_SURFACE, 0.15)
  return { backgroundColor: hexToRgba(hex, 0.15), color: ensureContrast(hex, tint, 4.5) }
}

export function getAgentBadgeStyle(agentName, alpha = 0.15) {
  const { hex } = getAgentColor(agentName)
  const tint = compositeOver(hex, ROLE_BADGE_SURFACE, alpha)
  return { backgroundColor: hexToRgba(hex, alpha), color: ensureContrast(hex, tint, 4.5) }
}
