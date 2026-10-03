import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSequenceRunStore } from './sequenceRunStore'
import api from '@/services/api'

const addNotificationMock = vi.hoisted(() => vi.fn())
vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({ addNotification: addNotificationMock }),
}))

const run = (id) => ({
  id,
  project_ids: ['p1'],
  resolved_order: ['p1'],
  current_index: 0,
  status: 'running',
  execution_mode: 'multi_terminal',
  project_statuses: { p1: 'pending' },
})

describe('handleSequenceUpdated: a failed existence check is not a retirement', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
    addNotificationMock.mockClear()
  })

  it('a 500 on the existence check is shown as a failure, never as "Chain finished"', async () => {
    store._testSeedRuns([run('r1')])
    api.sequenceRuns.list.mockResolvedValueOnce({ data: [] })
    api.sequenceRuns.get.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 500, data: { message: 'chain service is busy' } },
    })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(addNotificationMock).not.toHaveBeenCalledWith(expect.objectContaining({ title: 'Chain finished' }))
    expect(addNotificationMock).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: 'warning',
        message: expect.stringContaining('chain service is busy'),
      }),
    )
  })
})
