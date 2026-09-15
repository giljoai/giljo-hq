
import { getAgentColor } from '@/config/agentColors'
import { TEXT_MUTED } from '@/config/colorTokens'

export function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

export function getAgentBadgeStyle(agentName) {
  const colorObj = getAgentColor(agentName)
  const hex = colorObj?.hex || TEXT_MUTED
  return {
    backgroundColor: hexToRgba(hex, 0.15),
    color: hex,
    borderRadius: '8px',
  }
}
