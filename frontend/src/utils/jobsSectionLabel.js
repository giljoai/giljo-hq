/**
 * jobsSectionLabel.js — FE-9525d
 *
 * Pure (Vue-free) helper: the section label the plural Jobs viewport shows
 * for one in-flight project. The operator's D8 design ruling names three
 * concrete states in its ASCII mock: IMPLEMENTING, NEEDS INPUT, STAGED. Derived from
 * server-tracked lifecycle fields already present on the project row
 * (implementation_launched_at) plus the per-project agent execution statuses
 * (the same "blocked"/"silent" statuses statusConfig.js labels "Needs Input"
 * at the agent-row level) -- so this surface and JobsTab's own agent rows
 * never disagree about what "needs input" means.
 *
 * "Paused" is named in D8's prose bullet but not demonstrated in the ASCII
 * mock or given a concrete server signal anywhere else in the codebase this
 * project touches (project.status has no "paused" value). Left unmapped
 * rather than guessed at -- flagged to the orchestrator as an open question
 * instead of invented.
 *
 * "Claim" never appears in this vocabulary (ruling 19 / D8). "Active" WAS
 * banned by that same ruling, on the premise that the existing lifecycle
 * states already expressed everything a card needed to say. FE-9551
 * overrides that specific premise: an activated
 * project that has never entered staging (staging_status null/undefined, not
 * launched) had NO label at all, so the catch-all below silently mislabeled
 * it "Staged". The operator's words: "yes I agree with a add activated."
 * Shipped label set is now Activated / Planning / Staged / Implementing /
 * Needs Input / Review -- see the FE-9551 project record and the D8 ruling
 * correction it cites (operator-internal decision log, not shipped here).
 *
 * Edition scope: Both.
 */

import { isOrchestrator } from '@/utils/agentDisplay'

export const JOBS_SECTION_LABELS = Object.freeze({
  STAGED: 'Staged',
  IMPLEMENTING: 'Implementing',
  NEEDS_INPUT: 'Needs Input',
  // FE-9548: a project whose agents have all reached a terminal state but
  // hasn't been reviewed/closed out yet. Distinct from "completed" project
  // status -- the project stays in the active/in-flight set (and on the Jobs
  // board) until the operator actually reviews it, matching the mock's
  // "reviewed projects leave the board" rule.
  REVIEW: 'Review',
  // FE-9551: Project.staging_status === 'staging' -- staging is actively in
  // progress. Reuses the exact word statusConfig.js already uses for this
  // server value at the agent-row level rather than minting a second word.
  PLANNING: 'Planning',
  // FE-9551: the real "everything else" floor -- staging_status is
  // null/undefined (staging never started) and implementation hasn't
  // launched. This used to fall into the STAGED catch-all below, which
  // claimed a project was staged when it had never been staged at all.
  ACTIVATED: 'Activated',
})

const TERMINAL_AGENT_STATUSES = new Set(['complete', 'completed', 'decommissioned', 'closed'])

/**
 * True when every agent on this project has reached a terminal status AND
 * the orchestrator itself is terminal -- the same "ready for closeout" gate
 * useProjectCloseout.js's `allJobsTerminal` computed already enforces for the
 * single-project Review & Close button. Mirrored here (not imported) because
 * that composable is Vue-reactive (refs/computed) and this file stays a pure,
 * Vue-free helper usable from both the view and its unit tests.
 *
 * @param {{ status?: string, staging_status?: string, implementation_launched_at?: string | null }} project
 * @param {Array<{ status?: string, agent_name?: string, agent_display_name?: string }>} [agents]
 * @returns {boolean}
 */
export function isReadyForReview(project, agents = []) {
  if (['completed', 'terminated', 'cancelled'].includes(project?.status)) return false
  if (project?.staging_status === 'staging_complete' && !project?.implementation_launched_at) return false
  if (!agents.length) return false
  const allTerminal = agents.every((a) => TERMINAL_AGENT_STATUSES.has(a?.status))
  if (!allTerminal) return false
  // FE-9548 fix: use the CANONICAL isOrchestrator
  // predicate (checks agent_name OR agent_display_name) instead of a second,
  // narrower "which one is the orchestrator" definition -- an orchestrator
  // identified by agent_name but carrying a different agent_display_name was
  // invisible to the old agent_display_name-only check, which silently
  // stranded such a project in Implementing forever (never reaching Review).
  const orchestrator = agents.find(isOrchestrator)
  return Boolean(orchestrator && TERMINAL_AGENT_STATUSES.has(orchestrator.status))
}

/**
 * The real label ladder, highest to lowest precedence:
 *   1. Needs Input -- any agent blocked/silent
 *   2. Review -- isReadyForReview()
 *   3. Implementing -- implementation_launched_at is set
 *   4. Staged -- staging_status === 'staging_complete'
 *   5. Planning -- staging_status === 'staging'
 *   6. Activated -- everything else (staging_status null/undefined, not launched)
 *
 * FE-9551: this used to end in a STAGED catch-all instead of steps 4-6, which
 * mislabeled an activated-but-never-staged project (staging_status null,
 * implementation_launched_at null) "Staged" when it had never been staged.
 *
 * @param {{ staging_status?: string | null, implementation_launched_at?: string | null }} project
 * @param {Array<{ status?: string }>} [agents] this project's agent executions
 *        (blocked/silent -> Needs Input takes precedence over the lifecycle
 *        phase, mirroring get_workflow_status's own wedged-project framing).
 * @returns {string}
 */
export function jobsSectionLabelFor(project, agents = []) {
  const needsInput = agents.some((a) => a?.status === 'blocked' || a?.status === 'silent')
  if (needsInput) {
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
