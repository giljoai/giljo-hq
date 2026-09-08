/**
 * useApprovalBannerState.js — FE-9511
 *
 * Extracted from SystemStatusBanner.vue (to keep that file within the project's file-size budget): the
 * canned-text lookup + project-pill reduction for the approval banner row.
 *
 * Never `approval.reason` -- that is agent-authored prose, demoted to the
 * Review screen (ApprovalCard.vue), and must never reach this banner.
 *
 * Edition Scope: Both
 */
import { computed } from 'vue'

// The closed canned-text set for VALID_APPROVAL_BANNER_STATES
// (giljo_mcp/schemas/user_approval.py). Kept as a plain object (not a Set) so
// tests/unit/test_fe9511_approval_banner_state_checker.py can statically diff
// its KEYS against the backend enum -- an unrendered fifth state must fail
// that checker, not render nowhere (the FE-9501d D17 failure mode).
const APPROVAL_BANNER_STATE_TEXT = {
  waiting_at_staging: 'A project is waiting for you at staging',
  decision_needed: 'An agent is waiting on your decision',
  blocked: 'An agent is blocked and needs you',
  input_needed: 'An agent needs your input',
}

// Pills: the DISTINCT project taxonomy_alias values across pending approvals
// (several approvals can share a project), capped at 4 with a "+N more" tail
// -- one row, never a stack (per the operator-approved multi-approval format).
const APPROVAL_MAX_PILLS = 4

/**
 * @param {import('vue').ComputedRef<Array>} pendingApprovals
 */
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
