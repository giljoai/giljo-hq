<template>
  <BaseDialog
    :model-value="modelValue"
    :icon="dialogIcon"
    :title="dialogTitle"
    :size="600"
    scrollable
    @update:model-value="$emit('update:modelValue', $event)"
    @cancel="$emit('cancel')"
  >
    <template #titleAppend>
      <span v-if="isHandover" class="hnd-pill" :style="hndPillStyle" data-test="handover-pill">
        {{ RESERVED_HANDOVER_TYPE_ABBR }}
      </span>
    </template>

    <template #default>
      <v-alert
        v-if="saveError"
        type="error"
        variant="tonal"
        density="compact"
        class="mb-3"
        data-test="dialog-save-error"
      >
        {{ saveError }}
      </v-alert>

      <p v-if="isHandover" class="text-body-medium text-muted-a11y mb-3" data-test="handover-subtitle">
        Starts from your handover template. Shape it once in Tools › Agents › Handover template.
      </p>

      <v-form ref="taskFormRef">
        <v-row>
          <v-col cols="6">
            <v-text-field
              :model-value="currentTask.task_type || RESERVED_TASK_TYPE_ABBR"
              label="Type"
              variant="outlined"
              readonly
              data-test="edit-task-type"
            />
          </v-col>
          <v-col cols="6">
            <v-text-field
              :model-value="
                editingTask
                  ? currentTask.series_number != null
                    ? String(currentTask.series_number).padStart(4, '0')
                    : '—'
                  : 'auto'
              "
              label="Serial"
              variant="outlined"
              readonly
              data-test="edit-task-serial"
            />
          </v-col>
        </v-row>

        <v-text-field
          :model-value="currentTask.title"
          label="Task Title"
          variant="outlined"
          :rules="[(v) => !!v || 'Title is required']"
          data-test="edit-task-title"
          @update:model-value="updateField('title', $event)"
        />

        <v-textarea
          :model-value="currentTask.description"
          label="Description"
          variant="outlined"
          :rows="isHandover ? 10 : 3"
          data-test="edit-task-description"
          @update:model-value="updateField('description', $event)"
        />

        <div v-if="isHandover" class="handover-checklist" data-test="handover-checklist">
          <p class="text-body-small text-muted-a11y mb-1" data-test="handover-tip">
            Windows: Shift + right-click, then Copy as path. Mac: Option + right-click,
            then Copy as pathname.
          </p>
          <div
            v-for="item in handoverChecklistItems"
            :key="item.heading"
            class="handover-checklist-item"
            :class="`handover-checklist-item--${item.status}`"
          >
            <v-icon
              :icon="item.status === 'done' ? 'mdi-check-circle' : 'mdi-alert-circle-outline'"
              size="16"
            />
            <span>{{ item.heading.replace('## ', '') }}</span>
          </div>
          <p
            v-if="!handoverComplete"
            class="text-body-small handover-gap-message mt-1"
            data-test="handover-gap-message"
          >
            Still needs: {{ handoverGapNames }}
          </p>
        </div>

        <v-row>
          <v-col cols="6">
            <v-select
              :model-value="currentTask.status"
              :items="statusSelectOptions"
              label="Status"
              variant="outlined"
              data-test="edit-task-status"
              @update:model-value="updateField('status', $event)"
            />
          </v-col>
          <v-col cols="6">
            <v-select
              :model-value="currentTask.priority"
              :items="priorityOptions"
              label="Priority"
              variant="outlined"
              data-test="edit-task-priority"
              @update:model-value="updateField('priority', $event)"
            />
          </v-col>
        </v-row>
      </v-form>
    </template>

    <template #actions>
      <v-spacer />
      <v-btn variant="text" @click="$emit('cancel')">Cancel</v-btn>
      <v-btn
        color="primary"
        variant="flat"
        :loading="saving"
        :disabled="!canSaveHandover"
        @click="$emit('save', taskFormRef)"
      >
        {{ editingTask ? 'Update' : 'Create' }}
      </v-btn>
    </template>
  </BaseDialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { RESERVED_TASK_TYPE_ABBR, RESERVED_HANDOVER_TYPE_ABBR } from '@/utils/constants'
import { resolveTaxonomyColor, taxonomyBadgeStyle } from '@/utils/taxonomyBadge'
import { useHandoverChecklist, vanishPlaceholdersOnType } from '@/composables/useHandoverChecklist'
import BaseDialog from '@/components/common/BaseDialog.vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
  editingTask: {
    type: Object,
    default: null,
  },
  currentTask: {
    type: Object,
    required: true,
  },
  saving: {
    type: Boolean,
    default: false,
  },
  statusSelectOptions: {
    type: Array,
    default: () => [],
  },
  saveError: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['update:modelValue', 'save', 'cancel', 'update:currentTask'])

const taskFormRef = ref(null)

const priorityOptions = ['low', 'medium', 'high', 'critical']

function updateField(field, value) {
  if (field === 'description' && isHandover.value) {
    value = vanishPlaceholdersOnType(props.currentTask.description || '', value)
  }
  emit('update:currentTask', { ...props.currentTask, [field]: value })
}

const isHandover = computed(() => props.currentTask?.task_type === RESERVED_HANDOVER_TYPE_ABBR)

const dialogTitle = computed(() => {
  if (isHandover.value) return props.editingTask ? 'Edit Agent Handover' : 'New Agent Handover'
  return props.editingTask ? 'Edit Task' : 'Create Task'
})

const dialogIcon = computed(() => {
  if (isHandover.value) return 'mdi-account-arrow-right'
  return props.editingTask ? 'mdi-pencil' : 'mdi-plus'
})

const hndPillStyle = computed(() =>
  taxonomyBadgeStyle(resolveTaxonomyColor({ abbreviation: RESERVED_HANDOVER_TYPE_ABBR })),
)

const handoverDescription = computed(() => props.currentTask?.description || '')
const {
  items: handoverChecklistItems,
  incomplete: handoverIncomplete,
  isComplete: handoverComplete,
} = useHandoverChecklist(handoverDescription)

const handoverGapNames = computed(() =>
  handoverIncomplete.value.map((item) => item.heading.replace('## ', '')).join(', '),
)

const canSaveHandover = computed(() => !isHandover.value || handoverComplete.value)

defineExpose({ taskFormRef })
</script>

<style lang="scss" scoped>
@use '../../styles/design-tokens' as *;

// Mirrors TasksTable.vue's `.taxonomy-badge` anatomy (BE-9637): same tinted
// background + full-brightness text via taxonomyBadgeStyle, a pill radius
// here since it sits beside a dialog title rather than in a table cell.
.hnd-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  margin-left: 8px;
  border-radius: $border-radius-pill;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  font-weight: 600;
  white-space: nowrap;
}

.handover-checklist {
  margin-top: 4px;
  margin-bottom: 16px;
}

.handover-checklist-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  color: $color-text-secondary;
  padding: 2px 0;
}

.handover-checklist-item--done {
  color: $color-accent-success;
}

.handover-gap-message {
  color: $color-text-secondary;
}
</style>
