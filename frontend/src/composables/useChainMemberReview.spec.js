import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const toast = vi.hoisted(() => vi.fn())
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: toast }) }))
vi.mock('@/services/api', () => ({ default: {}, api: {} }))

import { useChainMemberReview } from './useChainMemberReview'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

const TAB = { projectId: 'p1', name: 'First', status: 'completed' }
let store

beforeEach(() => {
  setActivePinia(createPinia())
  store = useSequenceRunStore()
  vi.clearAllMocks()
})

describe('useChainMemberReview', () => {
  it('opens the review for the chosen member', () => {
    const r = useChainMemberReview({ chainCtx: ref({ runId: 'run-1' }) })
    r.handleTabReview(TAB)
    expect(r.showChainReview.value).toBe(true)
    expect(r.chainReviewTab.value).toEqual(TAB)
  })

  it('on closeout marks the member reviewed locally and durably, and patches nothing', async () => {
    const remote = vi.spyOn(store, 'markReviewedRemote').mockResolvedValue(null)
    const patch = vi.spyOn(store, 'patchRun')
    const r = useChainMemberReview({ chainCtx: ref({ runId: 'run-1' }) })
    r.handleTabReview(TAB)
    r.handleChainReviewComplete()
    expect(store.isReviewed('run-1', 'p1')).toBe(true)
    expect(remote).toHaveBeenCalledWith('run-1', 'p1')
    expect(patch).not.toHaveBeenCalled()
    expect(r.showChainReview.value).toBe(false)
    expect(r.chainReviewTab.value).toBeNull()
  })

  it('a failed durable write toasts and keeps the optimistic mark', async () => {
    vi.spyOn(store, 'markReviewedRemote').mockRejectedValue(new Error('offline'))
    const r = useChainMemberReview({ chainCtx: ref({ runId: 'run-1' }) })
    r.handleTabReview(TAB)
    r.handleChainReviewComplete()
    await Promise.resolve()
    await Promise.resolve()
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
    expect(store.isReviewed('run-1', 'p1')).toBe(true)
  })
})
