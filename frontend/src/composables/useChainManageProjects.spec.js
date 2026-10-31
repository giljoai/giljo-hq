import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  removeMember: vi.fn(),
  updateProject: vi.fn(),
  hydrate: vi.fn(),
}))

vi.mock('@/stores/sequenceRunStore', () => ({
  useSequenceRunStore: () => ({ removeMember: h.removeMember, hydrate: h.hydrate }),
}))
vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({ updateProject: h.updateProject }),
}))

import { useChainManageProjects } from './useChainManageProjects'

const tab = (projectId, order, status, extra = {}) => ({
  projectId,
  order,
  name: `Project ${projectId}`,
  taxonomyAlias: `BE-${order}`,
  status,
  isCurrent: false,
  isCompleted: status === 'completed',
  isDetached: status === 'detached',
  ...extra,
})

function setup({ started = false, locked = false } = {}) {
  const chainCtx = ref({
    runId: 'run-1',
    locked,
    tabs: [
      tab('a', 0, 'completed'),
      tab('b', 1, 'implementing', { isCurrent: true }),
      tab('c', 2, 'pending'),
      tab('d', 3, 'detached'),
    ],
  })
  return useChainManageProjects({ chainCtx, started: () => started })
}

describe('useChainManageProjects', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    h.removeMember.mockResolvedValue({})
    h.updateProject.mockResolvedValue({})
    h.hydrate.mockResolvedValue()
  })

  it('lists rows in chain order with the right drop state', () => {
    const { manageRows: rows } = setup()
    expect(rows.value.map((r) => [r.projectId, r.kind])).toEqual([
      ['a', 'finished'],
      ['b', 'droppable'],
      ['c', 'droppable'],
      ['d', 'dropped'],
    ])
  })

  it('before the run starts, a drop unlinks the member and asks for no confirm', async () => {
    const m = setup({ started: false })
    m.requestDrop('b')
    await flushPromises()
    expect(h.removeMember).toHaveBeenCalledWith('run-1', 'b')
    expect(h.updateProject).not.toHaveBeenCalled()
    expect(m.managePendingId.value).toBe('')
  })

  it('after the run starts, a non-current member is parked straight away', async () => {
    const m = setup({ started: true })
    m.requestDrop('c')
    await flushPromises()
    expect(h.updateProject).toHaveBeenCalledWith('c', { status: 'parked' })
    expect(h.removeMember).not.toHaveBeenCalled()
    expect(h.hydrate).toHaveBeenCalled()
  })

  it('after the run starts, the current member needs a confirm first', async () => {
    const m = setup({ started: true })
    m.requestDrop('b')
    await flushPromises()
    expect(m.managePendingId.value).toBe('b')
    expect(h.updateProject).not.toHaveBeenCalled()
    await m.confirmDrop()
    expect(h.updateProject).toHaveBeenCalledWith('b', { status: 'parked' })
    expect(m.managePendingId.value).toBe('')
  })

  it('cancelling the confirm drops nothing', async () => {
    const m = setup({ started: true })
    m.requestDrop('b')
    m.cancelDrop()
    expect(m.managePendingId.value).toBe('')
    expect(h.updateProject).not.toHaveBeenCalled()
  })

  it('a finished or dropped row cannot be dropped', async () => {
    const m = setup({ started: true })
    m.requestDrop('a')
    m.requestDrop('d')
    await flushPromises()
    expect(h.updateProject).not.toHaveBeenCalled()
    expect(h.removeMember).not.toHaveBeenCalled()
  })

  it('shows the server message on failure and keeps the dialog state', async () => {
    h.removeMember.mockRejectedValue({ response: { data: { message: 'Chain is running' } } })
    const m = setup({ started: false })
    m.openManageProjects()
    m.requestDrop('c')
    await flushPromises()
    expect(m.manageError.value).toBe('Chain is running')
    expect(m.showManageProjects.value).toBe(true)
    expect(m.manageDroppingId.value).toBe('')
  })

  it('staged and not started: no row is droppable and requestDrop does nothing', async () => {
    const m = setup({ started: false, locked: true })
    expect(m.managePhase.value).toBe('staged')
    expect(m.manageRows.value.map((r) => r.kind)).toEqual(['finished', 'staged', 'staged', 'dropped'])
    m.requestDrop('c')
    await flushPromises()
    expect(h.removeMember).not.toHaveBeenCalled()
  })

  it('reports the editing and started phases', () => {
    expect(setup({ started: false, locked: false }).managePhase.value).toBe('editing')
    expect(setup({ started: true, locked: true }).managePhase.value).toBe('started')
  })

  it('a 422 on unlink shows our own sentence', async () => {
    h.removeMember.mockRejectedValue({ response: { status: 422, data: { message: 'Terminate or Release' } } })
    const m = setup({ started: false })
    m.requestDrop('c')
    await flushPromises()
    expect(m.manageError.value).toBe('This chain has started. Close this window and try again.')
  })
})
