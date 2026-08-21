<template>
  <v-container>
    <!-- Header -->
    <v-row class="align-center mb-4">
      <v-col>
        <h1 class="text-headline-large">Tasks</h1>
        <p class="text-body-medium text-muted-a11y mt-1">
          Use the /giljo skill to have the AI coding agent add ideas and thoughts to the Task dashboard, or read tasks back (filter by status, task_type, or priority).
          <v-tooltip location="bottom start" max-width="600">
            <template #activator="{ props }">
              <v-icon v-bind="props" size="16" class="help-icon">mdi-help-circle-outline</v-icon>
            </template>
            <div>
              <div class="font-weight-bold mb-1">Task Field Reference</div>
              <div class="text-body-small mb-2" style="color: var(--text-muted);">Instructions for /giljo</div>
              <div><span class="font-weight-medium">title (required):</span> Free text</div>
              <div class="mt-1"><span class="font-weight-medium">description (recommended):</span> Free text</div>
              <div class="mt-1"><span class="font-weight-medium">status (optional):</span></div>
              <div class="ml-2 text-body-small">pending · in_progress · completed · blocked · cancelled</div>
              <div class="mt-1"><span class="font-weight-medium">priority (optional):</span></div>
              <div class="ml-2 text-body-small">low · medium · high · critical</div>
              <div class="mt-1"><span class="font-weight-medium">task_type (optional):</span></div>
              <div class="ml-2 text-body-small">Taxonomy abbreviation (e.g. BE, FE, INF)</div>
              <div class="mt-2"><span class="font-weight-medium">Examples:</span></div>
              <div class="ml-2 text-body-small">/giljo add task ... description ...</div>
              <div class="ml-2 text-body-small">/giljo list tasks status=pending task_type=BE</div>
            </div>
          </v-tooltip>
        </p>
      </v-col>
    </v-row>

    <!-- Filters Row (0870h: restyled filter bar) -->
    <div class="filter-bar">
      <v-text-field
        v-model="search"
        prepend-inner-icon="mdi-magnify"
        placeholder="Search tasks..."
        variant="solo"
        density="compact"
        clearable
        hide-details
        flat
        aria-label="Search tasks by title"
        data-search-input
        class="filter-search"
      />
      <v-select
        v-model="statusFilter"
        :items="statusSelectOptions"
        placeholder="Status"
        variant="solo"
        density="compact"
        clearable
        hide-details
        flat
        class="filter-select"
      />
      <v-select
        v-model="priorityFilter"
        :items="priorityOptions"
        placeholder="Priority"
        variant="solo"
        density="compact"
        clearable
        hide-details
        flat
        class="filter-select"
      />
      <v-btn variant="text" class="filter-clear-btn" @click="clearFilters">Clear Filters</v-btn>
      <!-- BE-2002: circular "Show archived" toggle (mirrors the projects action bar).
           Yellow (theme `warning` token) when archived tasks are being shown.
           Backend field is `hidden`; UI calls it "archived". -->
      <v-btn
        v-if="hiddenCount > 0 || showHidden"
        :color="showHidden ? 'warning' : undefined"
        :variant="showHidden ? 'flat' : 'outlined'"
        :icon="showHidden ? 'mdi-archive' : 'mdi-archive-outline'"
        :title="showHidden ? 'Hide archived tasks' : `Show archived tasks (${hiddenCount})`"
        aria-label="Toggle archived tasks"
        class="filter-cta-archive"
        @click="showHidden = !showHidden"
      />
      <!-- FE-9365f: icon-only, mirroring the Projects action bar — the same action in
           two rooms should wear the same clothes. Labels live in title/aria. -->
      <v-btn
        color="primary"
        variant="flat"
        icon="mdi-plus"
        title="New task"
        aria-label="Create new task"
        @click="handleNewTask"
      />
      <v-btn
        variant="outlined"
        icon="mdi-delete-restore"
        title="Deleted tasks"
        aria-label="Show deleted tasks"
        data-testid="deleted-tasks-btn"
        @click="openDeletedTasksDialog"
      />
    </div>

    <!-- Tasks Table (extracted child component) -->
    <TasksTable
      :tasks="hierarchicalTasks"
      :loading="loading"
      :status-select-options="statusSelectOptions"
      :priority-options="priorityOptions"
      :has-active-filters="!!(search || statusFilter || priorityFilter)"
      @edit-task="editTask"
      @convert-task="convertTaskToProject"
      @complete-task="completeTask"
      @toggle-hidden="toggleHidden"
      @delete-task="deleteTask"
      @update-field="updateTaskField"
      @update-due-date="updateTaskDueDate"
    />

    <!-- Create/Edit Task Dialog (extracted child component) -->
    <TaskEditDialog
      v-model="showTaskDialog"
      :editing-task="editingTask"
      :current-task="currentTask"
      :saving="saving"
      :status-select-options="statusSelectOptions"
      @cancel="cancelTask"
      @save="saveTask"
      @update:current-task="onCurrentTaskUpdate"
    />

    <!-- No Active Product Warning Dialog -->
    <BaseDialog
      v-model="showNoProductDialog"
      type="warning"
      title="No Active Product"
      confirm-label="OK"
      cancel-text=""
      @confirm="showNoProductDialog = false"
    >
      <p class="text-body-large">
        No products are set to active state. Please activate a product before creating or converting tasks.
      </p>
    </BaseDialog>

    <!-- Conversion Confirmation Dialog -->
    <BaseDialog
      v-model="showConversionConfirmDialog"
      type="info"
      title="Convert to Project"
      icon="mdi-folder-arrow-up"
      confirm-label="Convert"
      @confirm="confirmConversion"
      @cancel="showConversionConfirmDialog = false"
    >
      <p class="text-body-large mb-2">
        Convert task <strong>"{{ conversionTaskName }}"</strong> to a project?
      </p>
      <p class="text-body-medium text-muted-a11y">
        This will create a new project in the active product with the task's title and
        description.
      </p>
    </BaseDialog>

    <!-- Delete Confirmation Dialog -->
    <BaseDialog
      v-model="showDeleteConfirmDialog"
      type="danger"
      title="Delete Task"
      icon="mdi-delete"
      confirm-label="Delete"
      @confirm="confirmDelete"
      @cancel="showDeleteConfirmDialog = false"
    >
      <p class="text-body-large mb-2">
        Are you sure you want to delete <strong>"{{ deleteTaskName }}"</strong>?
      </p>
      <v-alert type="info" variant="tonal" density="compact">
        This action cannot be undone.
      </v-alert>
    </BaseDialog>

    <!-- Success Dialog -->
    <BaseDialog
      v-model="showSuccessDialog"
      type="success"
      title="Success"
      confirm-label="OK"
      :persistent="false"
      @confirm="showSuccessDialog = false"
    >
      <p class="text-body-large">{{ successMessage }}</p>
    </BaseDialog>

    <!-- Error Dialog -->
    <BaseDialog
      v-model="showErrorDialog"
      type="danger"
      title="Error"
      confirm-label="OK"
      :persistent="false"
      @confirm="showErrorDialog = false"
    >
      <p class="text-body-large">{{ errorMessage }}</p>
    </BaseDialog>

    <!-- Deleted Tasks Dialog (FE-6138) -->
    <TaskDeletedDialog
      v-model="showDeletedTasksDialog"
      :deleted-tasks="deletedTasks"
      :restoring-id="restoringId"
      @restore="handleRestoreTask"
    />
  </v-container>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useTaskStore } from '@/stores/tasks'
import { useProductStore } from '@/stores/products'
import api from '@/services/api'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { useTaskFilters } from '@/composables/useTaskFilters'
import { useTaskCrud } from '@/composables/useTaskCrud'
import { useToast } from '@/composables/useToast'
import { useNotificationStore } from '@/stores/notifications'
import { notifyFailure } from '@/utils/notifyFailure'
import TasksTable from './tasks/TasksTable.vue'
import TaskEditDialog from './tasks/TaskEditDialog.vue'
import TaskDeletedDialog from '@/components/tasks/TaskDeletedDialog.vue'

// Stores
const taskStore = useTaskStore()
const productStore = useProductStore()
const notificationStore = useNotificationStore()
const { showToast } = useToast()

// Dialog state (conversion / delete / success / error stay in view)
const showNoProductDialog = ref(false)
const showConversionConfirmDialog = ref(false)
const showDeleteConfirmDialog = ref(false)
const showSuccessDialog = ref(false)
const showErrorDialog = ref(false)

// Deleted tasks dialog state (FE-6138)
const showDeletedTasksDialog = ref(false)
const deletedTasks = ref([])
const restoringId = ref(null)
const conversionTaskName = ref('')
const deleteTaskName = ref('')
const currentConvertingTask = ref(null)
const currentDeletingTask = ref(null)
const successMessage = ref('')
const errorMessage = ref('')

// Table headers (FE-5046: Serial column folds in the old Type column —
// taxonomy alias + type color tint render together as a single badge
// before the Title column). Kept here for test assertion access via
// wrapper.vm.headers (tests/unit/views/TasksView.spec.js).
// eslint-disable-next-line no-unused-vars -- exposed on vm for test assertions
const headers = [
  { title: 'Status', key: 'status', width: '110', align: 'center' },
  { title: 'Priority', key: 'priority', width: '80', align: 'center' },
  { title: 'Serial', key: 'taxonomy_alias', width: '105', align: 'center' },
  { title: 'Task', key: 'title', maxWidth: '340', align: 'start' },
  { title: 'Created', key: 'created_at', width: '150', align: 'center' },
  { title: 'Convert', key: 'convert', width: '60', align: 'center', sortable: false },
  { title: 'Actions', key: 'actions', sortable: false, width: '70', align: 'center' },
]

// Filter options
const priorityOptions = ['low', 'medium', 'high', 'critical']

// Computed
const loading = computed(() => taskStore.loading)
const tasks = computed(() => taskStore.tasks)

// Product-filtered tasks (all tasks are bound to a product - Handover 0433)
const userFilteredTasks = computed(() => {
  const productId = productStore.effectiveProductId
  if (!productId) {
    return []
  }
  return tasks.value.filter((task) => task.product_id === productId)
})

// Filters composable — receives product-scoped task list. Tasks are auto-TSK
// (BE-6049c), so there is no task-type filter (FE-6049e).
const {
  search,
  statusFilter,
  priorityFilter,
  showHidden,
  hiddenCount,
  statusSelectOptions,
  filteredTasks,
  clearFilters,
} = useTaskFilters(userFilteredTasks)

// Hierarchy feature disabled — return filtered tasks directly
const hierarchicalTasks = computed(() => filteredTasks.value)

// CRUD composable
const {
  showTaskDialog,
  showCreateDialog,
  editingTask,
  saving,
  currentTask,
  editTask,
  cancelTask,
  saveTask: _saveTask,
  handleNewTask: _handleNewTask,
  completeTask: _completeTask,
  updateTaskField: _updateTaskField,
  updateTaskDueDate: _updateTaskDueDate,
} = useTaskCrud()

// Wrap completeTask: list-row callers pass the task object; the composable
// expects (taskId, notes?). Keep the row-level UX unchanged.
async function completeTask(task) {
  try {
    await _completeTask(task.id)
  } catch (error) {
    errorMessage.value = 'Failed to complete task. Please try again.'
    showErrorDialog.value = true
    // FE-9466: the composable's own catch already pushed a notification for
    // this same rethrown error -- same operation + entityId + error code
    // computes the same id, so the store's dedup-by-id collapses this into
    // the same row rather than showing the failure twice.
    notifyFailure(notificationStore, {
      operation: 'task.complete',
      entityId: task.id,
      error,
      fallbackMessage: errorMessage.value,
      title: 'Task not completed',
    })
  }
}

// Wrap handleNewTask to show the no-product dialog when needed
function handleNewTask() {
  const result = _handleNewTask()
  if (result?.noProduct) {
    showNoProductDialog.value = true
  }
}

// Wrap updateTaskField to show the error dialog on failure
async function updateTaskField(task, field, value) {
  try {
    await _updateTaskField(task, field, value)
  } catch (error) {
    errorMessage.value = `Failed to update ${field}. Please try again.`
    showErrorDialog.value = true
    // FE-9466: useTaskCrud.updateTaskField has no catch of its own (out of
    // pass-one scope) -- this is the only layer that sees the failure, so
    // it is the only one that needs to push.
    notifyFailure(notificationStore, {
      operation: `task.updateField.${field}`,
      entityId: task.id,
      error,
      fallbackMessage: errorMessage.value,
      title: 'Task not updated',
    })
  }
}

// Wrap updateTaskDueDate to show the error dialog on failure
async function updateTaskDueDate(task, newDate) {
  try {
    await _updateTaskDueDate(task, newDate)
  } catch (error) {
    errorMessage.value = 'Failed to update due date. Please try again.'
    showErrorDialog.value = true
    // FE-9466: useTaskCrud.updateTaskDueDate has no catch of its own (out of
    // pass-one scope) -- this is the only layer that sees the failure.
    notifyFailure(notificationStore, {
      operation: 'task.updateDueDate',
      entityId: task.id,
      error,
      fallbackMessage: errorMessage.value,
      title: 'Due date not updated',
    })
  }
}

// Delegate saveTask with form ref and fetchTasks callback.
// TaskEditDialog emits (formRef) as the payload; unwrap it here.
async function saveTask(formRef) {
  await _saveTask(formRef, fetchTasks)
}

// Apply the dialog's `update:current-task` payload to the composable's
// `currentTask` ref. An explicit named handler (writing `.value` in script
// context where `currentTask` is unambiguously the ref) replaces the prior
// inline `currentTask = $event` assignment — same runtime effect, but it
// removes any reliance on the compiler's ref-write heuristic and is covered
// by the "silent-save regression" contract test in TasksView.spec.js so the
// dialog → save → POST wiring cannot silently break again.
function onCurrentTaskUpdate(updated) {
  currentTask.value = updated
}

async function convertTaskToProject(task) {
  if (!productStore.effectiveProductId) {
    showNoProductDialog.value = true
    return
  }
  conversionTaskName.value = task.title
  currentConvertingTask.value = task
  showConversionConfirmDialog.value = true
}

async function confirmConversion() {
  showConversionConfirmDialog.value = false
  const task = currentConvertingTask.value
  if (!task) return

  try {
    const response = await api.tasks.convertToProject(task.id)
    await taskStore.fetchTasks()
    successMessage.value = `Task successfully converted to project: ${response.data.name}`
    showSuccessDialog.value = true
  } catch (error) {
    console.error('Error converting task to project:', error)
    errorMessage.value = error.response?.data?.detail || 'Failed to convert task to project'
    showErrorDialog.value = true
  }

  currentConvertingTask.value = null
}

async function deleteTask(task) {
  deleteTaskName.value = task.title
  currentDeletingTask.value = task
  showDeleteConfirmDialog.value = true
}

async function confirmDelete() {
  showDeleteConfirmDialog.value = false
  const task = currentDeletingTask.value
  if (!task) return

  try {
    await taskStore.deleteTask(task.id)
    successMessage.value = `Task "${task.title}" deleted successfully`
    showSuccessDialog.value = true
  } catch (error) {
    console.error('Failed to delete task:', error)
    errorMessage.value = 'Failed to delete task. Please try again.'
    showErrorDialog.value = true
  }

  currentDeletingTask.value = null
}

// FE-6138: Deleted Tasks dialog — open handler fetches soft-deleted list
async function openDeletedTasksDialog() {
  deletedTasks.value = []
  showDeletedTasksDialog.value = true
  try {
    const params = {}
    if (productStore.currentProductId) {
      params.product_id = productStore.currentProductId
    }
    const response = await api.tasks.getDeleted(params)
    // Response is a list of TaskResponse directly (not wrapped)
    deletedTasks.value = response.data
  } catch (error) {
    console.error('[TASKS] Failed to load deleted tasks:', error)
    showToast({ message: 'Failed to load deleted tasks', type: 'error' })
    showDeletedTasksDialog.value = false
  }
}

// FE-6138: Handle restore action from TaskDeletedDialog
async function handleRestoreTask(task) {
  restoringId.value = task.id
  try {
    await api.tasks.restore(task.id)
    // Remove from the deleted list
    deletedTasks.value = deletedTasks.value.filter((t) => t.id !== task.id)
    // Refresh the main task list so the re-minted task appears
    await fetchTasks()
    showToast({ message: `Task "${task.title}" restored successfully`, type: 'success' })
  } catch (error) {
    console.error('[TASKS] Failed to restore task:', error)
    showToast({ message: 'Failed to restore task. Please try again.', type: 'error' })
  } finally {
    restoringId.value = null
  }
}

async function fetchTasks() {
  // BE-2002: fetch the full set INCLUDING archived (hidden) tasks. The list
  // endpoint has no server-side hidden filter, so the store holds every task and
  // useTaskFilters owns visibility — the default view hides archived rows, while
  // a search OR the "Show archived" toggle reveals them (badged "Archived").
  // (The prior `{ hidden: false }` param was a silent no-op the endpoint ignored.)
  const params = {}
  if (productStore.currentProductId) {
    params.product_id = productStore.currentProductId
  }
  await taskStore.fetchTasks(params)
}

// FE-5046 / BE-2002: Archive/Unarchive toggle in the actions menu — mirrors
// ProjectsView. Backend field stays `hidden`; UI copy says "archived".
async function toggleHidden(task) {
  try {
    await taskStore.updateTask(task.id, { hidden: !task.hidden })
    showToast({
      message: task.hidden ? `"${task.title}" restored from archive` : `"${task.title}" archived`,
      type: 'success',
    })
  } catch (error) {
    console.error('[TASKS] Failed to toggle hidden:', error)
    showToast({ message: 'Failed to update task visibility', type: 'error' })
  }
}

onMounted(() => {
  if (showCreateDialog.value) {
    showTaskDialog.value = true
  }
})

onMounted(async () => {
  try {
    await fetchTasks()
  } catch (error) {
    console.error('Failed to initialize TasksView:', error)
  }
})

</script>

<style lang="scss" scoped>
@use '../styles/variables' as *;
@use '../styles/design-tokens' as *;
@use '../styles/list-filter-bar' as filterBar;

@include filterBar.list-filter-bar;
@include filterBar.list-filter-bar-responsive;

.filter-select {
  flex: 0 0 160px;
}

.filter-clear-btn {
  color: $color-text-muted !important;
  font-size: 0.72rem;
  text-transform: none;
  letter-spacing: 0;
}
</style>
