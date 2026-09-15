<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.
-->
<template>
  <div class="banner-fold-controls" data-testid="banner-fold-controls">
    <button
      class="banner-fold-chevron"
      data-testid="banner-fold-chevron"
      :aria-expanded="modelValue"
      aria-label="Toggle folded banner list"
      @click="$emit('update:modelValue', !modelValue)"
    >
      <v-icon :icon="modelValue ? 'mdi-chevron-up' : 'mdi-chevron-down'" size="16" />
    </button>
    <span class="banner-fold-qty" data-testid="banner-fold-qty">{{ qty }}</span>
  </div>
</template>

<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  qty: { type: Number, required: true },
})
defineEmits(['update:modelValue'])
</script>

<style scoped lang="scss">
@use '@/styles/banner-unified' as banner;

.banner-fold-controls {
  @include banner.unified-fold-controls;
}

.banner-fold-chevron {
  @include banner.unified-fold-chevron;
}

.banner-fold-qty {
  @include banner.unified-fold-qty;
}
</style>
