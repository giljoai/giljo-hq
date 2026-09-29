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
        Staging <span class="jb-filter-n">{{ sideCounts.staging }}</span>
      </button>
      <button
        type="button"
        class="jb-filter jb-side"
        :class="{ 'jb-filter--active': side === 'implementation' }"
        :aria-pressed="side === 'implementation'"
        data-testid="jobs-side-implementation"
        @click="emit('select-side', 'implementation')"
      >
        Implementation <span class="jb-filter-n">{{ sideCounts.implementation }}</span>
      </button>
    </div>
    <div class="jb-filter-group" role="group" aria-label="Filter by state">
      <button
        v-for="option in filterOptions"
        :key="option.value"
        type="button"
        class="jb-filter"
        :class="{ 'jb-filter--active': filter === option.value }"
        :data-testid="`jobs-filter-${option.value}`"
        @click="emit('select-filter', option.value)"
      >
        {{ option.label }}
        <span class="jb-filter-n" :class="{ 'jb-filter-n--hot': option.value === 'needs-input' && option.count > 0 }">
          {{ option.count }}
        </span>
      </button>
    </div>
    <div class="jb-filter-group jb-density" role="group" aria-label="View" data-testid="jobs-view-switch">
      <span class="jb-density-label" data-testid="jobs-view-label">View</span>
      <button
        type="button"
        class="jb-filter"
        :class="{ 'jb-filter--active': !isCompact }"
        :aria-pressed="!isCompact"
        data-testid="jobs-density-detailed"
        @click="emit('select-density', BOARD_DENSITIES.DETAILED)"
      >
        Detailed
      </button>
      <button
        type="button"
        class="jb-filter"
        :class="{ 'jb-filter--active': isCompact }"
        :aria-pressed="isCompact"
        data-testid="jobs-density-compact"
        @click="emit('select-density', BOARD_DENSITIES.COMPACT)"
      >
        Compact
      </button>
    </div>
    <span class="jb-count-note">{{ countNote }}</span>
  </div>
</template>

<script setup>
import { BOARD_DENSITIES } from '@/composables/useBoardDensity'

defineProps({
  side: { type: String, required: true },
  sideCounts: { type: Object, required: true },
  filter: { type: String, required: true },
  filterOptions: { type: Array, required: true },
  isCompact: { type: Boolean, default: false },
  countNote: { type: String, default: '' },
})

const emit = defineEmits(['select-side', 'select-filter', 'select-density'])
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

  &--hot {
    background: rgba($color-status-warning, 0.25);
    color: $color-status-warning;
  }
}

.jb-side-group {
  border-color: rgba($color-brand-yellow, 0.35);
}

.jb-side {
  font-weight: 600;
  padding: 7px 18px;
}

.jb-density {
  align-items: center;
}

.jb-density-label {
  font-size: 0.62rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: $color-text-secondary;
  padding: 0 4px 0 12px;
}

.jb-count-note {
  color: $color-text-secondary;
  font-size: 0.8rem;
  margin-left: auto;
}
</style>
