<template>
  <div class="jb-done" data-testid="jobs-done-group">
    <button
      type="button"
      class="jb-done-h"
      :aria-expanded="open"
      data-testid="jobs-done-group-toggle"
      @click="open = !open"
    >
      <v-icon size="14">{{ open ? 'mdi-chevron-down' : 'mdi-chevron-right' }}</v-icon>
      <span class="jb-done-k">Done, not reviewed</span>
      <span class="jb-done-n" data-testid="jobs-done-group-count">({{ count }})</span>
    </button>
    <div v-if="open" class="jb-done-body" data-testid="jobs-done-group-cards">
      <slot />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  count: { type: Number, required: true },
})

const open = ref(false)
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-done {
  margin-top: 8px;
}

.jb-done-h {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: none;
  border: 0;
  padding: 6px 0;
  cursor: pointer;
  color: $color-text-secondary;
  font-size: 0.78rem;

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
  }
}

.jb-done-k {
  letter-spacing: 0.02em;
}

.jb-done-n {
  font-family: $typography-font-mono;
}

.jb-done-body {
  margin-top: 10px;
}
</style>
