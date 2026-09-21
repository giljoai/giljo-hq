<template>
  <div class="chain-mode-bar" data-testid="chain-mode-bar">
    <span class="chain-mode-bar__counter" data-testid="chain-counter">
      {{ counter.n }}/{{ counter.m }}
    </span>
    <span class="chain-mode-bar__indicator" data-testid="chain-mode-indicator">
      <v-icon size="14" class="chain-mode-bar__icon">mdi-vector-link</v-icon>
      Multi project mode
    </span>
    <span v-if="mode" class="chain-mode-bar__mode" data-testid="chain-mode-readonly">
      <span class="chain-mode-bar__mode-key">Execution mode</span>
      <span class="chain-mode-bar__mode-val">{{ mode }}</span>
      <v-icon size="13" class="chain-mode-bar__mode-lock">mdi-lock-outline</v-icon>
    </span>
  </div>
</template>

<script setup>
defineProps({
  counter: {
    type: Object,
    required: true,
    validator: (v) => v && typeof v.n === 'number' && typeof v.m === 'number',
  },
  mode: {
    type: String,
    default: '',
  },
})
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

.chain-mode-bar {
  display: inline-flex;
  align-items: center;
  gap: 10px;

  &__counter {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.82rem;
    font-weight: 700;
    color: $color-brand-yellow;
    background: rgba($color-brand-yellow, 0.12);
    border-radius: $border-radius-pill;
    padding: 2px 10px;
  }

  &__indicator {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.62rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: $color-text-muted;
  }

  &__icon {
    color: $color-brand-yellow;
  }

  &__mode {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  &__mode-key {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.62rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: $color-text-muted;
  }

  &__mode-val {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    color: $color-text-secondary;
  }

  &__mode-lock {
    color: $color-text-muted;
  }
}
</style>
