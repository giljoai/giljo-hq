/**
 * useTaskCrud Composable
 *
 * Encapsulates dialog state and CRUD operations for the task edit/create
 * workflow. Uses the task and product stores internally.
 *
 * Mirrors the project-side update/complete pattern (`useProjectCrud` /
 * `update_project` MCP tool) — `updateTask(id, fields)` is the single
 * write path; status changes flow through the same call (no
 * `updateTaskStatus`, on parity with how projects do it).
 *
 * @returns {{
 *   showTaskDialog, showCreateDialog, editingTask, saving, currentTask,
 *   editTask, cancelTask, saveTask, handleNewTask, completeTask,
 *   updateTask, updateTaskField, updateTaskDueDate
 * }}
 */
import { ref } from 'vue'
import { format } from 'date-fns'
import { useTaskStore } from '@/stores/tasks'
import { useProductStore } from '@/stores/products'
import { useNotificationStore } from '@/stores/notifications'
import { useToast } from '@/composables/useToast'
import { parseErrorResponse } from '@/utils/errorMessages'
import { notifyFailure } from '@/utils/notifyFailure'

const GENERIC_SAVE_FAILURE = 'Failed to save task. Please try again.'
const GENERIC_COMPLETE_FAILURE = 'Failed to complete task. Please try again.'

const DEFAULT_TASK = () => ({
  title: '',
  description: '',
  status: 'pending',
  priority: 'medium',
  task_type: null,
  series_number: null,
  due_date: null,
})

export function useTaskCrud() {
  const taskStore = useTaskStore()
  const productStore = useProductStore()
  const notificationStore = useNotificationStore()
  const { showToast } = useToast()

  const showTaskDialog = ref(false)
  const showCreateDialog = ref(false)
  const editingTask = ref(null)
  const saving = ref(false)
  const currentTask = ref(DEFAULT_TASK())

  function editTask(task) {
    editingTask.value = task
    currentTask.value = { ...task }
    showTaskDialog.value = true
  }

  function cancelTask() {
    showTaskDialog.value = false
    showCreateDialog.value = false
    editingTask.value = null
    currentTask.value = DEFAULT_TASK()
  }

  function handleNewTask() {
    if (!productStore.effectiveProductId) {
      return { noProduct: true }
    }
    editingTask.value = null
    currentTask.value = DEFAULT_TASK()
    showTaskDialog.value = true
    return { noProduct: false }
  }

  /**
   * Update an arbitrary set of fields on a task. Mirrors the MCP
   * `update_task` tool surface — status flows through this call, there
   * is no separate `updateTaskStatus` (parity with how
   * `update_project` handles project status).
   *
   * @param {string} taskId
   * @param {object} fields - e.g. `{ status: 'in_progress' }` or
   *        `{ task_type: 'BE' }`. The store dispatches a PUT to
   *        `/api/v1/tasks/{id}/`.
   * @returns {Promise<object>} the updated task
   */
  async function updateTask(taskId, fields) {
    return await taskStore.updateTask(taskId, fields)
  }

  /**
   * Mark a task complete. Optional `notes` are accepted for parity
   * with the MCP `complete_task` tool, but the REST `TaskUpdate` schema
   * does not (yet) carry a completion-notes field — the param is
   * forwarded so that when the schema gains the field, no caller signature
   * needs to change. Until then it is a no-op on the wire.
   *
   * @param {string} taskId
   * @param {string} [notes]
   */
  async function completeTask(taskId, notes) {
    try {
      const fields = { status: 'completed' }
      if (notes != null && notes !== '') {
        fields.completion_notes = notes
      }
      return await taskStore.updateTask(taskId, fields)
    } catch (error) {
      console.error('Failed to complete task:', error)
      showToast({ message: GENERIC_COMPLETE_FAILURE, type: 'error' })
      // FE-9466: also drop a persistent notification carrying the server's
      // own reason, so it survives past the toast. TasksView's row-level
      // wrapper catches this same rethrown error too -- both compute the
      // same deterministic id, so the store's dedup-by-id collapses the
      // two pushes into one bell row.
      notifyFailure(notificationStore, {
        operation: 'task.complete',
        entityId: taskId,
        error,
        fallbackMessage: GENERIC_COMPLETE_FAILURE,
        title: 'Task not completed',
      })
      throw error
    }
  }

  /**
   * Convenience helper used by inline-edit dropdowns (status / priority /
   * task_type cells). Routes through `updateTask` so there's a single
   * write path.
   */
  async function updateTaskField(task, field, value) {
    try {
      await updateTask(task.id, { [field]: value })
    } catch (error) {
      console.error(`Failed to update task ${field}:`, error)
      throw error
    }
  }

  async function updateTaskDueDate(task, newDate) {
    try {
      const formattedDate = newDate ? format(new Date(newDate), 'yyyy-MM-dd') : null
      await updateTask(task.id, { due_date: formattedDate })
    } catch (error) {
      console.error('Failed to update due date:', error)
      throw error
    }
  }

  /**
   * Save the current task (create or update).
   *
   * @param {import('vue').Ref|object} taskForm - The dialog's <v-form>. It can
   *   arrive as a Vue ref (`.value` = the form instance) OR as the form instance
   *   directly: the save button emits it from a template inline handler
   *   (`@click="$emit('save', taskFormRef)"`), and templates AUTO-UNWRAP refs, so
   *   the parent actually receives the unwrapped v-form instance. The previous
   *   code assumed a ref and called `taskForm.value.validate()`, which on the
   *   real (instance) shape made `.value` undefined → `undefined.validate()`
   *   threw → the create silently no-op'd (no POST, no toast). Reproduced in a
   *   real browser on test.giljo.ai. Normalize so validate() is always reached.
   * @param {Function} afterSave - Optional callback run after successful save (e.g. fetchTasks)
   */
  async function saveTask(taskForm, afterSave) {
    // Accept both shapes: a ref (`.value` holds the instance) or the instance.
    const form = typeof taskForm?.validate === 'function' ? taskForm : taskForm?.value
    if (!form || typeof form.validate !== 'function') {
      console.error('[useTaskCrud] saveTask: no usable form ref to validate', taskForm)
      showToast({ message: 'Could not validate the form. Please try again.', type: 'error' })
      return
    }

    const { valid } = await form.validate()
    if (!valid) return

    saving.value = true
    try {
      if (editingTask.value) {
        const { parent_task_id: _parent, ...taskData } = currentTask.value
        await taskStore.updateTask(editingTask.value.id, taskData)
      } else {
        const productId = productStore.effectiveProductId
        if (productId) {
          currentTask.value.product_id = productId
        }
        const { parent_task_id: _parent, ...taskData } = currentTask.value
        await taskStore.createTask(taskData)
      }
      cancelTask()
      if (afterSave) {
        await afterSave()
      }
    } catch (error) {
      console.error('Failed to save task:', error)
      // FE-9461: show the server's own reason when it gave us one in our
      // structured error shape (it is written to be read by a human) --
      // fall back to the generic text for anything unstructured, so we
      // never render a raw exception string or stack trace to the user.
      const parsed = parseErrorResponse(error)
      const message = parsed.isStructured ? parsed.message : GENERIC_SAVE_FAILURE
      showToast({ message, type: 'error' })
    } finally {
      saving.value = false
    }
  }

  return {
    showTaskDialog,
    showCreateDialog,
    editingTask,
    saving,
    currentTask,
    editTask,
    cancelTask,
    saveTask,
    handleNewTask,
    completeTask,
    updateTask,
    updateTaskField,
    updateTaskDueDate,
  }
}
