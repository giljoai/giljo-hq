<template>
  <v-btn
    :color="active ? 'warning' : undefined"
    :variant="active ? 'flat' : 'outlined'"
    :icon="active ? 'mdi-hand-back-right' : 'mdi-hand-back-right-outline'"
    :size="size === 'sm' ? 'x-small' : 'small'"
    :disabled="disabled || !active"
    :aria-pressed="active ? 'true' : 'false'"
    :title="label"
    :aria-label="label"
    class="mark-handled-toggle"
    :class="{
      'mark-handled-toggle--sm': size === 'sm',
      'mark-handled-toggle--pulse': shouldPulse,
    }"
    @click="$emit('click')"
  />
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  active: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  size: { type: String, default: 'default' },
  pulse: { type: Boolean, default: false },
})

defineEmits(['click'])

const reducedMotion = ref(
  typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches,
)

const shouldPulse = computed(() => props.pulse && props.active && !reducedMotion.value)

const label = computed(() =>
  props.active
    ? "Mark handled — clears 'waiting on you'. The thread stays open, nothing is posted."
    : 'Nothing is waiting on you in this thread',
)
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.mark-handled-toggle {
  flex-shrink: 0;

  // The OFF state is inert by design, not broken. Vuetify's disabled treatment reads as
  // "unavailable"; this is "nothing to do", so it keeps a legible outline instead of
  // fading toward the background.
  &:disabled {
    opacity: 0.55;
  }

  &--pulse {
    animation: mark-handled-pulse 1.8s ease-in-out infinite;
  }
}

// Yellow because it is the handover colour, and derived from the same brand token the
// `warning` fill uses — no second hex, and it stays in step if the token moves.
@keyframes mark-handled-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba($color-brand-yellow, 0.55); }
  70% { box-shadow: 0 0 0 7px rgba($color-brand-yellow, 0); }
}

// The real protection. The class gate above exists to make this assertable; this is what
// honours the operator's OS preference in the product.
@media (prefers-reduced-motion: reduce) {
  .mark-handled-toggle--pulse {
    animation: none;
  }
}
</style>
