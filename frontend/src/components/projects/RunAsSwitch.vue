<template>
  <span class="run-as-seg" role="group" :aria-labelledby="labelledBy || undefined" data-testid="run-as-switch">
    <v-tooltip v-for="choice in MODE_CHOICES" :key="choice.value" location="bottom" open-delay="150">
      <template #activator="{ props: tooltipProps }">
        <button
          v-bind="tooltipProps"
          type="button"
          class="run-as-btn"
          :aria-pressed="modelValue === choice.value"
          :data-testid="choice.testid"
          @click="emit('change', choice.value)"
        >
          {{ choice.label }}
        </button>
      </template>
      <span>{{ choice.tip }}</span>
    </v-tooltip>
  </span>
</template>

<script setup>
defineProps({
  modelValue: { type: String, default: null },
  labelledBy: { type: String, default: '' },
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

.run-as-seg {
  display: flex;
  width: 100%;
  padding: 2px;
  gap: 2px;
  border-radius: $border-radius-default;
  box-shadow: inset 0 0 0 1px $color-border-secondary;
}

.run-as-btn {
  flex: 1 1 0;
  min-width: 0;
  padding: 6px 12px;
  border-radius: $border-radius-sharp;
  border: 0;
  background: none;
  color: $color-text-secondary;
  font: inherit;
  font-size: 0.76rem;
  font-weight: 500;
  cursor: pointer;

  &:hover,
  &:focus-visible {
    color: $color-text-primary;
  }

  &:focus-visible {
    outline: 2px solid $color-brand-yellow;
    outline-offset: 1px;
  }

  &[aria-pressed='true'] {
    background: rgba($color-brand-yellow, 0.14);
    color: $color-brand-yellow;
    font-weight: 600;
  }
}
</style>
