import { formatDurationSeconds, formatTimeOfDay, elapsedSecondsSince } from '@/utils/durationFormat'
import { JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'

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

export function aggregateWaiting(agents = []) {
  return agents.reduce((sum, agent) => sum + (agent?.messages_waiting_count ?? 0), 0)
}

export function projectDurationSeconds(project, nowMs) {
  if (!project?.implementation_launched_at) return null
  const endMs = project?.completed_at ? Date.parse(project.completed_at) : nowMs
  if (Number.isNaN(endMs)) return null
  return elapsedSecondsSince(project.implementation_launched_at, endMs)
}

export function jobsBoardMetaLine(project, sectionLabel, nowMs, { chainMember = false } = {}) {
  if (sectionLabel === JOBS_SECTION_LABELS.STAGED) {
    const created = formatTimeOfDay(project?.created_at)
    if (chainMember) return created ? `created ${created}` : ''
    return created ? `created ${created} · awaiting your go` : 'awaiting your go'
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
    const seconds = projectDurationSeconds(project, nowMs)
    if (seconds === null) return completed ? `completed ${completed}` : 'completed'
    const total = formatDurationSeconds(seconds)
    return completed ? `completed ${completed} · ${total} total` : `${total} total`
  }
  const launched = formatTimeOfDay(project?.implementation_launched_at)
  const elapsed = formatDurationSeconds(projectDurationSeconds(project, nowMs))
  return launched ? `launched ${launched} · ${elapsed} elapsed` : `${elapsed} elapsed`
}

export const EMPTY_RUN_LABEL = 'No agent run recorded'
export const EMPTY_RUN_HINT =
  'This project was completed without the HQ staging flow, so there are no agent, step or time records.'

export function isEmptyAgentRun(project, agents = []) {
  return project?.status === 'completed' && !agents.length && !project?.agent_count
}

export function closeoutMissionText(project) {
  const summary = (project?.closeout_summary || '').trim()
  return summary ? `Closeout: ${summary}` : ''
}
