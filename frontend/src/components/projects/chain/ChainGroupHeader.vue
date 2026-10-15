<template>
  <header class="cgh" data-testid="chain-group-header">
    <div class="cgh-top">
      <v-icon size="20" class="cgh-icon" aria-hidden="true">mdi-link-variant</v-icon>
      <h2 class="cgh-name" data-testid="chain-group-name">{{ chainCtx.name }}</h2>
      <span class="cgh-pill cgh-counter" data-testid="chain-group-counter">
        Step {{ chainCtx.counter.n }} of {{ chainCtx.counter.m }}
      </span>
    </div>

    <ChainMissionWindow :mission="chainCtx.chainMission" class="cgh-goal">
      <template v-if="running" #actions>
        <div class="cgh-actions" data-testid="chain-header-actions">
          <ChainStopControl
            :run="chainCtx.run"
            :model-value="controls.showChainStopConfirm"
            :stopping="controls.chainStopping"
            @open="controls.openChainStopConfirm"
            @confirm="controls.handleChainStop"
            @cancel="controls.cancelChainStop"
          />
          <button
            type="button"
            class="cgh-link"
            :disabled="controls.deactivating"
            :aria-busy="controls.deactivating ? 'true' : undefined"
            data-testid="chain-group-deactivate"
            @click="controls.openDeactivateConfirm"
          >
            Deactivate chain
          </button>
        </div>
      </template>
    </ChainMissionWindow>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import ChainMissionWindow from './ChainMissionWindow.vue'
import ChainStopControl from './ChainStopControl.vue'

const props = defineProps({
  chainCtx: { type: Object, required: true },
  controls: { type: Object, default: null },
})

const running = computed(() => props.controls?.chainPhase === 'running')
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;
@use '@/styles/chain-pill' as pill;

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

.cgh-pill {
  @include pill.chain-pill;
}

.cgh-counter {
  color: $color-brand-yellow;
  background: rgba($color-brand-yellow, 0.12);
}

.cgh-actions {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

// The same quiet link the control area uses for Deactivate chain (StagingControlArea .sca-link).
.cgh-link {
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  font-size: 0.76rem;
  color: $color-text-tertiary;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;

  &:hover:not(:disabled),
  &:focus-visible {
    color: $color-brand-yellow;
  }

  &:focus-visible {
    outline: 2px solid $color-brand-yellow;
    outline-offset: 2px;
  }

  &:disabled {
    cursor: default;
    opacity: 0.7;
  }
}
</style>
