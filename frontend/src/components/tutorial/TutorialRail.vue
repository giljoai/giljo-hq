<template>
  <aside class="tutorial-rail">
    <div class="rail-top">
      <img src="/icons/Giljo_YW_Face.svg" alt="" class="rail-logo" />
      <span class="rail-kicker">THE TOUR</span>
    </div>

    <div class="rail-stops">
      <div
        v-for="(label, i) in TUTORIAL_STOPS"
        :key="label"
        :class="[
          'rail-stop',
          {
            'rail-stop--active': i + 1 === activeStop,
            'rail-stop--done': i + 1 < activeStop,
          },
        ]"
        :data-testid="`tutorial-rail-stop-${i + 1}`"
        role="button"
        tabindex="0"
        :aria-current="i + 1 === activeStop ? 'step' : undefined"
        @click="$emit('go', i + 1)"
        @keydown.enter.prevent="$emit('go', i + 1)"
        @keydown.space.prevent="$emit('go', i + 1)"
      >
        <span class="rail-dot">
          <v-icon v-if="i + 1 < activeStop" size="12">mdi-check</v-icon>
          <v-icon v-else size="12">mdi-circle-small</v-icon>
        </span>
        <span class="rail-label">{{ label }}</span>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { TUTORIAL_STOPS } from '@/composables/useTutorialState'

defineProps({
  activeStop: {
    type: Number,
    required: true,
  },
})

defineEmits(['go'])
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.tutorial-rail {
  width: 230px;
  flex-shrink: 0;
  background: $color-background-tertiary;
  box-shadow: inset -1px 0 0 rgba(255, 255, 255, 0.08);
  padding: 26px 20px;
  display: flex;
  flex-direction: column;
}

.rail-top {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 26px;
}

.rail-logo {
  height: 22px;
}

.rail-kicker {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.16em;
  color: var(--text-muted);
}

.rail-stops {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}

.rail-stop {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px;
  border-radius: 10px;
  cursor: pointer;

  &:hover {
    background: rgba(255, 255, 255, 0.05);
  }

  &:focus-visible {
    outline: 2px solid rgba($color-brand-yellow, 0.55);
    outline-offset: 2px;
  }
}

.rail-stop--active {
  background: rgba($color-brand-yellow, 0.08);
}

.rail-dot {
  width: 22px;
  height: 22px;
  border-radius: $border-radius-pill;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-muted);
}

.rail-stop--active .rail-dot {
  // Active rail dot: brand ramp per the gradient-rail spec stops.
  background: linear-gradient(135deg, $gradient-brand-end, $gradient-brand-start);
  color: $color-on-brand-ink;
  box-shadow: 0 0 0 3px rgba($color-brand-yellow, 0.18);
}

.rail-stop--done .rail-dot {
  background: rgba($color-agent-researcher, 0.15);
  color: $color-agent-researcher;
}

.rail-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
}

.rail-stop--active .rail-label {
  color: $color-text-primary;
}

.rail-stop--done .rail-label {
  color: var(--text-secondary);
}
</style>
