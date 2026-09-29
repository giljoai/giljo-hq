<template>
  <span class="run-as" :class="{ 'run-as--refused': refused }" data-testid="run-as-switch">
    <span class="run-as-k" data-testid="run-as-label">Run as</span>
    <span class="run-as-seg" role="group" aria-label="Run as">
      <v-tooltip v-for="choice in MODE_CHOICES" :key="choice.value" location="bottom" open-delay="150">
        <template #activator="{ props: tooltipProps }">
          <button
            v-bind="tooltipProps"
            type="button"
            class="run-as-btn"
            :aria-pressed="modelValue === choice.value"
            :disabled="locked"
            :data-testid="choice.testid"
            @click="!locked && emit('change', choice.value)"
          >
            {{ choice.label }}
          </button>
        </template>
        <span>{{ choice.tip }}</span>
      </v-tooltip>
    </span>
  </span>
</template>

<script setup>
defineProps({
  modelValue: { type: String, default: null },
  locked: { type: Boolean, default: false },
  refused: { type: Boolean, default: false },
})

const emit = defineEmits(['change'])

const MODE_CHOICES = [
  {
    value: 'multi_terminal',
    label: 'Multi-terminal',
    testid: 'radio-multi-terminal',
    tip: 'One terminal per agent. You watch the fleet.',
  },
  {
    value: 'subagent',
    label: 'Subagent',
    testid: 'radio-subagent',
    tip: 'One orchestrator session manages workers. Its harness is auto-detected when recognized; otherwise a universal protocol is used.',
  },
]
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.run-as {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.run-as-k {
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: $color-text-tertiary;
}

.run-as-seg {
  display: inline-flex;
  gap: 4px;
}

.run-as-btn {
  padding: 5px 14px;
  border-radius: $border-radius-pill;
  border: 0;
  background: none;
  color: $color-text-secondary;
  box-shadow: inset 0 0 0 1px $color-border-secondary;
  font: inherit;
  font-size: 0.74rem;
  font-weight: 500;
  cursor: pointer;

  &:hover:not(:disabled),
  &:focus-visible {
    color: $color-text-primary;
  }

  &[aria-pressed='true'] {
    background: rgba($color-brand-yellow, 0.12);
    color: $color-brand-yellow;
    box-shadow: none;
  }

  &:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .run-as--refused & {
    box-shadow: inset 0 0 0 1px rgba($color-status-warning, 0.6);
  }
}
</style>
