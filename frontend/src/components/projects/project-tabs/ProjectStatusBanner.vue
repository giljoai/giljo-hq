<template>
  <!-- State A: Project is done -> status banner -->
  <div v-if="projectDoneStatus" class="action-buttons-row action-buttons-row--stacked">
    <v-chip
      :color="projectDoneStatus === 'completed' ? 'success' : projectDoneStatus === 'terminated' ? 'warning' : 'grey'"
      variant="flat"
      size="large"
      :prepend-icon="projectDoneStatus === 'cancelled' ? 'mdi-cancel' : 'mdi-check-circle'"
      data-testid="project-done-banner"
    >
      {{ projectDoneStatus === 'completed' ? 'Project Completed and Closed'
         : projectDoneStatus === 'terminated' ? 'Project Terminated'
         : 'Project Cancelled' }}
    </v-chip>
    <!-- FE-9191: review a completed project's closeout record from the pill.
         Completed only — the closeout modal's Close is an acknowledge there
         (skips the archive write); terminated/cancelled keep pill-only so the
         archive path can never overwrite those statuses. -->
    <v-btn
      v-if="projectDoneStatus === 'completed' && !isChainMember"
      class="closeout-btn"
      color="yellow-darken-2"
      variant="flat"
      prepend-icon="mdi-eye"
      data-testid="review-completed-btn"
      @click="$emit('open-closeout-modal')"
    >
      Review project
    </v-btn>
  </div>

  <!-- State A2: Orchestrator awaiting_user — HITL decision required. -->
  <div
    v-else-if="orchestratorCloseoutBlocked"
    class="action-buttons-row"
  >
    <button
      type="button"
      class="closeout-decision-banner closeout-decision-banner--clickable smooth-border"
      data-testid="closeout-decision-banner"
      aria-label="Open decision dialog"
      @click="$emit('open-decision-modal')"
    >
      <v-icon icon="mdi-clipboard-check-outline" size="20" class="closeout-decision-icon" />
      <div class="closeout-decision-content">
        <span class="closeout-decision-title">Decision Required</span>
        <span class="closeout-decision-desc">
          Check in with the orchestrator in chat, then click here to decide.
        </span>
      </div>
      <v-icon icon="mdi-chevron-right" size="20" class="closeout-decision-chevron" />
    </button>
  </div>

  <!-- State A3: Just-decided — orchestrator gate cleared, nudge prompt. -->
  <div
    v-else-if="showOrchUnlockedBanner"
    class="action-buttons-row"
  >
    <div
      class="closeout-decision-banner closeout-decision-banner--unlocked smooth-border"
      data-testid="orchestrator-unlocked-banner"
      role="status"
      aria-live="polite"
    >
      <v-icon icon="mdi-check-circle-outline" size="20" class="closeout-decision-icon closeout-decision-icon--ok" />
      <div class="closeout-decision-content">
        <span class="closeout-decision-title">Orchestrator unlocked</span>
        <span class="closeout-decision-desc">
          Tell the orchestrator to read its message and proceed.
        </span>
      </div>
      <v-btn
        icon
        variant="text"
        size="small"
        class="closeout-decision-dismiss"
        aria-label="Dismiss"
        data-testid="orchestrator-unlocked-dismiss"
        @click="$emit('dismiss-orch-unlocked')"
      >
        <v-icon icon="mdi-close" size="18" />
      </v-btn>
    </div>
  </div>

  <!-- State B: All agents terminal, project NOT done -> closeout button -->
  <div v-else-if="showCloseoutButton" class="action-buttons-row">
    <v-btn
      class="closeout-btn"
      color="yellow-darken-2"
      variant="flat"
      prepend-icon="mdi-check-circle"
      data-testid="close-project-btn"
      @click="$emit('open-closeout-modal')"
    >
      Review project
    </v-btn>
  </div>

  <!-- State B2: All agents terminal, waiting for 360 memory -->
  <div v-else-if="showMemoryPending" class="action-buttons-row">
    <v-chip color="info" variant="tonal" size="large" data-testid="memory-pending-chip">
      <template #prepend>
        <v-progress-circular indeterminate size="16" width="2" />
      </template>
      Saving project memory...
    </v-chip>
  </div>

  <!-- State B3: Memory poll timed out or errored -->
  <div
    v-else-if="allJobsTerminal && (memoryPollTimedOut || memoryPollError)"
    class="action-buttons-row"
  >
    <v-chip
      color="warning"
      variant="tonal"
      size="large"
      data-testid="memory-poll-error-chip"
    >
      <template #prepend>
        <v-icon icon="mdi-alert" size="18" />
      </template>
      <span>Closeout may have failed &mdash; check agent terminal for errors</span>
    </v-chip>
    <v-btn
      variant="tonal"
      color="warning"
      size="small"
      prepend-icon="mdi-refresh"
      class="ml-2"
      data-testid="memory-poll-retry-btn"
      :aria-label="'Retry memory poll'"
      @click="$emit('retry-memory-poll')"
    >
      Retry
    </v-btn>
    <v-btn
      variant="text"
      size="small"
      class="ml-1 text-muted-a11y"
      data-testid="memory-poll-dismiss-btn"
      :aria-label="'Dismiss error'"
      @click="$emit('dismiss-memory-poll-error')"
    >
      Dismiss
    </v-btn>
  </div>
</template>

<script setup>
defineProps({
  projectDoneStatus: {
    type: String,
    default: null,
  },
  orchestratorCloseoutBlocked: {
    type: Boolean,
    default: false,
  },
  showOrchUnlockedBanner: {
    type: Boolean,
    default: false,
  },
  showCloseoutButton: {
    type: Boolean,
    default: false,
  },
  showMemoryPending: {
    type: Boolean,
    default: false,
  },
  allJobsTerminal: {
    type: Boolean,
    default: false,
  },
  memoryPollTimedOut: {
    type: Boolean,
    default: false,
  },
  memoryPollError: {
    type: Boolean,
    default: false,
  },
  // FE-9244: chain member context — hides the "Review project" button once a
  // chain-completed project's pill is showing (buildChainAwareProjectDoneStatus
  // in reviewDispatch.js already only returns 'completed' post-review, so the
  // pill itself is correct; this just suppresses the redundant re-review CTA).
  isChainMember: {
    type: Boolean,
    default: false,
  },
})

defineEmits([
  'open-decision-modal',
  'dismiss-orch-unlocked',
  'open-closeout-modal',
  'retry-memory-poll',
  'dismiss-memory-poll-error',
])
</script>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;
@use '@/styles/design-tokens.scss' as *;

/* Action buttons row (centered) */
.action-buttons-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-shrink: 0;
}

/* FE-9244: State A only — stack the done pill above the Review button
   instead of side-by-side. Scoped to its own modifier class so the other
   5 banner states sharing .action-buttons-row are unaffected. */
.action-buttons-row--stacked {
  flex-direction: column;
  gap: 8px;
}

.closeout-btn {
  text-transform: none;
  font-weight: 600;
  letter-spacing: 0.5px;

  &:hover {
    background: rgb(var(--v-theme-highlight-hover));
  }
}

/* HITL Closeout banners */
.closeout-decision-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  border-radius: $border-radius-md;
  background: rgba($color-status-warning, 0.10);
  --smooth-border-color: rgba($color-status-warning, 0.30);
}

.closeout-decision-banner--clickable {
  max-width: 560px;
  cursor: pointer;
  text-align: left;
  color: inherit;
  font: inherit;
  transition: background 120ms ease, filter 120ms ease;
}

.closeout-decision-banner--unlocked {
  max-width: 560px;
  background: rgba($color-status-success, 0.10);
  --smooth-border-color: rgba($color-status-success, 0.30);

  .closeout-decision-icon--ok {
    color: $color-status-success;
  }
}

.closeout-decision-dismiss {
  margin-left: auto;
  flex-shrink: 0;
}

.closeout-decision-banner--clickable:hover,
.closeout-decision-banner--clickable:focus-visible {
  background: rgba($color-status-warning, 0.18);
  filter: brightness(1.05);
}

.closeout-decision-banner--clickable:focus-visible {
  outline: 2px solid $color-status-warning;
  outline-offset: 2px;
}

.closeout-decision-icon {
  color: $color-status-warning;
  flex-shrink: 0;
}

.closeout-decision-chevron {
  color: $color-status-warning;
  margin-left: auto;
  flex-shrink: 0;
}

.closeout-decision-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.closeout-decision-title {
  font-weight: 600;
  font-size: 0.875rem;
  color: $color-status-warning;
}

.closeout-decision-desc {
  font-size: 0.78rem;
  color: var(--text-muted);
}
</style>
