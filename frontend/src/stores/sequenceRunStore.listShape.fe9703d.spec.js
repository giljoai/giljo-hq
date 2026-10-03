import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSequenceRunStore } from './sequenceRunStore'
import api from '@/services/api'

describe('sequenceRunStore.hydrate reply shape', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('records an error on a wrapped reply instead of reading it as no runs', async () => {
    api.sequenceRuns.list.mockResolvedValueOnce({ data: { sequence_runs: [] } })
    const store = useSequenceRunStore()
    await store.hydrate()
    expect(store.error).toBeTruthy()
  })
})
