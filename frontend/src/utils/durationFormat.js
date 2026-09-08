/**
 * durationFormat.js — FE-9548
 *
 * Pure (Vue-free) duration/time formatting helpers, extracted out of
 * AgentRow.vue's local `formatDuration` so the Jobs board's per-agent rows
 * (JobsBoardAgentRow) and its project-level aggregate stat strip can render
 * the SAME duration string an agent's row already shows elsewhere in the
 * product, instead of a second hand-rolled formatter drifting from it.
 *
 * `formatDurationSeconds` is the exact algorithm AgentRow used inline before
 * this extraction (behavior-preserving refactor) — AgentRow now imports it
 * too, so there is exactly one place that decides what "1h 12m" means.
 *
 * Edition scope: Both.
 */

/**
 * Format a duration given in seconds as a short human string:
 *   < 60s   -> "42s"
 *   < 1h    -> "3m 27s"
 *   >= 1h   -> "1h 12m"
 *
 * @param {number|null|undefined} totalSeconds
 * @returns {string} '---' when totalSeconds is null/undefined.
 */
export function formatDurationSeconds(totalSeconds) {
  if (totalSeconds == null) return '---'

  const seconds = Math.max(0, Math.floor(totalSeconds))
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}m ${secs}s`
  }
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  return `${hours}h ${mins}m`
}

/**
 * Resolve the number of elapsed seconds for an agent job, ticking locally
 * between WS events off `working_started_at` for non-terminal agents and
 * trusting the backend's frozen `duration_seconds` for terminal ones.
 *
 * Lifted verbatim from AgentRow.vue's `formatDuration` (BE-5107) so both the
 * wide JobsTab table row and the compact Jobs-board row agree on what an
 * agent's duration is, not just how it's printed.
 *
 * @param {{ status?: string, duration_seconds?: number, working_started_at?: string }} agent
 * @param {number} nowMs - caller-owned ticking timestamp (no internal timer)
 * @returns {number|null}
 */
export function resolveAgentDurationSeconds(agent, nowMs) {
  const terminal = agent?.status === 'complete' || agent?.status === 'closed'
  let total = agent?.duration_seconds
  if (!terminal && agent?.working_started_at) {
    const anchor = Date.parse(agent.working_started_at)
    if (!Number.isNaN(anchor)) {
      total = (nowMs - anchor) / 1000
    }
  }
  return total == null ? null : total
}

/**
 * Format an agent job's duration directly from the job + a ticking `now`.
 * Convenience wrapper over resolveAgentDurationSeconds + formatDurationSeconds.
 *
 * @param {object} agent
 * @param {number} nowMs
 * @returns {string}
 */
export function formatAgentDuration(agent, nowMs) {
  return formatDurationSeconds(resolveAgentDurationSeconds(agent, nowMs))
}

/**
 * Format an ISO timestamp as a short local time-of-day string (e.g. "22:14"),
 * for the Jobs board card's meta line ("launched 22:14 · 41m elapsed").
 *
 * @param {string|null|undefined} iso
 * @returns {string} '' when iso is missing/unparseable.
 */
export function formatTimeOfDay(iso) {
  if (!iso) return ''
  const parsed = Date.parse(iso)
  if (Number.isNaN(parsed)) return ''
  return new Date(parsed).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * Elapsed seconds between an ISO timestamp and a ticking `now`, floored at 0.
 *
 * @param {string|null|undefined} iso
 * @param {number} nowMs
 * @returns {number|null}
 */
export function elapsedSecondsSince(iso, nowMs) {
  if (!iso) return null
  const anchor = Date.parse(iso)
  if (Number.isNaN(anchor)) return null
  return Math.max(0, (nowMs - anchor) / 1000)
}
