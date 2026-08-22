<template>
  <!-- FE-6174c: the project tab strip — single-row card with non-clickable badge.
       The Review badge is a display-only status indicator; the "Review project"
       button lives in ProjectStatusBanner and routes through onReviewProjectClick
       in ProjectTabs.vue. Active tab highlighted; completed tabs show "COMPLETED";
       not-started tabs faded. Conditional layer only.
       Badge state machine (FE-9239/FE-9493 addendum) — read-only reference for
       P2/FE-9244: REVIEW > COMPLETED > WORKING > PLANNING > WAITING, see
       badgeState() below. -->
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
/**
 * ProjectTabStrip — FE-6174c
 * Presentational tab strip for the chain /jobs variant. Emits `select(pid)` to
 * switch the viewed project. Badge states (review/working/completed) are display-only;
 * the actual Review action lives in ProjectStatusBanner → onReviewProjectClick.
 * Colors come from the taxonomy token (no hardcoded hex).
 */
import { resolveTaxonomyColor } from '@/utils/taxonomyBadge'

defineProps({
  // Ordered tab descriptors from useChainContext.
  tabs: {
    type: Array,
    required: true,
  },
  // The currently viewed project (route param).
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

/**
 * Returns the modifier key for the badge class.
 * Precedence: needsReview > isCompleted > isWorking (implementing) > isPlanning > waiting.
 * isWorking derives from the project's status field, NOT from chain position (isCurrent).
 * isPlanning / isWorking (FE-9493) are a PURE read of the backend's per-member run
 * status via useChainContext — WAITING means the conductor has not started this
 * member (status 'pending'/'staged'); PLANNING means its sub-orchestrator has
 * started working it but no worker agent has spawned yet (status 'planning');
 * WORKING means the first spawned worker has started (status 'implementing').
 * A card click NAVIGATES ONLY — it never writes status, so an unvisited member and
 * a visited-but-idle member read identically (see useChainContext.js's `tabs`).
 * Always returns a non-null string so every card always renders a badge.
 */
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

/** Returns true when the badge should pulse (working or review states). */
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
