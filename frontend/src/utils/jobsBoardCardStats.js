/**
 * jobsBoardCardStats.js — FE-9548
 *
 * Pure (Vue-free) helpers computing the Jobs board card's project-level
 * aggregate stat strip (Steps / Agents / Waiting / Duration) and its meta
 * line ("launched 22:14 · 41m elapsed" / "staged 23:20 · awaiting your go" /
 * "completed 23:41 · 1h 12m total"), kept out of JobsBoardCard.vue so the
 * arithmetic is independently unit-testable.
 *
 * Edition scope: Both.
 */
import { formatDurationSeconds, formatTimeOfDay, elapsedSecondsSince } from '@/utils/durationFormat'
import { JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'

/**
 * @param {Array<{ steps?: { completed?: number, total?: number }, messages_waiting_count?: number }>} agents
 * @returns {{ completed: number, total: number, hasSteps: boolean }}
 */
export function aggregateSteps(agents = []) {
  let completed = 0
  let total = 0
  let hasSteps = false
  for (const agent of agents) {
    if (agent?.steps && typeof agent.steps.completed === 'number' && typeof agent.steps.total === 'number') {
      hasSteps = true
      completed += agent.steps.completed
      total += agent.steps.total
    }
  }
  return { completed, total, hasSteps }
}

/**
 * @param {Array<{ messages_waiting_count?: number }>} agents
 * @returns {number}
 */
export function aggregateWaiting(agents = []) {
  return agents.reduce((sum, agent) => sum + (agent?.messages_waiting_count ?? 0), 0)
}

/**
 * Project-level duration: null (rendered as '—') until implementation
 * launches; ticking elapsed seconds while in flight; frozen at completed_at
 * once the project reaches Review.
 *
 * @param {{ implementation_launched_at?: string | null, completed_at?: string | null }} project
 * @param {number} nowMs
 * @returns {number|null}
 */
export function projectDurationSeconds(project, nowMs) {
  if (!project?.implementation_launched_at) return null
  const endMs = project?.completed_at ? Date.parse(project.completed_at) : nowMs
  if (Number.isNaN(endMs)) return null
  return elapsedSecondsSince(project.implementation_launched_at, endMs)
}

/**
 * Build the card's meta line -- the ONE piece of prose the mock composes
 * from different signals depending on section: Staged says "awaiting your
 * go"; Planning says staging is in progress; Activated says the project
 * hasn't been staged yet; Review says "N total"; Implementing/Needs Input
 * say "N elapsed".
 *
 * FE-9551 regression fixed here: Activated and Planning are new pre-launch
 * states with no implementation_launched_at. Before these branches existed,
 * both fell into the final "launched/elapsed" default below, which computes
 * projectDurationSeconds() -> null -> formatDurationSeconds(null) === '---',
 * rendering the nonsensical "--- elapsed" for a project that has never
 * launched implementation.
 *
 * @param {object} project
 * @param {string} sectionLabel one of JOBS_SECTION_LABELS
 * @param {number} nowMs
 * @returns {string}
 */
export function jobsBoardMetaLine(project, sectionLabel, nowMs) {
  if (sectionLabel === JOBS_SECTION_LABELS.STAGED) {
    const staged = formatTimeOfDay(project?.created_at)
    return staged ? `staged ${staged} · awaiting your go` : 'awaiting your go'
  }
  if (sectionLabel === JOBS_SECTION_LABELS.PLANNING) {
    return 'staging in progress'
  }
  if (sectionLabel === JOBS_SECTION_LABELS.ACTIVATED) {
    const activated = formatTimeOfDay(project?.created_at)
    return activated ? `activated ${activated} · not yet staged` : 'not yet staged'
  }
  if (sectionLabel === JOBS_SECTION_LABELS.REVIEW) {
    const completed = formatTimeOfDay(project?.completed_at || project?.updated_at)
    const total = formatDurationSeconds(projectDurationSeconds(project, nowMs))
    return completed ? `completed ${completed} · ${total} total` : `${total} total`
  }
  const launched = formatTimeOfDay(project?.implementation_launched_at)
  const elapsed = formatDurationSeconds(projectDurationSeconds(project, nowMs))
  return launched ? `launched ${launched} · ${elapsed} elapsed` : `${elapsed} elapsed`
}
