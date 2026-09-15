import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSequenceRunStore } from './sequenceRunStore'
import api from '@/services/api'

describe('sequenceRunStore — BE-9098 durable review persistence', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
  })

  it('REFRESH SIMULATION: a fresh store hydrates isReviewed from reviewed_project_ids with NO local mark', () => {
    expect(store.isReviewed('run-1', 'p1')).toBe(false)

    store.setActiveRun({
      id: 'run-1',
      project_ids: ['p1', 'p2'],
      resolved_order: ['p1', 'p2'],
      project_statuses: { p1: 'completed', p2: 'completed' },
      reviewed_project_ids: ['p1'],
    })

    expect(store.isReviewed('run-1', 'p1')).toBe(true)
    expect(store.isReviewed('run-1', 'p2')).toBe(false)
  })

  it('fetchRun hydrates the review Map from the server payload (end-to-end path)', async () => {
    api.sequenceRuns.get.mockResolvedValueOnce({
      data: {
        id: 'run-9',
        project_ids: ['pA', 'pB'],
        resolved_order: ['pA', 'pB'],
        project_statuses: { pA: 'completed', pB: 'completed' },
        reviewed_project_ids: ['pB'],
      },
    })

    await store.fetchRun('run-9')

    expect(store.isReviewed('run-9', 'pB')).toBe(true)
    expect(store.isReviewed('run-9', 'pA')).toBe(false)
  })

  it('hydrate() seeds review acks for every run in the active list', async () => {
    api.sequenceRuns.list.mockResolvedValueOnce({
      data: [
        {
          id: 'run-1',
          project_ids: ['p1'],
          resolved_order: ['p1'],
          status: 'running',
          project_statuses: { p1: 'completed' },
          reviewed_project_ids: ['p1'],
        },
      ],
    })

    await store.hydrate()

    expect(store.isReviewed('run-1', 'p1')).toBe(true)
  })

  it('server hydrate UNIONS with an optimistic local mark (never clobbers in-flight state)', () => {
    store.markReviewed('run-1', 'p2')
    expect(store.isReviewed('run-1', 'p2')).toBe(true)

    store.setActiveRun({
      id: 'run-1',
      project_ids: ['p1', 'p2'],
      resolved_order: ['p1', 'p2'],
      reviewed_project_ids: ['p1'],
    })

    expect(store.isReviewed('run-1', 'p1')).toBe(true)
    expect(store.isReviewed('run-1', 'p2')).toBe(true)
  })

  it('markReviewedRemote POSTs and merges the authoritative server array', async () => {
    api.sequenceRuns.markReviewed.mockResolvedValueOnce({
      data: { id: 'run-1', project_ids: ['p1'], resolved_order: ['p1'], reviewed_project_ids: ['p1'] },
    })

    await store.markReviewedRemote('run-1', 'p1')

    expect(api.sequenceRuns.markReviewed).toHaveBeenCalledWith('run-1', 'p1')
    expect(store.isReviewed('run-1', 'p1')).toBe(true)
  })

  it('markReviewedRemote rejects on API failure so the caller can toast', async () => {
    api.sequenceRuns.markReviewed.mockRejectedValueOnce(new Error('network down'))

    await expect(store.markReviewedRemote('run-1', 'p1')).rejects.toThrow('network down')
  })

  it('$reset clears server-hydrated acks too', () => {
    store.setActiveRun({ id: 'run-1', project_ids: ['p1'], reviewed_project_ids: ['p1'] })
    expect(store.isReviewed('run-1', 'p1')).toBe(true)

    store.$reset()

    expect(store.isReviewed('run-1', 'p1')).toBe(false)
  })
})
