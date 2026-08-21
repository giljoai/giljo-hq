<template>
  <BaseDialog
    v-model="isOpen"
    type="info"
    size="xl"
    scrollable
    hide-icon
    :title="`Deleted Threads (${deletedThreads.length})`"
    data-testid="thread-deleted-dialog"
  >
    <template #default>
      <v-list v-if="deletedThreads.length > 0" class="smooth-border rounded">
        <v-list-item v-for="(thread, index) in deletedThreads" :key="thread.thread_id">
          <template #prepend>
            <v-icon icon="mdi-forum-outline"></v-icon>
          </template>

          <div class="flex-grow-1">
            <div class="font-weight-bold">{{ thread.chat_id || thread.thread_id }}</div>
            <div class="text-body-small text-muted-a11y">
              {{ thread.subject || '(no subject)' }}
            </div>
          </div>

          <template #append>
            <v-btn
              class="restore-btn"
              icon="mdi-restore"
              size="small"
              variant="text"
              :disabled="restoringId === thread.thread_id"
              title="Restore thread"
              aria-label="Restore deleted thread"
              data-testid="restore-thread"
              @click="$emit('restore', thread)"
            ></v-btn>
          </template>

          <v-divider v-if="index < deletedThreads.length - 1" class="my-2" />
        </v-list-item>
      </v-list>

      <div v-else class="text-center py-8 text-muted-a11y">
        <v-icon size="48" class="mb-4">mdi-forum-outline</v-icon>
        <p>No deleted threads</p>
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
  deletedThreads: {
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
