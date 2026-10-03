
import { getAgentColor } from '@/config/agentColors'

export function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

export function tintedStyle(hex) {
  return { backgroundColor: hexToRgba(hex, 0.15), color: hex }
}

export function getAgentBadgeStyle(agentName) {
  return tintedStyle(getAgentColor(agentName).hex)
}
