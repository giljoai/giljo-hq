/**
 * Characterization of the project store's mutation actions: on success each
 * returns the server row (and upserts it where the action does), clears
 * `error` and ends with `loading` false; on failure each records the error
 * message, rethrows, and ends with `loading` false.
 *
 * Edition Scope: CE
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { projectsApi } = vi.hoisted(() => ({
  projectsApi: {
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    complete: vi.fn(),
    cancel: vi.fn(),
    restore: vi.fn(),
    restoreCompleted: vi.fn(),
    purgeDeleted: vi.fn(),
    purgeAllDeleted: vi.fn(),
    list: vi.fn(),
    fetchDeleted: vi.fn(),
  },
}))

vi.mock('@/services/api', () => ({
  api: { projects: projectsApi },
  default: { projects: projectsApi },
}))

import { useProjectStore } from '@/stores/projects'

const ROW = { id: 'p-1', name: 'One', status: 'active' }

const UPSERTING = [
  ['updateProject', 'update', (s) => s.updateProject('p-1', { name: 'One' })],
  ['completeProject', 'complete', (s) => s.completeProject('p-1')],
  ['cancelProject', 'cancel', (s) => s.cancelProject('p-1')],
  ['supersedeProject', 'update', (s) => s.supersedeProject('p-1', 'p-2')],
  ['restoreCompletedProject', 'restoreCompleted', (s) => s.restoreCompletedProject('p-1')],
  ['restoreProject', 'restore', (s) => s.restoreProject('p-1')],
]

const ALL = [
  ...UPSERTING,
  ['createProject', 'create', (s) => s.createProject({ name: 'One' })],
  ['deleteProject', 'delete', (s) => s.deleteProject('p-1')],
  ['purgeDeletedProject', 'purgeDeleted', (s) => s.purgeDeletedProject('p-1')],
  ['purgeAllDeletedProjects', 'purgeAllDeleted', (s) => s.purgeAllDeletedProjects()],
]

describe('project store mutations', () => {
  let store
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const fn of Object.values(projectsApi)) fn.mockReset()
    projectsApi.list.mockResolvedValue({ data: [], headers: {} })
    projectsApi.fetchDeleted.mockResolvedValue({ data: [] })
    vi.spyOn(console, 'error').mockImplementation(() => {})
    store = useProjectStore()
  })

  it.each(UPSERTING)('%s returns the server row and upserts it', async (_name, method, act) => {
    projectsApi[method].mockResolvedValue({ data: ROW })
    store.error = 'stale'
    await expect(act(store)).resolves.toEqual(ROW)
    expect(store.projectById('p-1')).toEqual(ROW)
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it.each(ALL)('%s records the error, rethrows and clears loading', async (_name, method, act) => {
    const boom = new Error('server said no')
    projectsApi[method].mockRejectedValue(boom)
    await expect(act(store)).rejects.toBe(boom)
    expect(store.error).toBe('server said no')
    expect(store.loading).toBe(false)
    expect(console.error).toHaveBeenCalledWith(expect.stringMatching(/^Failed to /), boom)
  })

  it('createProject returns the created row and refreshes the list', async () => {
    projectsApi.create.mockResolvedValue({ data: ROW })
    await expect(store.createProject({ name: 'One' })).resolves.toEqual(ROW)
    expect(projectsApi.list).toHaveBeenCalled()
    expect(store.loading).toBe(false)
  })

  it('deleteProject drops the row and refreshes the trash', async () => {
    store.projects = [ROW]
    projectsApi.delete.mockResolvedValue({})
    await store.deleteProject('p-1')
    expect(store.projects).toEqual([])
    expect(projectsApi.fetchDeleted).toHaveBeenCalled()
  })

  it('restoreProject moves the row from the trash to the list', async () => {
    store.deletedProjects = [ROW]
    projectsApi.restore.mockResolvedValue({ data: ROW })
    await store.restoreProject('p-1')
    expect(store.deletedProjects).toEqual([])
    expect(store.projects).toEqual([ROW])
  })

  it('supersedeProject sends the superseded status and successor', async () => {
    projectsApi.update.mockResolvedValue({ data: ROW })
    await store.supersedeProject('p-1', 'p-2')
    expect(projectsApi.update).toHaveBeenCalledWith('p-1', {
      status: 'superseded',
      successor_project_id: 'p-2',
    })
  })

  it('purgeAllDeletedProjects empties the trash', async () => {
    store.deletedProjects = [ROW]
    projectsApi.purgeAllDeleted.mockResolvedValue({})
    await store.purgeAllDeletedProjects()
    expect(store.deletedProjects).toEqual([])
    expect(projectsApi.fetchDeleted).toHaveBeenCalled()
  })
})
