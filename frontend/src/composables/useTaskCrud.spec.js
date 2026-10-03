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
  })

  it('editTask sets editingTask and opens dialog', () => {
    const task = {
      id: 1,
      title: 'Test',
      status: 'pending',
      priority: 'high',
      task_type: 'BE',
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

  describe('openHandoverDialog', () => {
    it('opens the dialog with task_type HND and an empty description', () => {
      const result = crud.openHandoverDialog()
      expect(result).toEqual({ noProduct: false })
      expect(crud.showTaskDialog.value).toBe(true)
      expect(crud.editingTask.value).toBeNull()
      expect(crud.currentTask.value.task_type).toBe('HND')
      expect(crud.currentTask.value.description).toBe('')
      expect(crud.currentTask.value.title).toBe('')
    })
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

    it('exposes the verbatim structured message on saveError for the dialog to render', async () => {
      const serverMessage =
        "A handover task (task_type='HND') must carry these headings in its description, and is missing '## Cannot testify'."
      mockUpdateTask.mockRejectedValueOnce(structuredServerError(serverMessage, 'VALIDATION_ERROR'))
      crud.editTask({ id: 1, title: 'Test', status: 'pending', priority: 'high', task_type: 'HND' })

      await crud.saveTask(stubForm())

      expect(crud.saveError.value).toBe(serverMessage)
    })

    it('does not set saveError for an unstructured failure (the generic toast already covers it)', async () => {
      mockUpdateTask.mockRejectedValueOnce(unstructuredError())
      crud.editTask({ id: 1, title: 'Test', status: 'pending', priority: 'high' })

      await crud.saveTask(stubForm())

      expect(crud.saveError.value).toBe('')
    })

    it('clears a stale saveError at the start of the next save attempt', async () => {
      mockUpdateTask.mockRejectedValueOnce(structuredServerError('first failure', 'VALIDATION_ERROR'))
      crud.editTask({ id: 1, title: 'Test', status: 'pending', priority: 'high' })
      await crud.saveTask(stubForm())
      expect(crud.saveError.value).toBe('first failure')

      mockUpdateTask.mockResolvedValueOnce({ id: 1 })
      await crud.saveTask(stubForm())
      expect(crud.saveError.value).toBe('')
    })

    it('clears saveError on cancelTask', async () => {
      mockUpdateTask.mockRejectedValueOnce(structuredServerError('failure', 'VALIDATION_ERROR'))
      crud.editTask({ id: 1, title: 'Test', status: 'pending', priority: 'high' })
      await crud.saveTask(stubForm())
      expect(crud.saveError.value).toBe('failure')

      crud.cancelTask()
      expect(crud.saveError.value).toBe('')
    })
  })

  describe('saveTask sends a diff-only payload in edit mode (FE-9656)', () => {
    const loadedTask = {
      id: 1,
      title: 'Original title',
      description: 'Original description',
      status: 'pending',
      priority: 'medium',
      task_type: 'TSK',
      product_id: 'product-1',
      series_number: 12,
      estimated_effort: 5,
      hidden: true,
    }

    it('sends only the one field the user changed, plus nothing else', async () => {
      crud.editTask(loadedTask)
      crud.currentTask.value = { ...crud.currentTask.value, status: 'in_progress' }

      await crud.saveTask(stubForm())

      expect(mockUpdateTask).toHaveBeenCalledWith(1, { status: 'in_progress' })
    })

    it('sends only the description when editing an HND handover description', async () => {
      const hnd = { ...loadedTask, task_type: 'HND', description: 'old body' }
      crud.editTask(hnd)
      crud.currentTask.value = { ...crud.currentTask.value, description: 'new body' }

      await crud.saveTask(stubForm())

      expect(mockUpdateTask).toHaveBeenCalledWith(1, { description: 'new body' })
    })

    it('sends multiple changed keys together when several fields are edited', async () => {
      crud.editTask(loadedTask)
      crud.currentTask.value = {
        ...crud.currentTask.value,
        title: 'New title',
        priority: 'high',
      }

      await crud.saveTask(stubForm())

      expect(mockUpdateTask).toHaveBeenCalledWith(1, { title: 'New title', priority: 'high' })
    })

    it('treats a clear-to-empty-string as a real change, not "unset"', async () => {
      crud.editTask(loadedTask)
      crud.currentTask.value = { ...crud.currentTask.value, title: '' }

      await crud.saveTask(stubForm())

      expect(mockUpdateTask).toHaveBeenCalledWith(1, { title: '' })
    })

    it('treats a change to 0 as a real change, not "unset"', async () => {
      crud.editTask(loadedTask)
      crud.currentTask.value = { ...crud.currentTask.value, estimated_effort: 0 }

      await crud.saveTask(stubForm())

      expect(mockUpdateTask).toHaveBeenCalledWith(1, { estimated_effort: 0 })
    })

    it('treats a change to false as a real change, not "unset"', async () => {
      crud.editTask(loadedTask)
      crud.currentTask.value = { ...crud.currentTask.value, hidden: false }

      await crud.saveTask(stubForm())

      expect(mockUpdateTask).toHaveBeenCalledWith(1, { hidden: false })
    })

    it('does not echo untouched fields (task_type, product_id, series_number) back', async () => {
      crud.editTask(loadedTask)
      crud.currentTask.value = { ...crud.currentTask.value, priority: 'low' }

      await crud.saveTask(stubForm())

      const sentFields = mockUpdateTask.mock.calls.at(-1)[1]
      expect(sentFields).not.toHaveProperty('task_type')
      expect(sentFields).not.toHaveProperty('product_id')
      expect(sentFields).not.toHaveProperty('series_number')
    })

    it('diffs against the snapshot of the task actually open, not a previously edited one', async () => {
      const taskB = {
        id: 2,
        title: 'Task B original',
        description: 'Task B description',
        status: 'pending',
        priority: 'low',
        task_type: 'TSK',
      }

      crud.editTask(loadedTask)
      crud.cancelTask()
      crud.editTask(taskB)
      crud.currentTask.value = { ...crud.currentTask.value, priority: 'high' }

      await crud.saveTask(stubForm())

      expect(mockUpdateTask).toHaveBeenCalledWith(2, { priority: 'high' })
    })

    it('sends an empty patch (still calls updateTask) when nothing was changed', async () => {
      crud.editTask(loadedTask)

      await crud.saveTask(stubForm())

      expect(mockUpdateTask).toHaveBeenCalledWith(1, {})
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
