/**
 * jobsBoardLifecycle.js — FE-9548
 *
 * Pure (Vue-free) helper resolving the Jobs board card's per-state color: the
 * left lifecycle edge, and the status pill's tint. Colors are NOT invented --
 * each one reuses an existing token accessor (getAgentColor for the
 * implementer blue, getStatusColor for the blocked-orange/complete-green
 * agent-status vocabulary, colorTokens.js's TEXT_SECONDARY for the neutral
 * Staged/Activated states) so the board never drifts from the colors those
 * functions already return elsewhere in the product.
 *
 * FE-9551: Planning reuses getStatusColor('planning') -- the same key
 * statusConfig.js already resolves for a chain member actively being staged
 * -- rather than a new hex. Activated reuses the same neutral TEXT_SECONDARY
 * token as Staged: both are quiet, non-alarming states with nothing for the
 * operator to act on yet.
 *
 * Edition scope: Both.
 */
import { getAgentColor } from '@/config/agentColors'
import { getStatusColor } from '@/utils/statusConfig'
import { TEXT_SECONDARY } from '@/config/colorTokens'
import { JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'

/**
 * @param {string} sectionLabel one of JOBS_SECTION_LABELS
 * @returns {string} hex color for the card's left edge + status pill
 */
export function jobsBoardLifecycleColor(sectionLabel) {
  switch (sectionLabel) {
    case JOBS_SECTION_LABELS.IMPLEMENTING:
      return getAgentColor('implementer').hex
    case JOBS_SECTION_LABELS.NEEDS_INPUT:
      return getStatusColor('blocked')
    case JOBS_SECTION_LABELS.REVIEW:
      return getStatusColor('complete')
    case JOBS_SECTION_LABELS.PLANNING:
      return getStatusColor('planning')
    case JOBS_SECTION_LABELS.ACTIVATED:
    case JOBS_SECTION_LABELS.STAGED:
    default:
      return TEXT_SECONDARY
  }
}
