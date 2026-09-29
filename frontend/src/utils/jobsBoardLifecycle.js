import { getAgentColor } from '@/config/agentColors'
import { getStatusColor } from '@/utils/statusConfig'
import { TEXT_SECONDARY, COLOR_DECISION, COLOR_UNREAD } from '@/config/colorTokens'
import { JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'

export function jobsBoardLifecycleColor(sectionLabel) {
  switch (sectionLabel) {
    case JOBS_SECTION_LABELS.IMPLEMENTING:
      return getAgentColor('implementer').hex
    case JOBS_SECTION_LABELS.NEEDS_INPUT:
      return getStatusColor('blocked')
    case JOBS_SECTION_LABELS.REVIEW:
    case JOBS_SECTION_LABELS.COMPLETE:
      return getStatusColor('complete')
    case JOBS_SECTION_LABELS.PLANNING:
      return getStatusColor('planning')
    case JOBS_SECTION_LABELS.ACTIVATED:
    case JOBS_SECTION_LABELS.STAGED:
    default:
      return TEXT_SECONDARY
  }
}

export function needsInputColor(kind) {
  switch (kind) {
    case 'decision':
      return COLOR_DECISION
    case 'unread':
      return COLOR_UNREAD
    case 'silent':
      return getStatusColor('silent')
    case 'blocked':
    default:
      return getStatusColor('blocked')
  }
}
