import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { ref } from 'vue'
import { useProjectDeletion } from './useProjectDeletion'
import { useNotificationStore } from '@/stores/notifications'

const store = vi.hoisted(() => ({
  deleteProject: vi.fn(),
  cancelProject: vi.fn(),
  restoreProject: vi.fn(),
  purgeDeletedProject: vi.fn(),
  purgeAllDeletedProjects: vi.fn(),
  deletedProjects: [],
}))
vi.mock('@/stores/projects', () => ({ useProjectStore: () => store }))
const toast = vi.hoisted(() => vi.fn())
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: toast }) }))

const CASES = [
  {
    action: 'deleteProject', fail: 'deleteProject', run: (d) => { d.projectToDelete.value = { id: 'p1' }; return d.deleteProject() },
    log: 'Failed to delete project:', toast: 'Failed to delete project. Please try again.', id: 'failure:project.delete:p1', title: 'Project not deleted',
  },
  {
    action: 'executeCancelProject', fail: 'cancelProject', run: (d) => { d.projectToCancel.value = { id: 'p2' }; return d.executeCancelProject() },
    log: 'Failed to cancel project:', toast: 'Failed to cancel project. Please try again.', id: 'failure:project.cancel:p2', title: 'Project not cancelled',
  },
  {
    action: 'restoreFromDelete', fail: 'restoreProject', run: (d) => d.restoreFromDelete({ id: 'p3' }),
    log: 'Failed to restore project:', toast: 'Failed to restore project. Please try again.', id: 'failure:project.restore:p3', title: 'Project not restored',
  },
  {
    action: 'purgeDeletedProject', fail: 'purgeDeletedProject', run: (d) => d.purgeDeletedProject({ id: 'p4' }),
    log: 'Failed to purge deleted project:', toast: 'Failed to permanently delete the project. Please try again.', id: 'failure:project.purgeOne:p4', title: 'Project not purged',
  },
  {
    action: 'executePurgeAll', fail: 'purgeAllDeletedProjects', run: (d) => d.executePurgeAll(),
    log: 'Failed to purge all deleted projects:', toast: 'Failed to purge deleted projects. Please try again.', id: 'failure:project.purgeAll', title: 'Projects not purged',
  },
]

describe('useProjectDeletion failure reporting', () => {
  let deletion
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    deletion = useProjectDeletion({ showDeletedDialog: ref(false), reloadProjects: vi.fn() })
  })

  it.each(CASES)('$action logs, toasts and leaves a notice', async (c) => {
    const err = new Error('Network Error')
    store[c.fail].mockRejectedValueOnce(err)
    await c.run(deletion)
    expect(console.error).toHaveBeenCalledWith(c.log, err)
    expect(toast.mock.calls).toEqual([[{ message: c.toast, type: 'error' }]])
    const notices = useNotificationStore().notifications.filter((n) => n.id?.startsWith(c.id))
    expect(notices.map((n) => [n.title, n.message])).toEqual([[c.title, c.toast]])
  })
})
