<template>
  <v-container>
    <v-row class="align-center mb-4">
      <v-col>
        <h1 class="text-headline-large">Tasks &amp; Handovers</h1>
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
              <div class="ml-2 text-body-small">pending · in_progress · on_hold · completed · blocked · cancelled</div>
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
        :items="statusFilterOptions"
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
      <v-menu>
        <template #activator="{ props: menuActivatorProps }">
          <v-btn
            v-bind="menuActivatorProps"
            color="primary"
            variant="flat"
            icon="mdi-plus"
            title="Add"
            aria-label="Add task or agent handover"
            data-testid="add-task-menu-btn"
          />
        </template>
        <v-list density="compact">
          <v-list-item
            title="New task"
            aria-label="Create new task"
            data-testid="new-task-menu-item"
            @click="handleNewTask"
          >
            <v-list-item-title>New task</v-list-item-title>
          </v-list-item>
          <v-list-item
            title="New Agent Handover"
            aria-label="Create new agent handover"
            data-testid="new-handover-menu-item"
            @click="handleNewHandover"
          >
            <v-list-item-title>New Agent Handover</v-list-item-title>
          </v-list-item>
        </v-list>
      </v-menu>
      <v-btn
        variant="outlined"
        icon="mdi-delete-restore"
        title="Deleted tasks"
        aria-label="Show deleted tasks"
        data-testid="deleted-tasks-btn"
        @click="openDeletedTasksDialog"
      />
    </div>

    <BulkActionBar
      :count="bulk.count.value"
      :page-count="pageCount"
      :matching-total="hierarchicalTasks.length"
      :all-matching="bulk.allMatching.value"
      :can-archive="canArchive"
      :can-unarchive="canUnarchive"
      :busy="bulkBusy"
      :noun="['task', 'tasks']"
      delete-note="Deleted tasks can be restored from Deleted tasks."
      @archive="archiveSelected"
      @unarchive="unarchiveSelected"
      @delete="deleteSelected"
      @clear="bulk.clear"
      @select-all-matching="selectAllMatching"
    />

    <TasksTable
      :tasks="hierarchicalTasks"
      :selected-ids="bulk.selectedIds.value"
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
      @update:selected-ids="onSelectedIds"
      @page-count="onPageCount"
    />

    <TaskEditDialog
      v-model="showTaskDialog"
      :editing-task="editingTask"
      :current-task="currentTask"
      :saving="saving"
      :save-error="saveError"
      :status-select-options="statusSelectOptions"
      @cancel="cancelTask"
      @save="saveTask"
      @update:current-task="onCurrentTaskUpdate"
    />

    <BaseDialog
      v-model="showNoProductDialog"
      type="warning"
      title="No Product Open"
      confirm-label="OK"
      cancel-text=""
      @confirm="showNoProductDialog = false"
    >
      <p class="text-body-large">
        No product is open. Add a product before creating or converting tasks.
      </p>
    </BaseDialog>

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
        This will create a new project in the viewed product with the task's title and
        description.
      </p>
    </BaseDialog>

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
import { parseErrorResponse } from '@/utils/errorMessages'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { useTaskFilters } from '@/composables/useTaskFilters'
import { useTaskCrud } from '@/composables/useTaskCrud'
import { useToast } from '@/composables/useToast'
import { useNotificationStore } from '@/stores/notifications'
import { notifyFailure } from '@/utils/notifyFailure'
import TasksTable from './tasks/TasksTable.vue'
import TaskEditDialog from './tasks/TaskEditDialog.vue'
import TaskDeletedDialog from '@/components/tasks/TaskDeletedDialog.vue'
import BulkActionBar from '@/components/common/BulkActionBar.vue'
import { useTaskBulkActions } from '@/composables/useTaskBulkActions'

const taskStore = useTaskStore()
const productStore = useProductStore()
const notificationStore = useNotificationStore()
const { showToast } = useToast()

const showNoProductDialog = ref(false)
const showConversionConfirmDialog = ref(false)
const showDeleteConfirmDialog = ref(false)
const showSuccessDialog = ref(false)
const showErrorDialog = ref(false)

const showDeletedTasksDialog = ref(false)
const deletedTasks = ref([])
const restoringId = ref(null)
const conversionTaskName = ref('')
const deleteTaskName = ref('')
const currentConvertingTask = ref(null)
const currentDeletingTask = ref(null)
const successMessage = ref('')
const errorMessage = ref('')

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

const priorityOptions = ['low', 'medium', 'high', 'critical']

const loading = computed(() => taskStore.loading)
const tasks = computed(() => taskStore.tasks)

const userFilteredTasks = computed(() => {
  const productId = productStore.effectiveProductId
  if (!productId) {
    return []
  }
  return tasks.value.filter((task) => task.product_id === productId)
})

const {
  search,
  statusFilter,
  priorityFilter,
  statusSelectOptions,
  statusFilterOptions,
  filteredTasks,
  clearFilters,
} = useTaskFilters(userFilteredTasks)

const hierarchicalTasks = computed(() => filteredTasks.value)

const {
  bulk,
  busy: bulkBusy,
  pageCount,
  canArchive,
  canUnarchive,
  onSelectedIds,
  selectAllMatching,
  archiveSelected,
  unarchiveSelected,
  deleteSelected,
} = useTaskBulkActions({
  visibleTasks: hierarchicalTasks,
  filterKeys: computed(() => [search.value, statusFilter.value, priorityFilter.value]),
})

function onPageCount(n) {
  pageCount.value = n
}

const {
  showTaskDialog,
  showCreateDialog,
  editingTask,
  saving,
  currentTask,
  saveError,
  editTask,
  cancelTask,
  saveTask: _saveTask,
  handleNewTask: _handleNewTask,
  openHandoverDialog,
  completeTask: _completeTask,
  updateTaskField: _updateTaskField,
} = useTaskCrud()

async function completeTask(task) {
  try {
    await _completeTask(task.id)
  } catch (error) {
    errorMessage.value = 'Failed to complete task. Please try again.'
    showErrorDialog.value = true
    notifyFailure(notificationStore, {
      operation: 'task.complete',
      entityId: task.id,
      error,
      fallbackMessage: errorMessage.value,
      title: 'Task not completed',
    })
  }
}

function handleNewTask() {
  const result = _handleNewTask()
  if (result?.noProduct) {
    showNoProductDialog.value = true
  }
}

async function handleNewHandover() {
  if (!productStore.effectiveProductId) {
    showNoProductDialog.value = true
    return
  }
  try {
    const response = await api.settings.getHandoverTemplate()
    openHandoverDialog(response?.data?.handover_template || '')
  } catch (error) {
    console.error('[TASKS] Failed to load the handover template:', error)
    showToast({ message: 'Failed to load the handover template. Please try again.', type: 'error' })
  }
}

async function updateTaskField(task, field, value) {
  try {
    await _updateTaskField(task, field, value)
  } catch (error) {
    errorMessage.value = `Failed to update ${field}. Please try again.`
    showErrorDialog.value = true
    notifyFailure(notificationStore, {
      operation: `task.updateField.${field}`,
      entityId: task.id,
      error,
      fallbackMessage: errorMessage.value,
      title: 'Task not updated',
    })
  }
}

async function saveTask(formRef) {
  await _saveTask(formRef, fetchTasks)
}

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
    errorMessage.value = parseErrorResponse(error).message || 'Failed to convert task to project'
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

async function openDeletedTasksDialog() {
  deletedTasks.value = []
  showDeletedTasksDialog.value = true
  try {
    const params = {}
    if (productStore.currentProductId) {
      params.product_id = productStore.currentProductId
    }
    const response = await api.tasks.getDeleted(params)
    deletedTasks.value = response.data
  } catch (error) {
    console.error('[TASKS] Failed to load deleted tasks:', error)
    showToast({ message: 'Failed to load deleted tasks', type: 'error' })
    showDeletedTasksDialog.value = false
  }
}

async function handleRestoreTask(task) {
  restoringId.value = task.id
  try {
    await api.tasks.restore(task.id)
    deletedTasks.value = deletedTasks.value.filter((t) => t.id !== task.id)
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
  const params = {}
  if (productStore.currentProductId) {
    params.product_id = productStore.currentProductId
  }
  await taskStore.fetchTasks(params)
}

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
