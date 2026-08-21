<template>
  <BaseDialog
    v-model="isOpen"
    data-testid="product-delete-dialog"
    type="warning"
    title="Move Product to Trash?"
    icon="mdi-delete"
    confirm-label="Move to Trash"
    confirm-checkbox
    confirm-checkbox-label="I understand this product will be recoverable for 10 days"
    :loading="deleting"
    @confirm="handleConfirm"
    @cancel="handleCancel"
  >
    <!-- Loading State -->
    <div v-if="loading" class="text-center py-4">
      <v-progress-circular indeterminate color="warning"></v-progress-circular>
      <div class="text-body-small mt-2">Calculating impact...</div>
    </div>

    <!-- Warning Content -->
    <template v-else>
      <v-alert type="info" variant="tonal" density="compact" class="mb-4">
        <div class="text-body-large font-weight-bold mb-2">Move to Trash?</div>
        <div>
          <strong>{{ product?.name }}</strong> will be moved to trash and can be recovered for 10
          days. After 10 days, it will be permanently deleted.
        </div>
      </v-alert>

      <!-- Cascade Impact -->
      <div v-if="cascadeImpact" class="mb-4">
        <div class="text-title-small mb-2">Kept with this product in the trash:</div>

        <v-list density="compact">
          <v-list-item>
            <template #prepend>
              <v-icon color="warning">mdi-folder-multiple</v-icon>
            </template>
            <v-list-item-title>
              <strong>{{ cascadeImpact.total_projects }}</strong> projects
            </v-list-item-title>
          </v-list-item>

          <v-list-item>
            <template #prepend>
              <v-icon color="warning">mdi-checkbox-marked-circle</v-icon>
            </template>
            <v-list-item-title>
              <strong>{{ cascadeImpact.total_tasks }}</strong> tasks
            </v-list-item-title>
          </v-list-item>

          <v-list-item>
            <template #prepend>
              <v-icon color="warning">mdi-file-document-multiple</v-icon>
            </template>
            <v-list-item-title>
              <strong>{{ cascadeImpact.total_vision_documents }}</strong> vision documents
            </v-list-item-title>
          </v-list-item>
        </v-list>

        <div class="text-body-small text-muted-a11y mt-2">
          These items are not deleted now. They are permanently deleted only when the product
          itself is — either when you delete it permanently from the trash, or automatically after
          10 days.
        </div>
      </div>
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
  product: {
    type: Object,
    default: () => ({}),
  },
  // Shape matches the backend CascadeImpact model (api/endpoints/products/models.py).
  cascadeImpact: {
    type: Object,
    default: () => ({
      total_projects: 0,
      total_tasks: 0,
      total_vision_documents: 0,
    }),
  },
  loading: {
    type: Boolean,
    default: false,
  },
  deleting: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const handleConfirm = () => {
  emit('confirm')
}

const handleCancel = () => {
  if (!props.deleting) {
    emit('cancel')
    isOpen.value = false
  }
}
</script>
