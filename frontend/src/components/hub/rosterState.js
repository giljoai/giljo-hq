import { getStatusLabel } from '@/utils/statusConfig'

const TERMINAL_THREAD = new Set(['resolved', 'closed'])
const ACTIVE_STATUSES = new Set(['working', 'blocked', 'waiting', 'awaiting_user'])

const HARNESS_NAMES = {
  'claude-code': 'Claude Code',
  codex: 'Codex',
  opencode: 'OpenCode',
  gemini: 'Gemini CLI',
  antigravity: 'Antigravity',
  claude: 'Claude',
  chatgpt: 'ChatGPT',
  hermes: 'Hermes',
}

export function harnessLabel(harness) {
  if (!harness || harness === 'generic') return 'Generic Harness'
  if (HARNESS_NAMES[harness]) return HARNESS_NAMES[harness]
  return String(harness).split(' · ')[0]
}

export function rosterAgents(participants) {
  return (participants || []).filter((p) => p.participant_type !== 'user')
}

function neverHeardFrom(participant) {
  return !participant.status && !participant.last_seen_at
}

function holdsBaton(participant, thread) {
  const owner = thread?.next_action_owner
  return !!owner && owner === participant.participant_id
}

export function stateWords(participant, thread) {
  if (holdsBaton(participant, thread)) return 'holds baton'
  if (neverHeardFrom(participant)) return 'unknown'
  const status = participant.status || 'idle'
  if (status === 'awaiting_user') return 'needs you'
  if (status === 'working' || status === 'blocked') return status
  return getStatusLabel(status).replace(/\.$/, '').toLowerCase()
}

export function isActive(participant, thread) {
  return holdsBaton(participant, thread) || ACTIVE_STATUSES.has(participant.status)
}

function isThreadTerminal(thread) {
  return TERMINAL_THREAD.has(String(thread?.status || '').toLowerCase())
}

export function needYouIds(participants, thread, messages, userId) {
  const ids = new Set()
  if (!thread || isThreadTerminal(thread)) return ids
  const agents = new Set(rosterAgents(participants).map((p) => p.participant_id))
  for (const p of rosterAgents(participants)) {
    if (p.status === 'awaiting_user') ids.add(p.participant_id)
  }
  for (const m of messages || []) {
    if (m.requires_action && m.from_kind !== 'user' && agents.has(m.from_agent_id)) ids.add(m.from_agent_id)
  }
  if (userId && thread.next_action_owner === userId) {
    const lastAgentPost = [...(messages || [])].reverse().find((m) => m.from_kind !== 'user')
    if (lastAgentPost && agents.has(lastAgentPost.from_agent_id)) ids.add(lastAgentPost.from_agent_id)
  }
  return ids
}
