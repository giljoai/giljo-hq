<template>
  <div class="jb-toolbar" data-testid="jobs-board-toolbar">
    <div class="jb-filter-group jb-side-group" role="group" aria-label="Board side">
      <button
        type="button"
        class="jb-filter jb-side"
        :class="{ 'jb-filter--active': side === 'staging' }"
        :aria-pressed="side === 'staging'"
        data-testid="jobs-side-staging"
        @click="emit('select-side', 'staging')"
      >
        Staging <span class="jb-filter-n" :class="countClass(sideCounts.staging)">{{ sideCounts.staging }}</span>
      </button>
      <button
        type="button"
        class="jb-filter jb-side"
        :class="{ 'jb-filter--active': side === 'implementation' }"
        :aria-pressed="side === 'implementation'"
        data-testid="jobs-side-implementation"
        @click="emit('select-side', 'implementation')"
      >
        Implementation <span class="jb-filter-n" :class="countClass(sideCounts.implementation)">{{ sideCounts.implementation }}</span>
      </button>
    </div>
    <div class="jb-status-line" data-testid="jobs-status-counters">
      <span v-for="option in statusCounts" :key="option.value" :data-testid="`jobs-status-${option.value}`">
        {{ option.label }}
        <span class="jb-filter-n" :class="countClass(option.count, option.value === 'needs-decision')">
          {{ option.count }}
        </span>
      </span>
    </div>
    <div class="jb-density" data-testid="jobs-view-switch">
      <label class="jb-density-label" for="jobs-compact-switch" data-testid="jobs-view-label">Compact view</label>
      <v-switch
        id="jobs-compact-switch"
        :model-value="isCompact"
        color="primary"
        density="compact"
        hide-details
        aria-label="Compact view"
        data-testid="jobs-compact-switch"
        @update:model-value="onToggleCompact"
      />
    </div>
  </div>
</template>

<script setup>
import { BOARD_DENSITIES } from '@/composables/useBoardDensity'

defineProps({
  side: { type: String, required: true },
  sideCounts: { type: Object, required: true },
  statusCounts: { type: Array, required: true },
  isCompact: { type: Boolean, default: false },
})

const emit = defineEmits(['select-side', 'select-density'])

function countClass(count, hotWhenPositive = false) {
  if (!(count > 0)) return null
  return hotWhenPositive ? 'jb-filter-n--hot' : 'jb-filter-n--on'
}

function onToggleCompact(on) {
  emit('select-density', on ? BOARD_DENSITIES.COMPACT : BOARD_DENSITIES.DETAILED)
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 24px;
}

.jb-filter-group {
  display: flex;
  background: $color-container-background;
  border: 1px solid $color-border-secondary;
  border-radius: $border-radius-pill;
  padding: 3px;
}

.jb-filter {
  background: none;
  border: 0;
  color: $color-text-secondary;
  cursor: pointer;
  padding: 6px 15px;
  border-radius: $border-radius-pill;
  font-size: 0.8rem;
  font-family: inherit;
  display: flex;
  align-items: center;
  gap: 6px;

  &--active {
    background: rgba($color-brand-yellow, 0.14);
    color: $color-brand-yellow;
    font-weight: 600;

    .jb-filter-n {
      background: rgba($color-brand-yellow, 0.22);
    }
  }
}

.jb-filter-n {
  font-size: 0.68rem;
  background: rgba(255, 255, 255, 0.09);
  padding: 0 6px;
  border-radius: $border-radius-pill;

  &--on {
    background: rgba($color-brand-yellow, 0.15);
    color: $color-brand-yellow;
  }

  &--hot {
    background: rgba($color-status-warning, 0.25);
    color: $color-status-warning;
  }
}

.jb-status-line {
  display: flex;
  align-items: center;
  gap: 14px;
  color: $color-text-secondary;
  font-size: 0.8rem;
}

.jb-side-group {
  border-color: rgba($color-brand-yellow, 0.35);
}

.jb-side {
  font-weight: 600;
  padding: 7px 18px;
}

.jb-density {
  display: flex;
  align-items: center;
  gap: 8px;
}

.jb-density-label {
  font-size: 0.8rem;
  color: $color-text-secondary;
  cursor: pointer;
}

.jb-density :deep(.v-switch .v-selection-control) {
  min-height: auto;
}
</style>
