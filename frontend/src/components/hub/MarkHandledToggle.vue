<!--
  MarkHandledToggle.vue — FE-9439

  The square hand toggle that clears "waiting on you". ONE control, rendered in two
  places: beside the thread search bar (small, persistent — a status indicator that is
  also the action) and in the composer (standard size, pulsing while it is the operator's
  turn). Behaviour lives in useMarkHandled.js; this file is looks and accessibility only.

  The shape is not new. It is the "Show archived" toggle from TasksView.vue:74-83, prop
  for prop — filled `warning` when on, outlined when off, filled/outline icon pair,
  labels in title/aria. The operator pointed at that control in his reference screenshots
  and asked for this one to match it, so matching it exactly is the requirement rather
  than a convenience.

  ON means the baton points at you. OFF means it does not. Clearing is ONE-WAY by design
  (there is no "un-handle" — you cannot hand yourself a baton back), so the OFF state is
  inert and says so: it is disabled, and its tooltip explains rather than going silent.

  Colour never carries the state alone — `aria-pressed` does, per WCAG. A screen reader
  gets the same two states the eye does.

  No `data-testid` is baked in: each instance passes its own, so a spec can address the
  search-bar one and the composer one separately. `.mark-handled-toggle` is the class
  that says "these two are the same control".
-->
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
  // Whether the baton currently points at the operator. Drives fill, icon, and
  // aria-pressed together, so the three cannot disagree.
  active: { type: Boolean, default: false },
  // In flight. Separate from `active` because a clear that has not landed yet is not
  // the same state as a turn that was never yours.
  disabled: { type: Boolean, default: false },
  // 'sm' for the search-bar row, which has an existing design height this must sit
  // inside rather than stretch. 'default' everywhere else.
  size: { type: String, default: 'default' },
  // Ask for the attention pulse. Honoured only while `active` and only when the
  // operator has not asked for reduced motion — see below.
  pulse: { type: Boolean, default: false },
})

defineEmits(['click'])

/**
 * Reduced motion, gated by CLASS as well as by media query.
 *
 * The SCSS below carries the real `@media (prefers-reduced-motion: reduce)` rule, which
 * is what actually protects the operator. This ref exists so the behaviour is also
 * assertable: vitest does not compile the SCSS in this tree, so a media-query-only pulse
 * would be untestable and FE-9439's DoD requires it proven. Same dual gate as
 * TutorialOverlay.vue:149-153, which solved this exact problem first.
 *
 * Read once per mount rather than watched: the operator changing an OS accessibility
 * preference mid-thread is not a case worth a listener, and the media query still
 * catches it on the next render.
 */
const reducedMotion = ref(
  typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches,
)

// The pulse is an attention aid. It never gates operating the control — the button is
// identical, clickable and correctly labelled with the animation suppressed.
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
