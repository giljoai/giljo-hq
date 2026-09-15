import { describe, it, expect } from 'vitest'
import { buildChainAwareProjectDoneStatus } from './reviewDispatch.js'

const chainCtx = { run: {}, tabs: [] }

describe('buildChainAwareProjectDoneStatus (banner green-flip)', () => {
  it('chain + completed + reviewed (!needsReview) → "completed" (green chip)', () => {
    const tab = { isCompleted: true, needsReview: false }
    expect(buildChainAwareProjectDoneStatus(chainCtx, tab, null)).toBe('completed')
  })

  it('chain + completed + still needs review → null (suppress green chip)', () => {
    const tab = { isCompleted: true, needsReview: true }
    expect(buildChainAwareProjectDoneStatus(chainCtx, tab, null)).toBeNull()
  })

  it('chain + not yet completed → null', () => {
    const tab = { isCompleted: false, needsReview: false }
    expect(buildChainAwareProjectDoneStatus(chainCtx, tab, 'completed')).toBeNull()
  })

  it('chain + currentChainTab null (no matching tab) → null', () => {
    expect(buildChainAwareProjectDoneStatus(chainCtx, null, 'completed')).toBeNull()
  })

  it('solo (chainCtx null) → passes projectDoneStatus through unchanged ("completed")', () => {
    expect(buildChainAwareProjectDoneStatus(null, null, 'completed')).toBe('completed')
  })

  it('solo (chainCtx null) → passes null projectDoneStatus through (renders nothing)', () => {
    expect(buildChainAwareProjectDoneStatus(null, null, null)).toBeNull()
  })

  it('solo (chainCtx null) → passes "terminated" through unchanged', () => {
    expect(buildChainAwareProjectDoneStatus(null, null, 'terminated')).toBe('terminated')
  })

  it('chain present → suppresses projectDoneStatus regardless of its value', () => {
    const tab = { isCompleted: false, needsReview: false }
    expect(buildChainAwareProjectDoneStatus(chainCtx, tab, 'terminated')).toBeNull()
  })
})
