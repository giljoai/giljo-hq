
import { getStatusColor, getStatusLabel } from '@/utils/statusConfig'

const NEVER_REGISTERED = Object.freeze({
  color: 'transparent',
  ring: 'inset 0 0 0 1.5px #757575',
  label: 'Never checked in',
  status: null,
})

const UNMAPPED_TO_IDLE = new Set(['staged'])

function displayStatus(participant) {
  if (!participant) return null
  const raw = participant.status
  if (!raw && !participant.last_seen_at) return null
  return !raw || UNMAPPED_TO_IDLE.has(raw) ? 'idle' : raw
}

export function agentStatusDot(participant) {
  const status = displayStatus(participant)
  if (!status) return NEVER_REGISTERED

  const raw = participant.status
  return {
    color: getStatusColor(status),
    ring: 'none',
    label: getStatusLabel(status),
    status: raw ?? null,
  }
}

const STATUS_MEANINGS = Object.freeze({
  waiting: 'posted and expecting a reply',
  working: 'actively running in its harness',
  blocked: 'stuck on something it cannot decide',
  awaiting_user: 'handed the call to you; drives the gold card',
  complete: 'finished its part of the work',
  idle: 'registered, watching, not working',
  sleeping: 'session parked, will resume',
  handed_over: 'passed its work to a successor',
  closed: 'accepted by the orchestrator',
  decommissioned: 'retired after succession',
})

export function agentStatusMeaning(participant) {
  const status = displayStatus(participant)
  if (!status) return ''
  return STATUS_MEANINGS[status] || ''
}

export function agentPillTitle(participant, harnessLabel) {
  const meaning = agentStatusMeaning(participant)
  const label = agentStatusDot(participant).label
  const parts = [
    participant?.display_name || participant?.participant_id || 'Unnamed agent',
    harnessLabel,
    meaning ? `${label}: ${meaning}` : label,
  ]
  return parts.filter(Boolean).join(' · ')
}
