<template>
  <div class="chain-stop-control">
    <v-btn
      class="stop-chain-button"
      variant="outlined"
      :loading="stopping"
      data-testid="stop-chain-btn"
      @click="emit('open')"
    >
      <v-icon size="18" class="mr-1">mdi-stop-circle-outline</v-icon>
      Stop chain
    </v-btn>

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
  margin-left: auto;
}

.stop-chain-button {
  color: $color-status-error;
  // Outlined, never filled: a filled control would out-weigh the primary action on
  // this screen, and the operator asked for red outlined.
  border-color: $color-status-error;
  letter-spacing: normal;
  text-transform: none;
}

.stop-effects {
  color: $color-text-secondary;
}
</style>
