<template>
  <!-- FE-6174c: the project tab strip — two-row layout with non-clickable badge.
       The Review badge is a display-only status indicator; the "Review project"
       button lives in ProjectStatusBanner and routes through onReviewProjectClick
       in ProjectTabs.vue. Active tab highlighted; completed tabs show "COMPLETED";
       not-started tabs faded. Conditional layer only.
       Badge state machine (FE-9239 addendum) — read-only reference for P2/FE-9244:
       REVIEW > COMPLETED > WORKING > PLANNING > WAITING, see badgeState() below. -->
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
      <!-- Row 1: alias badge + truncated name -->
      <span class="chain-tab__row1">
        <span
          v-if="tab.taxonomyAlias"
          class="chain-tab__alias"
          :style="aliasStyle(tab)"
        >{{ tab.taxonomyAlias }}</span>
        <span class="chain-tab__name">{{ truncName(tab) }}</span>
      </span>

      <!-- Row 2: centred state badge (display-only, non-interactive) -->
      <span v-if="badgeState(tab)" class="chain-tab__row2">
        <span
          class="chain-tab__badge"
          :class="[`chain-tab__badge--${badgeState(tab)}`, { 'chain-tab__badge--pulse': badgeIsPulsing(tab) }]"
          aria-hidden="true"
        >{{ badgeLabel(tab) }}</span>
      </span>
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

function truncName(tab) {
  if (tab.name && tab.name.length > 15) return `${tab.name.slice(0, 15)}…`
  return tab.name || `Project ${tab.order + 1}`
}

/**
 * Returns the modifier key for the badge class.
 * Precedence: needsReview > isCompleted > isWorking (implementing) > isPlanning > waiting.
 * isWorking derives from the project's status field, NOT from chain position (isCurrent).
 * A staging/pending member that IS the chain head correctly shows PLANNING (while its
 * staging_status is 'staging'/'staged') or WAITING (not yet staged) until its
 * sub-orchestrator sets status to 'implementing'.
 * isPlanning (FE-9239) derives from Project.staging_status via useChainContext — true
 * while a chain member is actively being staged, so it reads distinctly from a
 * genuinely-queued member instead of both showing WAITING. staging_complete (mission
 * written, Implement lit, no workers yet) is DELIBERATELY excluded from isPlanning by
 * useChainContext today (falls through to WAITING here) — that is a deliberate
 * design-review call; to switch it to PLANNING, flip the fallback check in
 * useChainContext.js's `tabs` computed (the `stagingActive` derivation) to also
 * include 'staging_complete', no change needed in this file.
 * Always returns a non-null string so every pill renders a two-row layout.
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
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-height: 52px;
  min-width: 80px;
  border: none;
  background: transparent;
  border-radius: $border-radius-pill;
  padding: 7px 14px;
  font-size: 0.76rem;
  font-weight: 500;
  color: var(--text-muted);
  cursor: pointer;
  transition: $transition-all-fast;
  --smooth-border-color: rgba(var(--v-theme-on-surface), 0.15);
  max-width: 220px;

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

  &__row1 {
    display: flex;
    align-items: center;
    gap: 6px;
    max-width: 100%;
  }

  &__row2 {
    display: flex;
    justify-content: center;
    width: 100%;
  }

  &__alias {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6rem;
    font-weight: 700;
    color: #fff;
    border-radius: $border-radius-sharp;
    padding: 1px 6px;
    flex-shrink: 0;
  }

  &__name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  &__badge {
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-radius: $border-radius-pill;
    padding: 1px 7px;
    line-height: 1.4;

    &--review {
      color: $color-status-review;
      background: rgba($color-status-review, 0.15);
    }

    &--completed {
      color: $color-status-complete;
      background: rgba($color-status-complete, 0.15);
    }

    &--working {
      color: $color-status-working;
      background: rgba($color-status-working, 0.15);
    }

    &--planning {
      // FE-9239: distinct from WAITING (amber) and WORKING (white) — a chain
      // member actively being staged, not yet a genuinely-queued/working one.
      color: $color-status-sleeping;
      background: rgba($color-status-sleeping, 0.15);
    }

    &--waiting {
      color: $color-status-waiting;
      background: rgba($color-status-waiting, 0.15);
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
