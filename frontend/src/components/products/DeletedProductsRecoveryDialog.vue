<template>
  <BaseDialog
    v-model="isOpen"
    type="info"
    size="xl"
    scrollable
    icon="mdi-delete-restore"
    :title="`Deleted Products (${deletedProducts.length})`"
  >
    <template #default>
      <v-alert
        v-if="deletedProducts.length > 0"
        type="warning"
        variant="tonal"
        density="compact"
        class="mb-3"
      >
        Permanently deleting items will remove all related data immediately. This action cannot be
        undone.
      </v-alert>

      <v-list v-if="deletedProducts.length > 0" class="border rounded">
        <v-list-item v-for="(product, index) in deletedProducts" :key="product.id">
          <template v-slot:prepend>
            <v-icon icon="mdi-package-variant-closed"></v-icon>
          </template>

          <div class="flex-grow-1">
            <div class="font-weight-bold">{{ product.name }}</div>
            <div class="text-body-small text-muted-a11y">
              {{ product.description || product.id }}
            </div>
          </div>

          <template v-slot:append>
            <div class="d-flex align-center ga-1">
              <v-btn
                icon="mdi-delete-restore"
                size="small"
                variant="text"
                :loading="restoringProductId === product.id"
                :disabled="purgingProductId === product.id || purgingAll"
                title="Restore product"
                aria-label="Restore deleted product"
                data-testid="product-recover-restore"
                @click="handleRestore(product.id)"
              ></v-btn>
              <v-btn
                icon="mdi-delete-forever"
                size="small"
                variant="text"
                color="error"
                :loading="purgingProductId === product.id"
                :disabled="restoringProductId === product.id || purgingAll"
                title="Permanently delete product"
                aria-label="Permanently delete product"
                data-testid="product-recover-purge"
                @click="handlePurge(product.id)"
              ></v-btn>
            </div>
          </template>

          <v-divider v-if="index < deletedProducts.length - 1" class="my-2" />
        </v-list-item>
      </v-list>

      <div v-else class="text-center py-8 text-muted-a11y">
        <v-icon size="48" class="mb-4">mdi-package-variant</v-icon>
        <p>No deleted products</p>
      </div>
    </template>

    <template #actions>
      <v-spacer />
      <v-btn variant="text" data-testid="product-recover-close" @click="closeDialog">Close</v-btn>
      <v-btn
        color="error"
        variant="flat"
        prepend-icon="mdi-delete-forever"
        :disabled="deletedProducts.length === 0 || purgingAll"
        :loading="purgingAll"
        data-testid="product-recover-purge-all"
        @click="handlePurgeAll"
      >
        Delete All
      </v-btn>
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
  deletedProducts: {
    type: Array,
    default: () => [],
  },
  restoringProductId: {
    type: String,
    default: null,
  },
  purgingProductId: {
    type: String,
    default: null,
  },
  purgingAll: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:modelValue', 'restore', 'purge', 'purge-all'])

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const closeDialog = () => {
  emit('update:modelValue', false)
}

const handleRestore = (productId) => {
  emit('restore', productId)
}

const handlePurge = (productId) => {
  emit('purge', productId)
}

const handlePurgeAll = () => {
  emit('purge-all')
}
</script>
