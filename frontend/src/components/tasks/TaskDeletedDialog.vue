<template>
  <BaseDialog
    v-model="isOpen"
    type="warning"
    size="xl"
    scrollable
    hide-icon
    :title="`Deleted Tasks (${deletedTasks.length})`"
    data-testid="task-deleted-dialog"
  >
    <template #default>
      <v-list v-if="deletedTasks.length > 0" class="smooth-border rounded">
        <v-list-item v-for="(task, index) in deletedTasks" :key="task.id">
          <template #prepend>
            <v-icon icon="mdi-checkbox-marked-outline"></v-icon>
          </template>

          <div class="flex-grow-1">
            <div class="font-weight-bold">{{ task.title }}</div>
            <div class="text-body-small text-muted-a11y">
              {{ task.taxonomy_alias }}
            </div>
          </div>

          <template #append>
            <v-btn
              class="restore-btn"
              icon="mdi-restore"
              size="small"
              variant="text"
              :disabled="restoringId === task.id"
              title="Restore task"
              aria-label="Restore deleted task"
              data-testid="restore-task"
              @click="$emit('restore', task)"
            ></v-btn>
          </template>

          <v-divider v-if="index < deletedTasks.length - 1" class="my-2" />
        </v-list-item>
      </v-list>

      <div v-else class="text-center py-8 text-muted-a11y">
        <v-icon size="48" class="mb-4">mdi-checkbox-marked-outline</v-icon>
        <p>No deleted tasks</p>
      </div>
    </template>

    <template #actions>
      <v-spacer></v-spacer>
      <v-btn variant="text" @click="isOpen = false">Close</v-btn>
    </template>
  </BaseDialog>
</template>

<script setup>
import { computed } from 'vue'
import BaseDialog from '@/components/common/BaseDialog.vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
  deletedTasks: {
    type: Array,
    default: () => [],
  },
  restoringId: {
    type: String,
    default: null,
  },
})

const emit = defineEmits(['update:modelValue', 'restore'])

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.restore-btn {
  color: $color-brand-yellow !important;
}
</style>
