
import { getAgentColor, getAgentColorKey } from '@/config/agentColors'

export function isOrchestrator(agent) {
  return agent?.agent_name === 'orchestrator' || agent?.agent_display_name === 'orchestrator'
}

export function getPrimaryAgentLabel(agent) {
  if (!agent) return ''
  if (isOrchestrator(agent)) return agent.agent_name || agent.agent_display_name || ''
  return agent.agent_display_name || agent.agent_name || ''
}

export function getAgentRoleLabel(agent) {
  if (isOrchestrator(agent)) return 'Fixed System Agent'
  const key = getAgentColorKey(agent) || agent?.agent_display_name || ''
  const name = getAgentColor(key)?.name || ''
  if (!name) return ''
  return name.charAt(0) + name.slice(1).toLowerCase()
}
