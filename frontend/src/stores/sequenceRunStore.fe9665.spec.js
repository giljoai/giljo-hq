import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSequenceRunStore } from './sequenceRunStore'
import api from '@/services/api'

const addNotificationMock = vi.hoisted(() => vi.fn())
vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({ addNotification: addNotificationMock }),
}))

function run(id, projectIds, status = 'running', extra = {}) {
  return {
    id,
    project_ids: projectIds,
    resolved_order: projectIds,
    current_index: 0,
    status,
    execution_mode: 'multi_terminal',
    project_statuses: projectIds.reduce((acc, p) => ({ ...acc, [p]: 'pending' }), {}),
    ...extra,
  }
}

describe('handleSequenceUpdated — board-level chain-finished notice (FE-9665)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
    addNotificationMock.mockClear()
  })

  it('raises the Chain finished bell when a run the board knew about is genuinely purged', async () => {
    store._testSeedRuns([run('r1', ['p1', 'p2'], 'running')])

    api.sequenceRuns.list.mockResolvedValueOnce({ data: [] })
    api.sequenceRuns.get.mockRejectedValueOnce({ response: { status: 404 } })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(api.sequenceRuns.get).toHaveBeenCalledWith('r1')
    expect(addNotificationMock).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'chain-retired:r1',
        severity: 'info',
        title: 'Chain finished',
      }),
    )
  })

  it('does NOT notify when the run merely drops out of the board filters but still exists server-side', async () => {
    store._testSeedRuns([run('r1', ['p1'], 'running')])

    api.sequenceRuns.list.mockResolvedValueOnce({ data: [] })
    api.sequenceRuns.get.mockResolvedValueOnce({ data: run('r1', ['p1'], 'completed') })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(addNotificationMock).not.toHaveBeenCalled()
  })

  it('does NOT notify or probe the server when the run is still known after hydrate', async () => {
    store._testSeedRuns([run('r1', ['p1'], 'running')])

    api.sequenceRuns.list.mockResolvedValueOnce({ data: [run('r1', ['p1'], 'running')] })

    await store.handleSequenceUpdated({ run_id: 'r1' })

    expect(api.sequenceRuns.get).not.toHaveBeenCalled()
    expect(addNotificationMock).not.toHaveBeenCalled()
  })

  it('does NOT notify for a run the board never knew about (no false positives on unrelated events)', async () => {
    api.sequenceRuns.list.mockResolvedValueOnce({ data: [] })

    await store.handleSequenceUpdated({ run_id: 'never-seen' })

    expect(api.sequenceRuns.get).not.toHaveBeenCalled()
    expect(addNotificationMock).not.toHaveBeenCalled()
  })
})
