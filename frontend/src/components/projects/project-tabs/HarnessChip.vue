<template>
  <span v-if="label" class="harness-chip" data-testid="harness-chip">
    detected: {{ label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { retiredHarnessLabel } from '@/config/retiredHarness'

const props = defineProps({
  harness: {
    type: String,
    default: null,
  },
})

const HARNESS_LABELS = {
  'claude-code': 'Claude Code',
  codex: 'Codex',
  opencode: 'opencode',
}

const label = computed(() => HARNESS_LABELS[props.harness] || retiredHarnessLabel(props.harness))
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens.scss' as *;

.harness-chip {
  display: inline-flex;
  align-items: center;
  border-radius: $border-radius-pill;
  padding: 3px 10px;
  font-size: 0.68rem;
  font-weight: 600;
  white-space: nowrap;
  background: rgba(var(--v-theme-on-surface), 0.08);
  color: var(--text-muted);
}
</style>
