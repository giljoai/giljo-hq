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

  it('Needs decision and Needs attention resolve to the blocked status color', () => {
    expect(jobsBoardLifecycleColor('Needs decision')).toBe(getStatusColor('blocked'))
    expect(jobsBoardLifecycleColor('Needs attention')).toBe(getStatusColor('blocked'))
  })

  it('Review resolves to the complete/success status color', () => {
    expect(jobsBoardLifecycleColor(JOBS_SECTION_LABELS.REVIEW)).toBe(getStatusColor('complete'))
  })

  it('Staged resolves to the neutral secondary text color', () => {
    expect(jobsBoardLifecycleColor(JOBS_SECTION_LABELS.STAGED)).toBe(TEXT_SECONDARY)
  })

  it('Planning resolves to the same color statusConfig.js uses for its "planning" status', () => {
    expect(jobsBoardLifecycleColor(JOBS_SECTION_LABELS.PLANNING)).toBe(getStatusColor('planning'))
  })

  it('Activated resolves to the neutral secondary text color', () => {
    expect(jobsBoardLifecycleColor(JOBS_SECTION_LABELS.ACTIVATED)).toBe(TEXT_SECONDARY)
  })

  it('falls back to the Staged color for an unrecognized label', () => {
    expect(jobsBoardLifecycleColor('Something Else')).toBe(TEXT_SECONDARY)
  })
})
