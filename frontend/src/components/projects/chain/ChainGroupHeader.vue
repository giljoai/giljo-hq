<template>
  <header class="cgh" data-testid="chain-group-header">
    <div class="cgh-top">
      <v-icon size="20" class="cgh-icon" aria-hidden="true">mdi-link-variant</v-icon>
      <h2 class="cgh-name" data-testid="chain-group-name">{{ chainCtx.name }}</h2>
      <span class="cgh-counter" data-testid="chain-group-counter">
        Step {{ chainCtx.counter.n }} of {{ chainCtx.counter.m }}
      </span>
      <span class="cgh-spacer" />
      <RunAsSwitch
        v-if="!chainCtx.locked && controls.chainScreenControls.showModeSelector"
        :model-value="chainCtx.run.execution_mode || null"
        data-testid="chain-group-run-as"
        @change="controls.patchRunMode"
      />
      <span v-else-if="modeLabel" class="cgh-mode-tag" data-testid="chain-group-mode-tag">
        <v-icon size="12" aria-hidden="true">mdi-lock</v-icon>
        {{ modeLabel }}
      </span>
    </div>

    <ChainMissionWindow :mission="chainCtx.chainMission" class="cgh-goal" />

    <div class="cgh-actions">
      <ChainStagingActions
        v-if="controls.chainScreenControls.showStageButton"
        :stage-text="controls.chainStageText"
        :stage-title="controls.chainStageTitle"
        :stage-disabled="controls.chainStageDisabled"
        :staging="controls.chainStaging"
        :implement-ready="controls.chainImplementReady"
        @stage="controls.handleChainStage"
        @implement="controls.handleChainImplement"
      />
      <button
        v-if="controls.showCopyMasterPrompt"
        type="button"
        class="cgh-link"
        data-testid="chain-group-copy-master"
        @click="controls.copyMasterPrompt"
      >
        Copy master prompt
      </button>
      <span class="cgh-spacer" />
      <ChainStopControl
        v-if="controls.chainScreenControls.showStopChain"
        :run="chainCtx.run"
        :model-value="controls.showChainStopConfirm"
        :stopping="controls.chainStopping"
        @open="controls.openChainStopConfirm"
        @confirm="controls.handleChainStop"
        @cancel="controls.cancelChainStop"
      />
      <v-btn
        variant="text"
        size="small"
        class="cgh-deactivate"
        :loading="controls.deactivating"
        data-testid="chain-group-deactivate"
        @click="controls.openDeactivateConfirm"
      >
        Deactivate chain
      </v-btn>
    </div>

    <BaseDialog
      :model-value="controls.showDeactivateConfirm"
      type="danger"
      title="Deactivate chain?"
      confirm-label="Deactivate chain"
      size="sm"
      :loading="controls.deactivating"
      @confirm="controls.handleChainDeactivate"
      @cancel="controls.cancelDeactivate"
      @update:model-value="(open) => !open && controls.cancelDeactivate()"
    >
      <p class="mb-3">
        This returns all {{ memberCount }} linked projects to their <strong>original state</strong>
        and deletes {{ agentCount }} {{ agentCount === 1 ? 'agent' : 'agents' }} and their jobs.
      </p>
      <v-alert type="warning" variant="tonal" density="compact">
        Staging and missions are cleared. <strong>No audit log is kept</strong>; to end a running chain
        and keep its work, use <strong>Stop chain</strong> instead. This cannot be undone.
      </v-alert>
    </BaseDialog>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { isSubagentExecutionMode } from '@/composables/useExecutionMode'
import BaseDialog from '@/components/common/BaseDialog.vue'
import RunAsSwitch from '@/components/projects/RunAsSwitch.vue'
import ChainMissionWindow from './ChainMissionWindow.vue'
import ChainStagingActions from './ChainStagingActions.vue'
import ChainStopControl from './ChainStopControl.vue'

const props = defineProps({
  chainCtx: { type: Object, required: true },
  controls: { type: Object, required: true },
  agentCount: { type: Number, default: 0 },
})

const memberCount = computed(() => props.chainCtx.counter.m)

const modeLabel = computed(() => {
  const mode = props.chainCtx.run.execution_mode
  if (!mode) return ''
  return isSubagentExecutionMode(mode) ? 'Subagent' : 'Multi-Terminal'
})
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

.cgh-top {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.cgh-icon {
  color: $color-brand-yellow;
}

.cgh-name {
  font-size: 1.05rem;
  font-weight: 600;
  margin: 0;
  color: $color-text-primary;
}

.cgh-counter {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  font-weight: 700;
  color: $color-brand-yellow;
  background: rgba($color-brand-yellow, 0.12);
  border-radius: $border-radius-pill;
  padding: 2px 10px;
}

.cgh-spacer {
  flex: 1;
}

.cgh-mode-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.75rem;
  color: $color-text-secondary;
  background: $elevation-raised;
  border-radius: $border-radius-pill;
  padding: 3px 10px;
}

.cgh-goal {
  margin-bottom: 12px;
}

.cgh-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.cgh-link {
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  font-size: 0.8rem;
  color: $color-text-secondary;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
  }
}

.cgh-deactivate {
  color: $color-status-error;
  text-transform: none;
  letter-spacing: normal;
}
</style>
