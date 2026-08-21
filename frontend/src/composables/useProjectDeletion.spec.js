/**
 * useProjectDeletion.spec.js — FE-9466
 *
 * The five destructive-lifecycle methods here already showed a generic toast
 * on failure and swallowed the server's own reason. They now also push a
 * persistent notification carrying that reason (structured error) or a safe
 * generic message otherwise, via the shared notifyFailure helper.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { ref } from 'vue'
import { useProjectDeletion } from './useProjectDeletion'
import { useNotificationStore } from '@/stores/notifications'

const mockDeleteProject = vi.fn()
const mockCancelProject = vi.fn()
const mockRestoreProject = vi.fn()
const mockPurgeDeletedProject = vi.fn()
const mockPurgeAllDeletedProjects = vi.fn()
const deletedProjects = ref([])

vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    deleteProject: (...a) => mockDeleteProject(...a),
    cancelProject: (...a) => mockCancelProject(...a),
    restoreProject: (...a) => mockRestoreProject(...a),
    purgeDeletedProject: (...a) => mockPurgeDeletedProject(...a),
    purgeAllDeletedProjects: (...a) => mockPurgeAllDeletedProjects(...a),
    get deletedProjects() {
      return deletedProjects.value
    },
  }),
}))

function structuredServerError(message, errorCode = 'PROJECT_STATE_ERROR') {
  return Object.assign(new Error('Request failed with status code 409'), {
    response: { status: 409, data: { error_code: errorCode, message, context: {} } },
  })
}

describe('useProjectDeletion error surfacing (FE-9466)', () => {
  let deletion

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    deletedProjects.value = []
    deletion = useProjectDeletion({
      showDeletedDialog: ref(false),
      reloadProjects: vi.fn(() => Promise.resolve()),
    })
  })

  it('deleteProject pushes a persistent notification with the server reason', async () => {
    const serverMessage = 'Cannot delete a project with an active agent.'
    mockDeleteProject.mockRejectedValueOnce(structuredServerError(serverMessage))
    deletion.projectToDelete.value = { id: 'proj-1' }

    await deletion.deleteProject()

    const store = useNotificationStore()
    expect(store.notifications.some((n) => n.message === serverMessage)).toBe(true)
  })

  it('executeCancelProject pushes a persistent notification with the server reason', async () => {
    const serverMessage = 'Project is already cancelled.'
    mockCancelProject.mockRejectedValueOnce(structuredServerError(serverMessage))
    deletion.projectToCancel.value = { id: 'proj-2' }

    await deletion.executeCancelProject()

    const store = useNotificationStore()
    expect(store.notifications.some((n) => n.message === serverMessage)).toBe(true)
  })

  it('restoreFromDelete pushes a persistent notification with the server reason', async () => {
    const serverMessage = 'Project retention window has expired.'
    mockRestoreProject.mockRejectedValueOnce(structuredServerError(serverMessage))

    await deletion.restoreFromDelete({ id: 'proj-3' })

    const store = useNotificationStore()
    expect(store.notifications.some((n) => n.message === serverMessage)).toBe(true)
  })

  it('purgeDeletedProject pushes a persistent notification with the server reason', async () => {
    const serverMessage = 'Project purge is already in progress.'
    mockPurgeDeletedProject.mockRejectedValueOnce(structuredServerError(serverMessage))

    await deletion.purgeDeletedProject({ id: 'proj-4' })

    const store = useNotificationStore()
    expect(store.notifications.some((n) => n.message === serverMessage)).toBe(true)
  })

  it('executePurgeAll pushes a persistent notification with the server reason', async () => {
    const serverMessage = 'Nothing to purge.'
    mockPurgeAllDeletedProjects.mockRejectedValueOnce(structuredServerError(serverMessage))

    await deletion.executePurgeAll()

    const store = useNotificationStore()
    expect(store.notifications.some((n) => n.message === serverMessage)).toBe(true)
  })

  it('falls back to a generic message on an unstructured failure, never the raw error', async () => {
    mockDeleteProject.mockRejectedValueOnce(new Error('Network Error'))
    deletion.projectToDelete.value = { id: 'proj-5' }

    await deletion.deleteProject()

    const store = useNotificationStore()
    const pushed = store.notifications.find((n) => n.id?.startsWith('failure:project.delete:proj-5'))
    expect(pushed).toBeDefined()
    expect(pushed.message).not.toMatch(/Network Error/)
  })
})
