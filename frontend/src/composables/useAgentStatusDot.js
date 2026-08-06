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
 * Every dot carries its label in the pill's tooltip. A colour the operator has to
 * decode from memory is a bug — that is also why the `?` legend exists.
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
 * @param {{status?: string|null, last_seen_at?: string|null}} participant
 * @returns {{color: string, ring: string, label: string, status: string|null}}
 */
export function agentStatusDot(participant) {
  if (!participant) return NEVER_REGISTERED

  const raw = participant.status
  // No status AND no sighting => this agent has never been heard from.
  if (!raw && !participant.last_seen_at) return NEVER_REGISTERED

  const status = !raw || UNMAPPED_TO_IDLE.has(raw) ? 'idle' : raw
  return {
    color: getStatusColor(status),
    ring: 'none',
    label: getStatusLabel(status),
    status: raw ?? null,
  }
}

/**
 * The pill's tooltip: everything the badge and dot encode, in words.
 * `{display_name} · {harness} · {status label}`.
 */
export function agentPillTitle(participant, harnessLabel) {
  const parts = [
    participant?.display_name || participant?.participant_id || 'Unnamed agent',
    harnessLabel,
    agentStatusDot(participant).label,
  ]
  return parts.filter(Boolean).join(' · ')
}
