<template>
  <BaseDialog
    :model-value="modelValue"
    type="info"
    title="Start a chain?"
    :confirm-label="`Start chain (${ordered.length})`"
    :loading="creating"
    size="sm"
    @confirm="onStart"
    @cancel="$emit('update:modelValue', false)"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <p class="mb-2">These projects run one after another, in this order:</p>
    <v-progress-linear v-if="resolving" indeterminate class="mb-2" />
    <ol v-else class="chain-order" data-testid="chain-order">
      <li v-for="row in ordered" :key="row.project_id" class="chain-order-row">
        <span v-if="row.taxonomy_alias" class="chain-order-alias">{{ row.taxonomy_alias }}</span>
        <span class="chain-order-name">{{ row.name }}</span>
      </li>
    </ol>
    <p class="chain-order-hint">The order follows your roadmap. A lettered series (a, b, c) stays in letter order.</p>
  </BaseDialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { useSequenceRunner } from '@/composables/useSequenceRunner'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  projects: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'started'])

const { creating, resolveRunOrder, startSequence } = useSequenceRunner()
const ordered = ref([])
const resolving = ref(false)

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return
    resolving.value = true
    try {
      ordered.value = await resolveRunOrder(props.projects)
    } finally {
      resolving.value = false
    }
  },
  { immediate: true },
)

async function onStart() {
  const resolvedOrder = ordered.value.map((r) => r.project_id)
  const run = await startSequence({ projectIds: resolvedOrder, resolvedOrder })
  if (run) {
    emit('update:modelValue', false)
    emit('started', run)
  }
}
</script>

<style scoped lang="scss">
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;

.chain-order {
  margin: 0 0 8px 20px;
  padding: 0;
}

.chain-order-row {
  font-size: 0.82rem;
  line-height: 1.8;
}

.chain-order-alias {
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 600;
  margin-right: 8px;
  color: $color-text-primary;
}

.chain-order-name {
  color: $color-text-secondary;
}

.chain-order-hint {
  font-size: 0.74rem;
  color: $color-text-muted;
}
</style>
