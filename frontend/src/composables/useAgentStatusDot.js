/**
 * useAgentStatusDot — the Hub card's status dot (FE-9365c).
 *
 * The dot answers "what is this agent doing right now" using the SAME colour
 * vocabulary as the Jobs dashboard, because the operator already learned it there.
 * Every hex comes from `statusConfig.js` via `getStatusColor` / `getStatusLabel`.
 * Do not re-pick a colour here and do not add one — a second vocabulary for the
 * same concept is worse than no colour at all.
 *
 * What this replaces: `isAgentLive()` gave a binary green/grey from a 5-minute
 * `last_seen_at` window. That invented a third meaning for green ("posted recently")
 * that contradicted the board's green ("finished"), so the same dot meant two
 * different things on two screens.
 *
 * Two rules that are load-bearing rather than cosmetic:
 *
 *   1. ABSENT DATA MUST NOT READ AS HEALTHY. A participant with no status falls back
 *      to idle slate, never to green. `getStatusColor` on its own would return the
 *      #666666 FALLBACK and the label "Unknown", so the normalisation to `idle`
 *      happens BEFORE the lookup, not after.
 *   2. NEVER REGISTERED IS NOT THE SAME AS IDLE. An agent that was invited to a
 *      thread but never checked in gets a hollow ring, not a filled dot. Filling it
 *      would claim we heard from something we never heard from.
 *
 * Every dot carries its label AND its meaning in the pill's tooltip. A colour the
 * operator has to decode from memory is a bug. FE-9368 removed the `?` legend panel as
 * redundant, which makes the tooltip the only explanation surface there is — so the
 * legend's one-line meanings moved here rather than being thrown away with it.
 */

import { getStatusColor, getStatusLabel } from '@/utils/statusConfig'

/**
 * An agent that has no execution record at all — invited, never arrived.
 * Transparent fill + inset ring, so it reads as an outline rather than a state.
 */
const NEVER_REGISTERED = Object.freeze({
  color: 'transparent',
  ring: 'inset 0 0 0 1.5px #757575',
  label: 'Never checked in',
  status: null,
})

/**
 * Statuses the backend can emit that `statusConfig` does not map.
 *
 * `agent_executions.status` includes `staged` (BE-6008: created pre-mission,
 * messageable but play-locked) which has no entry in the shared Jobs map. Left
 * alone it renders #666666 / "Unknown" — the failure mode where a store writes a
 * status the display map has never heard of.
 *
 * We deliberately do NOT add it to `statusConfig` from here: that map is the Jobs
 * board's vocabulary too, `$color-status-staged` is already spent on the amber that
 * means "your decision", and giving two states one colour is precisely the ambiguity
 * this composable exists to remove. Reading it as "registered, not working yet" —
 * which is what idle already means — is honest and needs no new colour.
 */
const UNMAPPED_TO_IDLE = new Set(['staged'])

/**
 * The status to DISPLAY for a participant, or null when it has never been heard from.
 * The single place the two normalisations live, so the dot's colour, its label and its
 * meaning can never disagree about which state they are describing.
 *
 * @param {{status?: string|null, last_seen_at?: string|null}} participant
 * @returns {string|null}
 */
function displayStatus(participant) {
  if (!participant) return null
  const raw = participant.status
  // No status AND no sighting => this agent has never been heard from.
  if (!raw && !participant.last_seen_at) return null
  return !raw || UNMAPPED_TO_IDLE.has(raw) ? 'idle' : raw
}

/**
 * @param {{status?: string|null, last_seen_at?: string|null}} participant
 * @returns {{color: string, ring: string, label: string, status: string|null}}
 */
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

/**
 * What each state MEANS to the operator, as opposed to what the enum calls it.
 * "blocked" is a state name; "stuck on something it cannot decide" is the thing the
 * operator needs in order to act. These lines are the ones the deleted legend carried
 * (FE-9368) — the panel went, the sentences did not.
 *
 * Keyed by the DISPLAYED status, so a state whose shared Jobs-board label is terse
 * ("Monitoring", "Waiting.") still explains itself. A status with no entry simply
 * shows its label, which is the honest degrade: no invented meaning.
 */
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

/**
 * The one-line meaning for a participant's state, or '' when there is nothing honest
 * to add (a never-registered agent's label already says everything known about it).
 */
export function agentStatusMeaning(participant) {
  const status = displayStatus(participant)
  if (!status) return ''
  return STATUS_MEANINGS[status] || ''
}

/**
 * The pill's tooltip: everything the badge and dot encode, in words.
 * `{display_name} · {harness} · {status label}: {what that state means}`.
 */
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
