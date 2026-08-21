<template>
  <BaseDialog
    v-model="isOpen"
    type="warning"
    size="xl"
    scrollable
    hide-icon
    :title="`Deleted Projects (${deletedProjects.length})`"
  >
    <template #default>
      <v-alert
        v-if="deletedProjects.length > 0"
        type="warning"
        variant="tonal"
        density="compact"
        class="mb-3"
      >
        Permanently deleting items will remove all related data immediately. This action cannot be
        undone.
      </v-alert>

      <v-list v-if="deletedProjects.length > 0" class="smooth-border rounded">
        <v-list-item v-for="(project, index) in deletedProjects" :key="project.id">
          <template #prepend>
            <v-icon icon="mdi-folder-minus"></v-icon>
          </template>

          <div class="flex-grow-1">
            <div class="font-weight-bold">{{ project.name }}</div>
            <div class="text-body-small text-muted-a11y">
              {{ project.id }}
            </div>
          </div>

          <template #append>
            <div class="d-flex align-center ga-1">
              <v-btn
                class="restore-btn"
                icon="mdi-restore"
                size="small"
                variant="text"
                :disabled="purgingProjectId === project.id || purgingAllDeleted"
                title="Restore project"
                aria-label="Restore deleted project"
                @click="$emit('restore', project)"
              ></v-btn>
              <v-btn
                icon="mdi-delete-forever"
                size="small"
                variant="text"
                color="error"
                :loading="purgingProjectId === project.id"
                :disabled="purgingAllDeleted"
                title="Permanently delete project"
                aria-label="Permanently delete project"
                data-testid="purge-project"
                @click="$emit('purge', project)"
              ></v-btn>
            </div>
          </template>

          <v-divider v-if="index < deletedProjects.length - 1" class="my-2" />
        </v-list-item>
      </v-list>

      <div v-else class="text-center py-8 text-muted-a11y">
        <v-icon size="48" class="mb-4">mdi-folder-open</v-icon>
        <p>No deleted projects</p>
      </div>
    </template>

    <template #actions>
      <v-spacer></v-spacer>
      <v-btn
        color="error"
        variant="flat"
        prepend-icon="mdi-delete-forever"
        :disabled="deletedProjects.length === 0 || purgingAllDeleted"
        :loading="purgingAllDeleted"
        data-testid="purge-projects-all"
        @click="$emit('purge-all')"
      >
        Delete All
      </v-btn>
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
  deletedProjects: {
    type: Array,
    default: () => [],
  },
  purgingProjectId: {
    type: String,
    default: null,
  },
  purgingAllDeleted: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:modelValue', 'restore', 'purge', 'purge-all'])

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
