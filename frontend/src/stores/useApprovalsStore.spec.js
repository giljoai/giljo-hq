import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useApprovalsStore } from './useApprovalsStore'

describe('useApprovalsStore — $reset (TSK-9372)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useApprovalsStore()
  })

  it('$reset restores approvalsById, loading, and error to initial values', () => {
    store.upsertApproval({ id: 'appr-1', job_id: 'job-1', question: 'Merge the branch?' })
    store.upsertApproval({ id: 'appr-2', job_id: 'job-2', question: 'Close the project?' })
    store.loading = true
    store.error = 'previous session failure'
    expect(store.pendingApprovals).toHaveLength(2)

    store.$reset()

    expect(store.approvalsById.size).toBe(0)
    expect(store.pendingApprovals).toHaveLength(0)
    expect(store.findByJobId('job-1')).toBeNull()
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })
})
