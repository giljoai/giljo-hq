
import { isOrchestrator, getAgentRoleLabel } from '@/utils/agentDisplay'
import { getStatusLabel } from '@/utils/statusConfig'

const LIVE_STATUSES = new Set(['working', 'silent'])
const ORCHESTRATOR_STATES = new Set(['monitoring', 'result_waiting', 'silent'])

export function jobStatusWord(agent) {
  const status = agent?.status || ''
  if (!LIVE_STATUSES.has(status)) return status
  if (agent?.activity === 'holding') return 'holding'
  const derived = agent?.orchestrator_state?.state
  return ORCHESTRATOR_STATES.has(derived) ? derived : status
}

export function jobStatusLabel(agent) {
  const word = jobStatusWord(agent)
  if (word === agent?.orchestrator_state?.state && agent.orchestrator_state.label) return agent.orchestrator_state.label
  return getStatusLabel(word, agent?.block_reason)
}

export function isLiveStatusWord(word) {
  return word === 'working'
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

function ownerLabel(agent) {
  if (isOrchestrator(agent)) return 'Orchestrator'
  const role = getAgentRoleLabel(agent) || agent?.agent_display_name || agent?.agent_name || 'Agent'
  return role.charAt(0).toUpperCase() + role.slice(1)
}

export function needsInputOwner(agents = []) {
  const decisions = agents.filter((a) => a?.status === 'awaiting_user').length
  if (decisions > 0) {
    return {
      owner: 'operator',
      kind: 'decision',
      count: decisions,
      text: decisions === 1 ? 'Your decision needed' : `${decisions} decisions need you`,
      hint: 'An agent is waiting on a human choice. Open Jobs detail to decide, or answer in the Hub thread.',
    }
  }

  const blocked = agents.filter((a) => a?.status === 'blocked')
  if (blocked.length > 0) {
    return {
      owner: 'operator',
      kind: 'blocked',
      count: blocked.length,
      text: blocked.length === 1 ? `${ownerLabel(blocked[0])} blocked` : `${blocked.length} agents blocked`,
      hint: 'Stopped on a blocker it cannot clear on its own. Read the reason in Jobs detail or the Hub thread, then clear it or reassign the work.',
    }
  }

  const unreadHolder = agents.find((a) => (a?.action_required_unread ?? 0) > 0 && isOrchestrator(a))
    || agents.find((a) => (a?.action_required_unread ?? 0) > 0)
  if (unreadHolder) {
    const label = ownerLabel(unreadHolder)
    const count = unreadHolder.action_required_unread
    const waiting = Math.max(unreadHolder.messages_waiting_count ?? 0, count)
    return {
      owner: label.toLowerCase(),
      kind: 'unread',
      count,
      text: waiting === count ? `${label}: answer ${count}` : `${label}: answer ${count} of ${waiting}`,
      hint: `${plural(count, 'post')} in the Hub thread ${count === 1 ? 'asks' : 'ask'} the ${label.toLowerCase()} to act. It clears when they read and answer.`,
    }
  }

  const resultWaiting = agents.find((a) => isOrchestrator(a) && jobStatusWord(a) === 'result_waiting')
  if (resultWaiting) {
    return {
      owner: 'operator',
      kind: 'silent',
      count: resultWaiting.orchestrator_state?.agents || 1,
      text: 'Result not picked up',
      hint: 'A worker finished and the orchestrator has not picked up its result. Open its Hub thread and post, or replay its prompt from the row.',
    }
  }

  const silent = agents.filter((a) => jobStatusWord(a) === 'silent')
  if (silent.length > 0) {
    const orchestratorSilent = silent.some(isOrchestrator)
    if (orchestratorSilent) {
      return {
        owner: 'operator',
        kind: 'silent',
        count: silent.length,
        text: 'Orchestrator silent',
        hint: 'No progress report past the silence threshold with work still open. Nobody else can nudge the orchestrator, so this one is on you: open its Hub thread and post, or replay its prompt from the row.',
      }
    }
    const text = silent.length === 1 ? `${ownerLabel(silent[0])} silent` : `${silent.length} agents silent`
    return {
      owner: 'orchestrator',
      kind: 'silent',
      count: silent.length,
      text,
      hint: 'No progress report past the silence threshold with work still open. The orchestrator handles a silent worker; if it does not, post in the Hub thread.',
    }
  }
  return null
}
