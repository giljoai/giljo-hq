<template>
  <BaseDialog
    v-model="isOpen"
    data-testid="product-tuning-dialog"
    type="primary"
    icon="mdi-tune"
    title="Tune Context"
    :size="760"
    scrollable
    :persistent="false"
    @cancel="handleClose"
  >
    <template v-if="product">
      <div class="text-title-large mb-2">{{ product.name }}</div>
      <div class="text-body-small mb-4 text-muted-a11y font-mono tuning-product-id">
        ID: {{ product.id }}
      </div>

      <div class="text-title-small mb-2">Generate Tuning Prompt</div>
      <div class="text-body-small text-muted-a11y mb-3">
        Select the product sections you want to retune and generate a prompt for the next pass.
      </div>
      <ProductTuningMenu
        :product-id="product.id"
        hide-trigger
        initially-open
      />
    </template>

    <template #actions>
      <v-spacer />
      <v-btn variant="text" data-testid="product-tuning-close" @click="handleClose">Close</v-btn>
    </template>
  </BaseDialog>
</template>

<script setup>
import { computed } from 'vue'
import BaseDialog from '@/components/common/BaseDialog.vue'
import ProductTuningMenu from './ProductTuningMenu.vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
  product: {
    type: Object,
    default: () => ({}),
  },
})

const emit = defineEmits(['update:modelValue'])

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

function handleClose() {
  emit('update:modelValue', false)
}
</script>

<style lang="scss" scoped>
.tuning-product-id {
  font-size: 0.65rem;
}
</style>
