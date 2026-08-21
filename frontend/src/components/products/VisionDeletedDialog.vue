<template>
  <BaseDialog
    v-model="isOpen"
    type="warning"
    size="xl"
    scrollable
    hide-icon
    :title="`Deleted Vision Documents (${deletedDocuments.length})`"
    data-testid="vision-deleted-dialog"
  >
    <template #default>
      <v-list v-if="deletedDocuments.length > 0" class="smooth-border rounded">
        <v-list-item v-for="(doc, index) in deletedDocuments" :key="doc.id">
          <template #prepend>
            <v-icon icon="mdi-file-document-outline"></v-icon>
          </template>

          <div class="flex-grow-1">
            <div class="font-weight-bold">{{ doc.filename || doc.document_name }}</div>
            <div class="text-body-small text-muted-a11y">
              {{ doc.id }}
            </div>
          </div>

          <template #append>
            <v-btn
              class="restore-btn"
              icon="mdi-restore"
              size="small"
              variant="text"
              :disabled="restoringId === doc.id"
              :loading="restoringId === doc.id"
              title="Restore document"
              aria-label="Restore deleted vision document"
              data-testid="restore-vision"
              @click="$emit('restore', doc)"
            ></v-btn>
          </template>

          <v-divider v-if="index < deletedDocuments.length - 1" class="my-2" />
        </v-list-item>
      </v-list>

      <div v-else class="text-center py-8 text-muted-a11y">
        <v-icon size="48" class="mb-4">mdi-file-document-outline</v-icon>
        <p>No deleted documents</p>
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
  deletedDocuments: {
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
