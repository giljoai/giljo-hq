import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useTaskCrud } from './useTaskCrud'

const mockUpdateTask = vi.fn(() => Promise.resolve({ id: 1 }))
const mockCreateTask = vi.fn(() => Promise.resolve())
const mockFetchTasks = vi.fn(() => Promise.resolve())
const mockShowToast = vi.fn()
const mockAddNotification = vi.fn()

vi.mock('@/stores/tasks', () => ({
  useTaskStore: () => ({
    updateTask: mockUpdateTask,
    createTask: mockCreateTask,
    fetchTasks: mockFetchTasks,
    tasks: [],
    loading: false,
  }),
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    effectiveProductId: 'product-1',
    currentProductId: 'product-1',
  }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}))

vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({ addNotification: mockAddNotification }),
}))

// A save can fail two ways: with our structured server error shape
// ({error_code, message, context} under response.data), or without one
// (a network error, a legacy 500, anything unstructured). Axios errors are
// real Error instances with a `.response` property attached -- mirror that
// shape rather than a bare object, since that's what the interceptor chain
// (api.js normalizeRejection) actually hands the composable's catch block.
function structuredServerError(message, errorCode = 'RESERVED_TAG_ERROR') {
  return Object.assign(new Error('Request failed with status code 400'), {
    response: {
      status: 400,
      data: { error_code: errorCode, message, context: {} },
    },
  })
}

function unstructuredError() {
  return new Error('Network Error')
}

function stubForm() {
  return { validate: () => Promise.resolve({ valid: true }) }
}

describe('useTaskCrud', () => {
  let crud

  beforeEach(() => {
    vi.clearAllMocks()
    crud = useTaskCrud()
  })

  it('initializes with dialog closed and no editing task', () => {
    expect(crud.showTaskDialog.value).toBe(false)
    expect(crud.editingTask.value).toBeNull()
    expect(crud.saving.value).toBe(false)
  })

  it('initializes currentTask with default values (task_type null per Phase B)', () => {
    expect(crud.currentTask.value.title).toBe('')
    expect(crud.currentTask.value.status).toBe('pending')
    expect(crud.currentTask.value.priority).toBe('medium')
    expect(crud.currentTask.value.task_type).toBeNull()
    expect(crud.currentTask.value.due_date).toBeNull()
  })

  it('editTask sets editingTask and opens dialog', () => {
    const task = {
      id: 1,
      title: 'Test',
      status: 'pending',
      priority: 'high',
      task_type: 'BE',
      due_date: null,
    }
    crud.editTask(task)
    expect(crud.editingTask.value).toEqual(task)
    expect(crud.currentTask.value.title).toBe('Test')
    expect(crud.showTaskDialog.value).toBe(true)
  })

  it('cancelTask resets state and closes dialog', () => {
    crud.editTask({ id: 1, title: 'Test', status: 'pending', priority: 'high', task_type: 'BE' })
    crud.cancelTask()

    expect(crud.showTaskDialog.value).toBe(false)
    expect(crud.showCreateDialog.value).toBe(false)
    expect(crud.editingTask.value).toBeNull()
    expect(crud.currentTask.value.title).toBe('')
    expect(crud.currentTask.value.status).toBe('pending')
  })

  it('handleNewTask opens dialog when product is active', () => {
    crud.handleNewTask()
    expect(crud.showTaskDialog.value).toBe(true)
  })

  it('updateTask delegates to taskStore.updateTask with the given fields', async () => {
    await crud.updateTask(99, { status: 'in_progress' })
    expect(mockUpdateTask).toHaveBeenCalledWith(99, { status: 'in_progress' })
  })

  it('updateTask supports task_type rebind (re-tagging post-migration NULL)', async () => {
    await crud.updateTask(99, { task_type: 'BE' })
    expect(mockUpdateTask).toHaveBeenCalledWith(99, { task_type: 'BE' })
  })

  it('completeTask calls updateTask with completed status', async () => {
    await crud.completeTask(42)
    expect(mockUpdateTask).toHaveBeenCalledWith(42, { status: 'completed' })
  })

  it('completeTask forwards optional completion notes', async () => {
    await crud.completeTask(42, 'shipped to test install')
    expect(mockUpdateTask).toHaveBeenCalledWith(42, {
      status: 'completed',
      completion_notes: 'shipped to test install',
    })
  })

  it('completeTask omits completion_notes when notes are blank', async () => {
    await crud.completeTask(42, '')
    expect(mockUpdateTask).toHaveBeenCalledWith(42, { status: 'completed' })
  })

  it('updateTaskField routes a single field through updateTask (single write path)', async () => {
    const task = { id: 5, title: 'task', status: 'pending' }
    await crud.updateTaskField(task, 'status', 'in_progress')
    expect(mockUpdateTask).toHaveBeenCalledWith(5, { status: 'in_progress' })
  })

  it('updateTaskDueDate formats and routes through updateTask', async () => {
    const task = { id: 7, title: 'task' }
    const localDate = new Date(2025, 5, 15) // June (months are 0-indexed)
    await crud.updateTaskDueDate(task, localDate)
    expect(mockUpdateTask).toHaveBeenCalledWith(7, { due_date: '2025-06-15' })
  })

  it('updateTaskDueDate passes null when no date provided', async () => {
    const task = { id: 8, title: 'task' }
    await crud.updateTaskDueDate(task, null)
    expect(mockUpdateTask).toHaveBeenCalledWith(8, { due_date: null })
  })

  describe('saveTask error surfacing (FE-9461)', () => {
    it('renders the server reason when the save fails with a structured error', async () => {
      const serverMessage = "'TSK' is a reserved tag and cannot be selected."
      mockUpdateTask.mockRejectedValueOnce(structuredServerError(serverMessage))
      crud.editTask({ id: 1, title: 'Test', status: 'pending', priority: 'high' })

      await crud.saveTask(stubForm())

      expect(mockShowToast).toHaveBeenCalledWith({ message: serverMessage, type: 'error' })
    })

    it('falls back to the generic message when the save fails without a structured error', async () => {
      mockUpdateTask.mockRejectedValueOnce(unstructuredError())
      crud.editTask({ id: 1, title: 'Test', status: 'pending', priority: 'high' })

      await crud.saveTask(stubForm())

      expect(mockShowToast).toHaveBeenCalledWith({
        message: 'Failed to save task. Please try again.',
        type: 'error',
      })
    })
  })

  describe('completeTask error surfacing (FE-9466)', () => {
    it('pushes a persistent notification carrying the server reason on a structured failure', async () => {
      const serverMessage = 'Cannot complete a task with unresolved subtasks.'
      mockUpdateTask.mockRejectedValueOnce(
        structuredServerError(serverMessage, 'TASK_HAS_OPEN_SUBTASKS'),
      )

      await expect(crud.completeTask(42)).rejects.toThrow()

      expect(mockAddNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'failure:task.complete:42:TASK_HAS_OPEN_SUBTASKS',
          message: serverMessage,
        }),
      )
    })

    it('falls back to a generic message on an unstructured failure, never the raw error', async () => {
      mockUpdateTask.mockRejectedValueOnce(unstructuredError())

      await expect(crud.completeTask(42)).rejects.toThrow()

      const pushed = mockAddNotification.mock.calls.at(-1)?.[0]
      expect(pushed?.message).toBe('Failed to complete task. Please try again.')
      expect(pushed?.message).not.toMatch(/Network Error/)
    })
  })
})
