<template>
  <BaseDialog
    :model-value="modelValue"
    :icon="editingTask ? 'mdi-pencil' : 'mdi-plus'"
    :title="editingTask ? 'Edit Task' : 'Create Task'"
    :size="600"
    scrollable
    @update:model-value="$emit('update:modelValue', $event)"
    @cancel="$emit('cancel')"
  >
    <template #default>
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
          rows="3"
          @update:model-value="updateField('description', $event)"
        />

        <v-row>
          <v-col cols="6">
            <v-select
              :model-value="currentTask.status"
              :items="statusSelectOptions"
              label="Status"
              variant="outlined"
              @update:model-value="updateField('status', $event)"
            />
          </v-col>
          <v-col cols="6">
            <v-select
              :model-value="currentTask.priority"
              :items="priorityOptions"
              label="Priority"
              variant="outlined"
              @update:model-value="updateField('priority', $event)"
            />
          </v-col>
        </v-row>

        <v-text-field
          :model-value="currentTask.due_date"
          label="Due Date"
          type="date"
          variant="outlined"
          @update:model-value="updateField('due_date', $event)"
        />
      </v-form>
    </template>

    <template #actions>
      <v-spacer />
      <v-btn variant="text" @click="$emit('cancel')">Cancel</v-btn>
      <v-btn color="primary" variant="flat" :loading="saving" @click="$emit('save', taskFormRef)">
        {{ editingTask ? 'Update' : 'Create' }}
      </v-btn>
    </template>
  </BaseDialog>
</template>

<script setup>
import { ref } from 'vue'
import { RESERVED_TASK_TYPE_ABBR } from '@/utils/constants'
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
})

const emit = defineEmits(['update:modelValue', 'save', 'cancel', 'update:currentTask'])

const taskFormRef = ref(null)

const priorityOptions = ['low', 'medium', 'high', 'critical']

function updateField(field, value) {
  emit('update:currentTask', { ...props.currentTask, [field]: value })
}

defineExpose({ taskFormRef })
</script>
