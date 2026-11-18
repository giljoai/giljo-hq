<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.
-->
<template>
  <button
    type="button"
    class="banner-expand-toggle"
    data-testid="banner-expand-toggle"
    :aria-expanded="expanded ? 'true' : 'false'"
    :aria-controls="controls"
    @click.stop="$emit('toggle')"
  >
    {{ expanded ? 'Less' : 'More' }}
  </button>
</template>

<script setup>
defineProps({
  expanded: { type: Boolean, default: false },
  controls: { type: String, required: true },
})
defineEmits(['toggle'])
</script>

<style scoped lang="scss">
@use '@/styles/banner-unified' as banner;

.banner-expand-toggle {
  @include banner.unified-banner-expand-toggle;
}
</style>
