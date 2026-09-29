import { ref } from 'vue'
import { useTaskStore } from '@/stores/tasks'
import { useProductStore } from '@/stores/products'
import { useNotificationStore } from '@/stores/notifications'
import { useToast } from '@/composables/useToast'
import { parseErrorResponse } from '@/utils/errorMessages'
import { notifyFailure } from '@/utils/notifyFailure'
import { RESERVED_HANDOVER_TYPE_ABBR } from '@/utils/constants'

const GENERIC_SAVE_FAILURE = 'Failed to save task. Please try again.'
const GENERIC_COMPLETE_FAILURE = 'Failed to complete task. Please try again.'

const DEFAULT_TASK = () => ({
  title: '',
  description: '',
  status: 'pending',
  priority: 'medium',
  task_type: null,
  series_number: null,
})

function diffChangedFields(snapshot, edited) {
  if (!snapshot) return { ...edited }
  const changed = {}
  for (const key of Object.keys(edited)) {
    if (edited[key] !== snapshot[key]) {
      changed[key] = edited[key]
    }
  }
  return changed
}

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
  const editSnapshot = ref(null)
  const saveError = ref('')

  function editTask(task) {
    editingTask.value = task
    currentTask.value = { ...task }
    editSnapshot.value = { ...task }
    showTaskDialog.value = true
  }

  function cancelTask() {
    showTaskDialog.value = false
    showCreateDialog.value = false
    editingTask.value = null
    currentTask.value = DEFAULT_TASK()
    editSnapshot.value = null
    saveError.value = ''
  }

  function handleNewTask() {
    if (!productStore.effectiveProductId) {
      return { noProduct: true }
    }
    editingTask.value = null
    currentTask.value = DEFAULT_TASK()
    editSnapshot.value = null
    showTaskDialog.value = true
    return { noProduct: false }
  }

  function openHandoverDialog(templateText) {
    if (!productStore.effectiveProductId) {
      return { noProduct: true }
    }
    editingTask.value = null
    currentTask.value = {
      ...DEFAULT_TASK(),
      task_type: RESERVED_HANDOVER_TYPE_ABBR,
      description: templateText,
    }
    editSnapshot.value = null
    showTaskDialog.value = true
    return { noProduct: false }
  }

  async function updateTask(taskId, fields) {
    return await taskStore.updateTask(taskId, fields)
  }

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

  async function updateTaskField(task, field, value) {
    try {
      await updateTask(task.id, { [field]: value })
    } catch (error) {
      console.error(`Failed to update task ${field}:`, error)
      throw error
    }
  }

  async function saveTask(taskForm, afterSave) {
    const form = typeof taskForm?.validate === 'function' ? taskForm : taskForm?.value
    if (!form || typeof form.validate !== 'function') {
      console.error('[useTaskCrud] saveTask: no usable form ref to validate', taskForm)
      showToast({ message: 'Could not validate the form. Please try again.', type: 'error' })
      return
    }

    const { valid } = await form.validate()
    if (!valid) return

    saving.value = true
    saveError.value = ''
    try {
      if (editingTask.value) {
        const { parent_task_id: _parent, ...changedFields } = diffChangedFields(
          editSnapshot.value,
          currentTask.value,
        )
        await taskStore.updateTask(editingTask.value.id, changedFields)
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
      const parsed = parseErrorResponse(error)
      const message = parsed.isStructured ? parsed.message : GENERIC_SAVE_FAILURE
      showToast({ message, type: 'error' })
      if (parsed.isStructured) {
        saveError.value = parsed.message
      }
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
    saveError,
    editTask,
    cancelTask,
    saveTask,
    handleNewTask,
    openHandoverDialog,
    completeTask,
    updateTask,
    updateTaskField,
  }
}
