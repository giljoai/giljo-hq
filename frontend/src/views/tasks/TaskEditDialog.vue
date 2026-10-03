<template>
  <BaseDialog
    :model-value="modelValue"
    hide-icon
    :title="dialogTitle"
    :size="600"
    scrollable
    @update:model-value="$emit('update:modelValue', $event)"
    @cancel="$emit('cancel')"
  >
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

        <template v-if="isHandover">
          <div v-for="field in HANDOVER_FIELDS" :key="field.key" class="mb-2">
            <v-textarea
              :model-value="handoverValues[field.key]"
              :label="field.label"
              :hint="field.hint"
              persistent-hint
              variant="outlined"
              rows="2"
              auto-grow
              :data-test="`handover-field-${field.key}`"
              @update:model-value="updateHandoverField(field.key, $event)"
            />
            <p
              v-if="field.key === 'links'"
              class="text-body-small text-muted-a11y mt-1"
              data-test="handover-tip"
            >
              Tip: to copy a file path, Windows: Shift + right-click, then Copy as path. Mac: Option +
              right-click, then Copy as pathname.
            </p>
          </div>
        </template>
        <v-textarea
          v-else
          :model-value="currentTask.description"
          label="Description"
          variant="outlined"
          :rows="3"
          data-test="edit-task-description"
          @update:model-value="updateField('description', $event)"
        />

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
        data-test="edit-task-save"
        @click="$emit('save', taskFormRef)"
      >
        Save
      </v-btn>
    </template>
  </BaseDialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { RESERVED_TASK_TYPE_ABBR, RESERVED_HANDOVER_TYPE_ABBR } from '@/utils/constants'
import {
  HANDOVER_FIELDS,
  emptyHandoverValues,
  joinHandoverFields,
  splitHandoverDescription,
} from '@/composables/useHandoverFields'
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
  emit('update:currentTask', { ...props.currentTask, [field]: value })
}

const isHandover = computed(() => props.currentTask?.task_type === RESERVED_HANDOVER_TYPE_ABBR)

const dialogTitle = computed(() => {
  if (isHandover.value) return props.editingTask ? 'Edit Agent Handover' : 'Create new Handover'
  return props.editingTask ? 'Edit Task' : 'Create new Task'
})

const handoverValues = ref(emptyHandoverValues())
let lastJoined = null

watch(
  () => props.currentTask?.description,
  (description) => {
    if (!isHandover.value || description === lastJoined) return
    handoverValues.value = splitHandoverDescription(description)
    lastJoined = description || ''
  },
  { immediate: true },
)

function updateHandoverField(key, value) {
  handoverValues.value = { ...handoverValues.value, [key]: value || '' }
  lastJoined = joinHandoverFields(handoverValues.value)
  updateField('description', lastJoined)
}

defineExpose({ taskFormRef })
</script>
