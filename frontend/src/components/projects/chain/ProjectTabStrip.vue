<template>
  <div class="project-tab-strip" role="tablist" data-testid="project-tab-strip">
    <button
      v-for="tab in tabs"
      :key="tab.projectId"
      type="button"
      role="tab"
      class="chain-tab smooth-border"
      :class="{
        'chain-tab--active': tab.projectId === activePid,
        'chain-tab--current': tab.isCurrent,
        'chain-tab--completed': tab.isCompleted,
        'chain-tab--faded': !tab.isStarted && !tab.isCurrent && tab.projectId !== activePid,
      }"
      :aria-selected="tab.projectId === activePid"
      :data-testid="`chain-tab-${tab.order}`"
      :title="tab.name"
      @click="emit('select', tab.projectId)"
    >
      <span
        v-if="tab.taxonomyAlias"
        class="chain-tab__alias"
        :style="aliasStyle(tab)"
      >{{ tab.taxonomyAlias }}</span>
      <span
        v-if="badgeState(tab)"
        class="chain-tab__badge"
        :class="[`chain-tab__badge--${badgeState(tab)}`, { 'chain-tab__badge--pulse': badgeIsPulsing(tab) }]"
      >{{ badgeLabel(tab) }}</span>
    </button>
  </div>
</template>

<script setup>
import { resolveTaxonomyColor } from '@/utils/taxonomyBadge'

defineProps({
  tabs: {
    type: Array,
    required: true,
  },
  activePid: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['select'])

function aliasStyle(tab) {
  const color = resolveTaxonomyColor({
    abbreviation: tab.taxonomy?.abbreviation,
    alias: tab.taxonomyAlias,
    color: tab.taxonomy?.color,
  })
  return { backgroundColor: color }
}

function badgeState(tab) {
  if (tab.needsReview) return 'review'
  if (tab.isCompleted) return 'completed'
  if (tab.isWorking) return 'working'
  if (tab.isPlanning) return 'planning'
  return 'waiting'
}

function badgeLabel(tab) {
  const state = badgeState(tab)
  if (state === 'review') return 'REVIEW'
  if (state === 'completed') return 'COMPLETED'
  if (state === 'working') return 'WORKING'
  if (state === 'planning') return 'PLANNING'
  if (state === 'waiting') return 'WAITING'
  return ''
}

function badgeIsPulsing(tab) {
  const state = badgeState(tab)
  return state === 'working' || state === 'review'
}
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;
@use '@/styles/variables' as v;

.project-tab-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  flex-shrink: 0;
}

.chain-tab {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 8px;
  border: none;
  background: transparent;
  border-radius: $border-radius-default;
  padding: 6px 9px;
  font-weight: 500;
  color: var(--text-muted);
  cursor: pointer;
  transition: $transition-all-fast;
  --smooth-border-color: rgba(var(--v-theme-on-surface), 0.15);

  &:hover {
    color: var(--text-secondary);
    --smooth-border-color: rgba(var(--v-theme-on-surface), 0.25);
  }

  &--active,
  &--active:hover {
    background: rgba($color-brand-yellow, 0.12);
    color: $color-brand-yellow;
    --smooth-border-color: rgba(#{$color-brand-yellow}, 0.4);
  }

  &--faded {
    opacity: 0.5;
  }

  &--completed {
    color: $color-status-complete;
  }

  &__alias {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.62rem;
    font-weight: 700;
    color: $color-background-primary;
    border-radius: $border-radius-sharp;
    padding: 2px 6px;
    flex-shrink: 0;
  }

  &__badge {
    font-size: 0.56rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;

    &--review {
      color: $color-status-review;
    }

    &--completed {
      color: $color-status-complete;
    }

    &--working {
      color: $color-status-working;
    }

    &--planning {
      // FE-9239/FE-9493: distinct from WAITING (amber) and WORKING (white) — this
      // project's sub-orchestrator has started working it, no worker agent yet.
      color: $color-status-sleeping;
    }

    &--waiting {
      color: $color-status-waiting;
    }

    &--pulse {
      animation: chain-tab-pulse 1.4s ease-in-out infinite;
    }
  }
}

@keyframes chain-tab-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}
</style>
