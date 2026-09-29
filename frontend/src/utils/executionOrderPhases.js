
import { isOrchestrator } from '@/utils/agentDisplay'
import { isSubagentExecutionMode } from '@/composables/useExecutionMode'
import { getAgentColor, getAgentColorKey } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'

const NO_PHASE = 999

function paint(displayName, colorKey) {
  const color = getAgentColor(colorKey).hex
  return { displayName, color, tintedBg: hexToRgba(color, 0.15) }
}

export function buildExecutionOrderPhases(agents = [], executionMode = null) {
  if (isSubagentExecutionMode(executionMode)) return null
  const list = Array.isArray(agents) ? agents : []
  if (!list.some((agent) => agent?.phase != null)) return null

  const groups = new Map()
  for (const agent of list) {
    if (isOrchestrator(agent)) continue
    const phase = typeof agent?.phase === 'number' ? agent.phase : NO_PHASE
    if (!groups.has(phase)) groups.set(phase, [])
    groups.get(phase).push(paint(agent.agent_display_name || agent.agent_name || 'unknown', getAgentColorKey(agent)))
  }

  const phases = [{ label: 'Start', agents: [paint('Orchestrator', 'orchestrator')] }]
  for (const phase of [...groups.keys()].sort((a, b) => a - b)) {
    const members = groups.get(phase)
    const number = phase === NO_PHASE ? '?' : phase
    phases.push({ label: members.length > 1 ? `Phase ${number} Parallel Execution` : `Phase ${number}`, agents: members })
  }
  return phases
}
