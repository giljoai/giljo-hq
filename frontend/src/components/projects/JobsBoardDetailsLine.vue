<template>
  <button
    type="button"
    class="jb-details-btn"
    :aria-expanded="open"
    data-testid="jb-details-btn"
    @click="emit('toggle')"
  >
    <v-icon size="16" class="jb-details-chev" :class="{ 'jb-details-chev--open': open }">mdi-chevron-right</v-icon>
    <span>Description and mission</span>
    <span class="jb-mpill" :class="`jb-mpill--${missionState}`" data-testid="jb-mission-state" :data-state="missionState">
      <template v-if="missionState === 'writing'">Writing mission<LiveDots /></template>
      <template v-else-if="missionState === 'written'">Mission written</template>
      <template v-else>No mission yet</template>
    </span>
  </button>
</template>

<script setup>
import LiveDots from './LiveDots.vue'

defineProps({
  open: { type: Boolean, default: false },
  missionState: { type: String, default: 'none' },
})

const emit = defineEmits(['toggle'])
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-details-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  background: none;
  border: 0;
  color: $color-text-secondary;
  font: inherit;
  font-size: 0.8rem;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  padding: 4px 6px 4px 2px;
  border-radius: $border-radius-sharp;
  margin: 0 0 10px;

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
  }
}

.jb-details-chev {
  flex: none;
  transition: transform 0.2s;

  &--open {
    transform: rotate(90deg);
  }
}

.jb-mpill {
  display: inline-flex;
  align-items: center;
  margin-left: auto;
  font-size: 0.67rem;
  font-weight: 600;
  padding: 2px 9px;
  border-radius: $border-radius-pill;
  color: $color-text-secondary;
  background: rgba($color-text-secondary, 0.15);

  &--writing {
    color: $color-status-waiting;
    background: rgba($color-status-waiting, 0.15);
  }

  &--written {
    color: $color-status-complete;
    background: rgba($color-status-complete, 0.15);
  }
}
</style>
