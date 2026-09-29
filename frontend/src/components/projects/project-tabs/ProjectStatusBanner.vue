<template>
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

  <div v-else-if="showCloseoutButton" class="action-buttons-row">
    <v-chip
      color="info"
      variant="tonal"
      size="large"
      prepend-icon="mdi-clipboard-text-clock-outline"
      data-testid="ready-for-review-chip"
    >
      Ready for review
    </v-chip>
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

  <div v-else-if="showMemoryPending" class="action-buttons-row">
    <v-chip color="info" variant="tonal" size="large" data-testid="memory-pending-chip">
      <template #prepend>
        <v-progress-circular indeterminate size="16" width="2" />
      </template>
      Saving project memory...
    </v-chip>
  </div>

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
        <v-icon icon="mdi-alert" size="18" class="mr-1" />
      </template>
      <span>The agents stopped without writing a closeout</span>
    </v-chip>
    <v-btn
      class="closeout-btn"
      color="yellow-darken-2"
      variant="flat"
      prepend-icon="mdi-clipboard-check-outline"
      data-testid="close-without-summary-btn"
      @click="openCloseDialog"
    >Close without agent summary</v-btn>
    <v-btn
      variant="tonal"
      color="warning"
      size="small"
      prepend-icon="mdi-refresh"
      data-testid="memory-poll-retry-btn"
      aria-label="Check again for the agent closeout"
      @click="$emit('retry-memory-poll')"
    >
      Retry
    </v-btn>

    <v-dialog v-model="closeDialogOpen" max-width="520">
      <v-card class="smooth-border" data-testid="close-without-summary-dialog">
        <div class="dlg-header dlg-header--warning">
          <v-icon class="dlg-icon">mdi-clipboard-check-outline</v-icon>
          <span class="dlg-title">Close without agent summary</span>
          <v-btn icon variant="text" class="dlg-close" aria-label="Close dialog" @click="closeDialogOpen = false">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </div>
        <v-card-text class="pt-6">
          <p class="close-dialog-text">
            The agents on this project stopped without writing their closeout. This saves a short
            closeout to project memory so you can review and archive the project as usual.
          </p>
          <v-textarea
            v-model="closeReason"
            label="Note for project memory (optional)"
            variant="outlined"
            rows="2"
            auto-grow
            counter="500"
            maxlength="500"
            hide-details="auto"
            data-testid="close-without-summary-reason"
          />
        </v-card-text>
        <div class="dlg-footer">
          <v-spacer />
          <v-btn variant="text" @click="closeDialogOpen = false">Cancel</v-btn>
          <v-btn
            color="yellow-darken-2"
            variant="flat"
            :loading="closingWithoutSummary"
            data-testid="close-without-summary-confirm"
            @click="confirmClose"
          >Save closeout</v-btn>
        </div>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { ref } from 'vue'

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
  isChainMember: {
    type: Boolean,
    default: false,
  },
  closingWithoutSummary: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits([
  'open-decision-modal',
  'dismiss-orch-unlocked',
  'open-closeout-modal',
  'retry-memory-poll',
  'close-without-summary',
])

const closeDialogOpen = ref(false)
const closeReason = ref('')

function openCloseDialog() {
  closeReason.value = ''
  closeDialogOpen.value = true
}

function confirmClose() {
  emit('close-without-summary', closeReason.value)
  closeDialogOpen.value = false
}
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

.close-dialog-text {
  margin-bottom: 16px;
  color: var(--text-secondary);
}

.closeout-decision-desc {
  font-size: 0.78rem;
  color: var(--text-muted);
}
</style>
