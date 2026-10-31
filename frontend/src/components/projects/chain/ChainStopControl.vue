<template>
  <div class="chain-stop-control">
    <button
      type="button"
      class="csc-btn"
      :disabled="stopping"
      :aria-busy="stopping ? 'true' : undefined"
      :title="STOP_CHAIN_TOOLTIP"
      data-testid="stop-chain-btn"
      @click="emit('open')"
    >
      <v-progress-circular v-if="stopping" indeterminate size="12" width="2" />
      <v-icon v-else size="16" aria-hidden="true">mdi-stop-circle-outline</v-icon>
      Stop chain
    </button>

    <BaseDialog
      :model-value="modelValue"
      type="danger"
      title="Stop chain?"
      confirm-label="Stop chain"
      size="sm"
      :loading="stopping"
      @confirm="emit('confirm')"
      @cancel="emit('cancel')"
    >
      <p v-if="effectsText" class="mb-3 stop-effects">{{ effectsText }}</p>
      <v-alert type="warning" variant="tonal" density="compact">
        You can set the terminated project back to inactive from the Projects list and
        stage it again.
      </v-alert>
    </BaseDialog>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { STOP_CHAIN_TOOLTIP } from './chainControlTooltips.js'
import { buildStopChainEffects } from '@/components/projects/chainScreenVisibility.js'

const props = defineProps({
  run: {
    type: Object,
    default: null,
  },
  modelValue: {
    type: Boolean,
    default: false,
  },
  stopping: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['open', 'confirm', 'cancel'])

const effects = computed(() => buildStopChainEffects(props.run))

function list(numbers) {
  return numbers.join(', ')
}

const effectSentences = computed(() => {
  const { completed, underway, unstarted } = effects.value
  const sentences = []
  if (completed.length) {
    sentences.push(`${list(completed)} completed ${completed.length > 1 ? 'stay' : 'stays'}.`)
  }
  if (underway.length) {
    sentences.push(`${list(underway)} ${underway.length > 1 ? 'become' : 'becomes'} terminated.`)
  }
  if (unstarted.length) {
    sentences.push(`${list(unstarted)} ${unstarted.length > 1 ? 'return' : 'returns'} to inactive.`)
  }
  return sentences
})

const effectsText = computed(() => effectSentences.value.join(' '))
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

.chain-stop-control {
  display: inline-flex;
}

.csc-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border: 0;
  border-radius: $border-radius-default;
  background: none;
  box-shadow: inset 0 0 0 2px rgba($color-status-error, 0.75);
  color: $color-status-error;
  font: inherit;
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;

  &:hover:not(:disabled),
  &:focus-visible {
    background: rgba($color-status-error, 0.12);
  }

  &:focus-visible {
    outline: 2px solid $color-status-error;
    outline-offset: 2px;
  }

  &:disabled {
    cursor: default;
    opacity: 0.7;
  }
}

.stop-effects {
  color: $color-text-secondary;
}
</style>
