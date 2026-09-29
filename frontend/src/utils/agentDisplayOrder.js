
import { isOrchestrator } from '@/utils/agentDisplay'

const NO_PHASE = Number.MAX_SAFE_INTEGER

function phaseOf(agent) {
  if (isOrchestrator(agent)) return -1
  const phase = agent?.phase
  return typeof phase === 'number' && Number.isFinite(phase) ? phase : NO_PHASE
}

export function orderAgentsForDisplay(agents = []) {
  if (!Array.isArray(agents)) return []
  return agents
    .map((agent, index) => ({ agent, index, phase: phaseOf(agent) }))
    .sort((a, b) => a.phase - b.phase || a.index - b.index)
    .map((entry) => entry.agent)
}
