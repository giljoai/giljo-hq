import { computed } from 'vue'

const APPROVAL_BANNER_STATE_TEXT = {
  waiting_at_staging: 'A project is waiting for you at staging',
  decision_needed: 'An agent is waiting on your decision',
  blocked: 'An agent is blocked and needs you',
  input_needed: 'An agent needs your input',
}

const APPROVAL_MAX_PILLS = 4

export function useApprovalBannerState(pendingApprovals) {
  const approvalMessage = computed(() => {
    const approvals = pendingApprovals.value
    if (approvals.length > 1) {
      return `${approvals.length} agents need your decision`
    }
    const state = approvals[0]?.banner_state
    return APPROVAL_BANNER_STATE_TEXT[state] || APPROVAL_BANNER_STATE_TEXT.decision_needed
  })

  const approvalPillAliases = computed(() => {
    const seen = new Set()
    const aliases = []
    for (const approval of pendingApprovals.value) {
      const alias = approval?.taxonomy_alias
      if (alias && !seen.has(alias)) {
        seen.add(alias)
        aliases.push(alias)
      }
    }
    return aliases
  })

  const visibleApprovalPills = computed(() => approvalPillAliases.value.slice(0, APPROVAL_MAX_PILLS))
  const approvalPillOverflowCount = computed(() => Math.max(0, approvalPillAliases.value.length - APPROVAL_MAX_PILLS))

  return { approvalMessage, visibleApprovalPills, approvalPillOverflowCount }
}
