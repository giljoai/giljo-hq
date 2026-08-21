<template>
  <div class="execution-mode-pills" :class="{ 'mode-locked': isExecutionModeLocked }">
    <span class="mode-label">Execution Mode:</span>
    <div class="mode-pill-group">
      <v-tooltip location="bottom">
        <template #activator="{ props: tooltipProps }">
          <button
            v-bind="tooltipProps"
            class="pill-btn pill-sm smooth-border"
            :class="{ active: executionPlatform === 'multi_terminal' }"
            :disabled="isExecutionModeLocked"
            data-testid="radio-multi-terminal"
            @click="!isExecutionModeLocked && $emit('change', 'multi_terminal')"
          >
            Multi-Terminal
          </button>
        </template>
        <span>One terminal per agent — you watch the fleet.</span>
      </v-tooltip>
      <v-tooltip location="bottom">
        <template #activator="{ props: tooltipProps }">
          <button
            v-bind="tooltipProps"
            class="pill-btn pill-sm smooth-border"
            :class="{ active: executionPlatform === 'subagent' }"
            :disabled="isExecutionModeLocked"
            data-testid="radio-subagent"
            @click="!isExecutionModeLocked && $emit('change', 'subagent')"
          >
            Subagent
          </button>
        </template>
        <span>
          One orchestrator session manages workers — its harness is auto-detected when recognized; otherwise a universal protocol is used.
        </span>
      </v-tooltip>
    </div>
    <v-tooltip location="bottom">
      <template #activator="{ props: tooltipProps }">
        <v-icon v-bind="tooltipProps" size="small" class="help-icon" aria-label="Execution mode help">mdi-help-circle-outline</v-icon>
      </template>
      <span>Multi-Terminal: manual, one terminal per agent. Subagent: automatic, one orchestrator session runs the whole team.</span>
    </v-tooltip>
    <v-icon v-if="isExecutionModeLocked" size="small" class="lock-icon" aria-label="Execution mode locked">mdi-lock</v-icon>
  </div>
</template>

<script setup>
defineProps({
  executionPlatform: {
    type: String,
    default: null,
  },
  isExecutionModeLocked: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['change'])
</script>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;
@use '@/styles/design-tokens.scss' as *;

.execution-mode-pills {
  display: flex;
  align-items: center;
  gap: 8px;

  &.mode-locked {
    opacity: 0.6;
  }

  .mode-label {
    font-weight: 500;
    color: white;
    font-size: 14px;
    margin-right: 4px;
  }

  .mode-pill-group {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .help-icon {
    color: rgba(var(--v-theme-on-surface), 0.5);
    cursor: help;
  }

  .lock-icon {
    color: rgba(var(--v-theme-on-surface), 0.5);
    margin-left: 4px;
  }
}

/* Shared pill button style — duplicated from ProjectTabs container because
   scoped styles do not cross component boundaries. */
.pill-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: $border-radius-pill;
  padding: 8px 18px;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  transition: $transition-all-fast;
  background: transparent;
  color: var(--text-muted);
  border: none;
  --smooth-border-color: rgba(var(--v-theme-on-surface), 0.15);

  &:hover:not(:disabled) {
    color: var(--text-secondary);
    --smooth-border-color: rgba(var(--v-theme-on-surface), 0.25);
  }

  &.active,
  &.active:hover {
    background: rgba($color-brand-yellow, 0.12);
    color: $color-brand-yellow;
    box-shadow: none;
  }

  &:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
}

.pill-sm {
  padding: 5px 14px;
  font-size: 0.73rem;
}

@media (max-width: 600px) {
  .execution-mode-pills .mode-pill-group {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }
}
</style>
