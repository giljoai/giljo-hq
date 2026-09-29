
import { isOrchestrator } from '@/utils/agentDisplay'
import { needsInputOwner } from '@/utils/jobStatusWord'

export const JOBS_SECTION_LABELS = Object.freeze({
  STAGED: 'Staged',
  IMPLEMENTING: 'Implementing',
  NEEDS_INPUT: 'Needs Input',
  REVIEW: 'Review',
  PLANNING: 'Planning',
  ACTIVATED: 'Activated',
  COMPLETE: 'Complete',
  STOPPED: 'Stopped',
})

const STOPPED_PROJECT_STATUSES = new Set(['cancelled', 'terminated'])

const TERMINAL_AGENT_STATUSES = new Set(['complete', 'completed', 'decommissioned', 'closed'])

export function isReadyForReview(project, agents = []) {
  if (['completed', 'terminated', 'cancelled'].includes(project?.status)) return false
  if (project?.staging_status === 'staging_complete' && !project?.implementation_launched_at) return false
  if (!agents.length) return false
  const allTerminal = agents.every((a) => TERMINAL_AGENT_STATUSES.has(a?.status))
  if (!allTerminal) return false
  const orchestrator = agents.find(isOrchestrator)
  return Boolean(orchestrator && TERMINAL_AGENT_STATUSES.has(orchestrator.status))
}

export function jobsSectionLabelFor(project, agents = []) {
  if (project?.status === 'completed') return JOBS_SECTION_LABELS.COMPLETE
  if (STOPPED_PROJECT_STATUSES.has(project?.status)) return JOBS_SECTION_LABELS.STOPPED
  if (needsInputOwner(agents)) {
    return JOBS_SECTION_LABELS.NEEDS_INPUT
  }
  if (isReadyForReview(project, agents)) {
    return JOBS_SECTION_LABELS.REVIEW
  }
  if (project?.implementation_launched_at) {
    return JOBS_SECTION_LABELS.IMPLEMENTING
  }
  if (project?.staging_status === 'staging_complete') {
    return JOBS_SECTION_LABELS.STAGED
  }
  if (project?.staging_status === 'staging') {
    return JOBS_SECTION_LABELS.PLANNING
  }
  return JOBS_SECTION_LABELS.ACTIVATED
}
