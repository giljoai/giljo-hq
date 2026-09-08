/**
 * jobsBoardLifecycle.spec.js — FE-9548
 *
 * Pure unit tests for the Jobs board's per-state color resolver. Values are
 * asserted against the SAME accessor functions the mock's colors were lifted
 * from (getAgentColor/getStatusColor), not against bare hex literals, so a
 * token change anywhere upstream cannot silently desync this file.
 *
 * Edition scope: Both.
 */
import { describe, it, expect } from 'vitest'
import { jobsBoardLifecycleColor } from './jobsBoardLifecycle'
import { getAgentColor } from '@/config/agentColors'
import { getStatusColor } from '@/utils/statusConfig'
import { TEXT_SECONDARY } from '@/config/colorTokens'
import { JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'

describe('jobsBoardLifecycleColor', () => {
  it('Implementing resolves to the implementer agent color', () => {
    expect(jobsBoardLifecycleColor(JOBS_SECTION_LABELS.IMPLEMENTING)).toBe(getAgentColor('implementer').hex)
  })

  it('Needs Input resolves to the blocked status color', () => {
    expect(jobsBoardLifecycleColor(JOBS_SECTION_LABELS.NEEDS_INPUT)).toBe(getStatusColor('blocked'))
  })

  it('Review resolves to the complete/success status color', () => {
    expect(jobsBoardLifecycleColor(JOBS_SECTION_LABELS.REVIEW)).toBe(getStatusColor('complete'))
  })

  it('Staged resolves to the neutral secondary text color', () => {
    expect(jobsBoardLifecycleColor(JOBS_SECTION_LABELS.STAGED)).toBe(TEXT_SECONDARY)
  })

  // FE-9551: Planning reuses the SAME color statusConfig.js already resolves
  // for its own 'planning' status key, so the board and the agent-row status
  // pill never disagree about what color "Planning" is.
  it('Planning resolves to the same color statusConfig.js uses for its "planning" status', () => {
    expect(jobsBoardLifecycleColor(JOBS_SECTION_LABELS.PLANNING)).toBe(getStatusColor('planning'))
  })

  // FE-9551: Activated is the new neutral floor state (never entered
  // staging) -- reuses the same neutral secondary-text token as Staged
  // rather than inventing a new hex.
  it('Activated resolves to the neutral secondary text color', () => {
    expect(jobsBoardLifecycleColor(JOBS_SECTION_LABELS.ACTIVATED)).toBe(TEXT_SECONDARY)
  })

  it('falls back to the Staged color for an unrecognized label', () => {
    expect(jobsBoardLifecycleColor('Something Else')).toBe(TEXT_SECONDARY)
  })
})
