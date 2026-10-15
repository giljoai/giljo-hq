<template>
  <div class="chain-staging-actions" data-testid="chain-staging-actions">
    <StagingControlArea
      v-if="controls.chainPhase !== 'running'"
      variant="chain"
      :phase="controls.chainPhase"
      :mode="controls.chainMode"
      :mode-locked="chainCtx.locked"
      :stage-text="controls.chainStageText"
      :stage-title="controls.chainStageTitle"
      :stage-role="chainCtx.locked ? 'secondary' : 'next'"
      :stage-needs-mode="controls.chainStageNeedsMode"
      :stage-blocked="controls.chainStaging"
      :stage-busy="controls.chainStaging"
      :implement-ready="controls.chainImplementReady"
      :implement-busy="controls.launching"
      :copying="controls.copyingChainPrompt"
      secondary-label="Deactivate chain"
      :secondary-busy="controls.deactivating"
      @pick-mode="controls.patchRunMode"
      @stage="controls.handleChainStage"
      @implement="controls.handleChainImplement"
      @copy-prompt="controls.copyChainPrompt"
      @secondary="controls.openDeactivateConfirm"
    >
      <template v-if="controls.chainPhase === 'pickup'" #actions>
        <ChainStopControl
          :run="chainCtx.run"
          :model-value="controls.showChainStopConfirm"
          :stopping="controls.chainStopping"
          @open="controls.openChainStopConfirm"
          @confirm="controls.handleChainStop"
          @cancel="controls.cancelChainStop"
        />
      </template>
    </StagingControlArea>


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
        This returns all {{ chainCtx.counter.m }} linked projects to their <strong>original state</strong>
        and deletes {{ agentCount }} {{ agentCount === 1 ? 'agent' : 'agents' }} and their jobs.
      </p>
      <v-alert type="warning" variant="tonal" density="compact">
        Staging and missions are cleared. <strong>No audit log is kept</strong>; to end a running chain
        and keep its work, use <strong>Stop chain</strong> instead. This cannot be undone.
      </v-alert>
    </BaseDialog>
  </div>
</template>

<script setup>
import BaseDialog from '@/components/common/BaseDialog.vue'
import StagingControlArea from '@/components/projects/StagingControlArea.vue'
import ChainStopControl from './ChainStopControl.vue'

defineProps({
  chainCtx: { type: Object, required: true },
  controls: { type: Object, required: true },
  agentCount: { type: Number, default: 0 },
})
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

.chain-staging-actions {
  margin-top: 16px;
}
</style>
