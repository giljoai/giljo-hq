import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const updateMock = vi.fn()
vi.mock('@/services/api', () => {
  const api = { threads: { update: (...a) => updateMock(...a), list: vi.fn() } }
  return { default: api, api }
})

import { useCommHubStore } from '@/stores/commHubStore'

describe('commHubStore.setThreadStatus (FE-9746)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useCommHubStore()
    updateMock.mockReset()
    store._testSeedThread({ thread_id: 't1', chat_id: 'CHT-0001', subject: 'S', status: 'open' })
  })

  it('PATCHes only the status and patches the local thread from the response', async () => {
    updateMock.mockResolvedValue({ data: { thread_id: 't1', status: 'resolved' } })
    await store.setThreadStatus('t1', 'resolved')
    expect(updateMock).toHaveBeenCalledWith('t1', { status: 'resolved' })
    expect(store.threadsById.get('t1').status).toBe('resolved')
  })

  it('leaves the thread untouched and rethrows when the server refuses', async () => {
    updateMock.mockRejectedValue(new Error('nope'))
    await expect(store.setThreadStatus('t1', 'resolved')).rejects.toThrow('nope')
    expect(store.threadsById.get('t1').status).toBe('open')
  })
})
