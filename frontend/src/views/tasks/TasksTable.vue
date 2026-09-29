<template>
  <v-card class="task-table-card smooth-border">
    <v-data-table
      :headers="headers"
      :items="tasks"
      :loading="loading"
      :items-per-page="25"
      class="elevation-0 scrollable-table"
      data-table
      item-value="id"
      show-select
      :model-value="selectedIds"
      @update:model-value="$emit('update:selected-ids', $event)"
      @update:current-items="$emit('page-count', $event.length)"
    >
        <template #loading>
          <div class="text-center pa-4">
            <v-progress-circular indeterminate color="primary" size="48" />
            <p class="text-body-medium text-muted-a11y mt-2">Loading tasks...</p>
          </div>
        </template>

        <template #item.status="{ item }">
          <div class="d-flex justify-center">
            <v-select
              :model-value="item.status"
              :items="statusSelectOptions"
              variant="plain"
              density="compact"
              hide-details
              class="inline-select inline-select-no-arrow"
              @update:model-value="(newStatus) => $emit('update-field', item, 'status', newStatus)"
            >
              <template #selection="{ internalItem: statusItem }">
                <TaskStatusBadge :status="statusItem.value" />
              </template>
              <template #item="{ props, internalItem: statusItem }">
                <v-list-item v-bind="props">
                  <template #prepend>
                    <v-icon :color="getStatusColor(statusItem.value)" size="small">
                      {{ getStatusIcon(statusItem.value) }}
                    </v-icon>
                  </template>
                </v-list-item>
              </template>
            </v-select>
          </div>
        </template>

        <template #item.priority="{ item }">
          <div class="d-flex justify-center">
          <v-select
            :model-value="item.priority"
            :items="priorityOptions"
            variant="plain"
            density="compact"
            hide-details
            class="inline-select inline-select-no-arrow"
            @update:model-value="(newPriority) => $emit('update-field', item, 'priority', newPriority)"
          >
            <template #selection="{ internalItem: priorityItem }">
              <span
                class="priority-pill"
                :class="'priority-' + priorityItem.value"
              >
                {{ priorityItem.value }}
              </span>
            </template>
            <template #item="{ props, internalItem: priorityItem }">
              <v-list-item v-bind="props">
                <template #prepend>
                  <span
                    class="priority-pill"
                    :class="'priority-' + priorityItem.value"
                  >
                    {{ priorityItem.value }}
                  </span>
                </template>
              </v-list-item>
            </template>
          </v-select>
          </div>
        </template>

        <template #item.title="{ item }">
          <div
            class="task-row-content"
            :data-test="`task-row-${item.id}`"
            @click="$emit('edit-task', item)"
          >
            <div class="task-content flex-grow-1">
              <div class="task-title">
                {{ item.title }}
                <v-chip
                  v-if="item.hidden"
                  size="x-small"
                  color="warning"
                  variant="tonal"
                  prepend-icon="mdi-archive"
                  class="ml-2 archived-badge"
                  data-test="task-archived-badge"
                >Archived</v-chip>
              </div>
              <div class="task-desc">
                {{ item.description }}
              </div>
            </div>
          </div>
        </template>

        <template #item.created_at="{ item }">
          <span class="date-cell">{{ formatDateWithTime(item.created_at) }}</span>
        </template>

        <template #item.taxonomy_alias="{ item }">
          <div class="d-flex justify-center">
            <span
              v-if="item.taxonomy_alias"
              class="taxonomy-badge"
              :style="taxonomyBadgeStyle(resolveTaxonomyColor({
                abbreviation: item.task_type?.abbreviation,
                alias: item.taxonomy_alias,
                color: item.task_type_color || item.task_type?.color,
              }))"
            >
              {{ item.taxonomy_alias }}
            </span>
            <span v-else class="date-cell--empty">—</span>
          </div>
        </template>

        <template #item.convert="{ item }">
          <div class="d-flex justify-center">
            <button
              v-if="item.status !== 'completed' && !item.converted_project_id && !isHandoverRow(item)"
              class="row-action icon-interactive convert-action"
              aria-label="Convert to project"
              @click.stop="$emit('convert-task', item)"
            >
              <v-icon size="16">mdi-folder-arrow-right</v-icon>
              <v-tooltip activator="parent" location="top"> Convert to Project </v-tooltip>
            </button>
            <span v-else class="date-cell--empty">—</span>
          </div>
        </template>

        <template #item.actions="{ item }">
          <v-menu>
            <template #activator="{ props }">
              <v-btn icon="mdi-dots-vertical" size="small" variant="text" v-bind="props" aria-label="Task actions" />
            </template>
            <v-list>
              <v-list-item @click="$emit('edit-task', item)">
                <template #prepend>
                  <v-icon>mdi-pencil</v-icon>
                </template>
                <v-list-item-title>Edit</v-list-item-title>
              </v-list-item>

              <v-list-item
                v-if="item.status !== 'completed' && !isHandoverRow(item)"
                @click="$emit('convert-task', item)"
              >
                <template #prepend>
                  <v-icon>mdi-folder-arrow-up</v-icon>
                </template>
                <v-list-item-title>Convert to Project</v-list-item-title>
              </v-list-item>

              <v-list-item v-if="item.status !== 'completed'" @click="$emit('complete-task', item)">
                <template #prepend>
                  <v-icon color="success">mdi-check</v-icon>
                </template>
                <v-list-item-title>Mark Complete</v-list-item-title>
              </v-list-item>

              <v-list-item
                data-test="task-hide-action"
                :disabled="isPendingHandover(item)"
                @click="$emit('toggle-hidden', item)"
              >
                <template #prepend>
                  <v-icon>{{ item.hidden ? 'mdi-archive-arrow-up' : 'mdi-archive' }}</v-icon>
                </template>
                <v-list-item-title>{{ item.hidden ? 'Unarchive' : 'Archive' }}</v-list-item-title>
                <v-tooltip v-if="isPendingHandover(item)" activator="parent" location="start">
                  Nobody has read this handover yet. Mark it in progress or completed first.
                </v-tooltip>
              </v-list-item>

              <v-divider />

              <v-list-item @click="$emit('delete-task', item)">
                <template #prepend>
                  <v-icon color="error">mdi-delete</v-icon>
                </template>
                <v-list-item-title>Delete</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-menu>
        </template>

        <template #no-data>
          <EmptyState
            icon="mdi-clipboard-text-outline"
            title="No tasks found"
            :description="hasActiveFilters
              ? 'Try adjusting your filters'
              : 'Create your first task to get started'"
          />
        </template>
    </v-data-table>
  </v-card>
</template>

<script setup>
import { useFormatDate } from '@/composables/useFormatDate'
import { getAgentColor } from '@/config/agentColors'
import { TEXT_MUTED } from '@/config/colorTokens'
import { STATUS_COLORS } from '@/utils/statusConfig'
import { taxonomyBadgeStyle, resolveTaxonomyColor, isHandoverRow } from '@/utils/taxonomyBadge'
import TaskStatusBadge from '@/components/TaskStatusBadge.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const props = defineProps({
  tasks: {
    type: Array,
    required: true,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  statusSelectOptions: {
    type: Array,
    default: () => [],
  },
  priorityOptions: {
    type: Array,
    default: () => ['low', 'medium', 'high', 'critical'],
  },
  hasActiveFilters: {
    type: Boolean,
    default: false,
  },
  selectedIds: {
    type: Array,
    default: () => [],
  },
})

defineEmits([
  'edit-task',
  'convert-task',
  'complete-task',
  'toggle-hidden',
  'delete-task',
  'update-field',
  'update:selected-ids',
  'page-count',
])

function isPendingHandover(item) {
  return isHandoverRow(item) && item?.status === 'pending'
}

const { formatDateWithTime } = useFormatDate()

const headers = [
  { title: 'Status', key: 'status', width: '110', align: 'center' },
  { title: 'Priority', key: 'priority', width: '80', align: 'center' },
  { title: 'Serial', key: 'taxonomy_alias', width: '105', align: 'center' },
  { title: 'Task', key: 'title', maxWidth: '340', align: 'start' },
  { title: 'Created', key: 'created_at', width: '150', align: 'center' },
  { title: 'Convert', key: 'convert', width: '60', align: 'center', sortable: false },
  { title: 'Actions', key: 'actions', sortable: false, width: '70', align: 'center' },
]

function getStatusColor(status) {
  const colors = {
    pending: STATUS_COLORS.PENDING,
    in_progress: getAgentColor('implementer').hex,
    on_hold: getAgentColor('reviewer').hex,
    completed: getAgentColor('documenter').hex,
    blocked: getAgentColor('analyzer').hex,
    cancelled: TEXT_MUTED,
  }
  return colors[status] || STATUS_COLORS.PENDING
}

function getStatusIcon(status) {
  const icons = {
    pending: 'mdi-clock-outline',
    in_progress: 'mdi-progress-clock',
    on_hold: 'mdi-pause-circle-outline',
    completed: 'mdi-check-circle',
    blocked: 'mdi-block-helper',
    cancelled: 'mdi-cancel',
  }
  return icons[status] || 'mdi-help'
}
</script>

<style lang="scss" scoped>
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;

/* 0870h: smooth-border table panel */
.task-table-card {
  border: none !important;
  border-radius: $border-radius-rounded !important;
  overflow: hidden;

  // Make inner table transparent so card's inset box-shadow border shows on all sides
  :deep(.v-table) {
    background: transparent;
  }
}

/* Table body expands to show all rows; browser scrollbar handles overflow */
.scrollable-table :deep(.v-table__wrapper) {
  overflow: visible;
}

/* Pagination footer: sticky at viewport bottom */
.scrollable-table :deep(.v-data-table-footer) {
  border-top: 1px solid $color-border-subtle;
}

/* 0870h: table header cells */
:deep(.v-data-table__thead th) {
  @include table-header-label;
  border-bottom: 1px solid $color-border-subtle !important;
}

/* 0870h: row hover and separators */
:deep(.v-data-table__tr) {
  transition: background $transition-fast;
  cursor: pointer;
}

:deep(.v-data-table__tr:hover) {
  background: rgba(255, 255, 255, 0.02) !important;
}

:deep(.v-data-table__td) {
  @include table-row-separator;
  font-size: 0.8rem;
}

:deep(.v-data-table__tr:last-child .v-data-table__td) {
  border-bottom: none !important;
}

/* 0870h: tinted priority pills */
.priority-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: $border-radius-sharp;
  font-size: 0.62rem;
  font-weight: 500;
}

.priority-critical {
  background: rgba($color-agent-analyzer, 0.15);
  color: $color-agent-analyzer;
}

.priority-high {
  background: rgba($color-agent-analyzer, 0.1);
  color: $color-agent-analyzer;
}

.priority-medium {
  background: rgba(255, 255, 255, 0.05);
  color: $color-text-secondary;
}

.priority-low {
  background: rgba(255, 255, 255, 0.03);
  color: $color-text-muted;
}

/* Task content wrapper — constrain for truncation */
.task-content {
  min-width: 0;
  overflow: hidden;
}

/* 0870h: task title — brand yellow, truncated */
.task-title {
  font-size: 0.82rem;
  font-weight: 500;
  color: $color-brand-yellow;
  margin-bottom: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 0870h: task description — muted text, clamped */
.task-desc {
  font-size: 0.72rem;
  color: $color-text-muted;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* FE-5046: Tinted square taxonomy badge */
.taxonomy-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: $border-radius-sharp;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  font-weight: 600;
  white-space: nowrap;
}

/* Column alignment + width discipline. */

/* Headers: never wrap. */
:deep(.v-data-table__thead th) {
  white-space: nowrap !important;
}

/* Column positions count the FE-9641 select column: 1 select, 2 Status,
   3 Priority, 4 Serial, 5 Task. Centered: everything except Task (5). */
:deep(.v-data-table__thead th:not(:nth-child(5))),
:deep(.v-data-table__tr td:not(:nth-child(5))) {
  text-align: center !important;
}

/* Center the title+sort-icon group inside the header cell */
:deep(.v-data-table__thead th:not(:nth-child(5)) .v-data-table-header__content) {
  justify-content: center !important;
  position: relative;
}

/* Float the sort arrow out of the flex flow */
:deep(.v-data-table__thead th:not(:nth-child(5)) .v-data-table-header__content > i) {
  position: absolute !important;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
}

/* Left-aligned: Task (5). */
:deep(.v-data-table__thead th:nth-child(5)),
:deep(.v-data-table__tr td:nth-child(5)) {
  text-align: left !important;
}

/* Tighten cell padding on the badge columns (Priority, Serial). */
:deep(.v-data-table__thead th:nth-child(3)),
:deep(.v-data-table__thead th:nth-child(4)),
:deep(.v-data-table__tr td:nth-child(3)),
:deep(.v-data-table__tr td:nth-child(4)) {
  padding-left: 4px !important;
  padding-right: 4px !important;
}

/* Force the badge/pill inside a v-select to sit at centre of v-field input */
.inline-select :deep(.v-field__input) {
  justify-content: center;
}

/* Match Status badge font to Priority pill size */
:deep(.task-status-badge) {
  font-size: 0.62rem;
}

/* Created column: plain-text date */
.date-cell {
  font-size: 0.72rem;
}

/* 0870h: row action buttons */
.row-action {
  width: 30px;
  height: 30px;
  border: none;
  background: transparent;
  display: inline-grid;
  place-items: center;
  font-size: 16px;
}

.convert-action {
  color: $color-brand-yellow;
  opacity: 0.6;
}

.convert-action:hover {
  opacity: 1;
}

/* 0870h: date cell & empty state */
.date-cell--empty {
  color: $color-text-muted;
}

/* Inline editing styles */
.inline-select :deep(.v-field) {
  border: none;
  box-shadow: none;
}

.inline-select :deep(.v-field__input) {
  padding: 0;
  min-height: auto;
  overflow: visible;
}

.inline-select:hover :deep(.v-field) {
  background-color: rgba(255, 255, 255, 0.03);
  border-radius: $border-radius-sharp;
}

.inline-select :deep(.v-input__control) {
  overflow: visible;
}

.inline-select :deep(.v-field__field) {
  overflow: visible;
}

/* Hide arrow indicator for category column */
.inline-select-no-arrow :deep(.v-field__append-inner) {
  display: none;
}

.task-row-content {
  display: flex;
  align-items: center;
  padding: 8px 4px;
  border-radius: $border-radius-sharp;
  transition: all $transition-normal ease;
  min-height: 48px;
  cursor: pointer;
  max-width: 100%;
  overflow: hidden;
}

.task-row-content:hover {
  background-color: rgba(255, 255, 255, 0.03);
}

/* Fix dropdown menu icons being cut off */
.inline-select :deep(.v-list-item) {
  padding-left: 16px;
  padding-right: 16px;
}

.inline-select :deep(.v-list-item__prepend) {
  margin-right: 12px;
}

.inline-select :deep(.v-list-item__prepend .v-icon) {
  margin: 0;
}
</style>
