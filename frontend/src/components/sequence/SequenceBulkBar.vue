<template>
  <div v-if="count > 0" class="seq-bulk-bar smooth-border" data-testid="seq-bulk-bar">
    <span class="seq-bulk-count" data-testid="seq-bulk-count">{{ count }} selected</span>
    <span v-if="overCap" class="seq-bulk-warn" data-testid="seq-bulk-warn">
      Max {{ max }} per sequence — deselect {{ count - max }}
    </span>
    <span v-else-if="underMin" class="seq-bulk-hint" data-testid="seq-bulk-hint">
      Elect at least 2 for a sequential run
    </span>
    <div class="seq-bulk-spacer" />
    <v-btn variant="text" size="small" class="seq-bulk-clear" @click="$emit('clear')">Clear</v-btn>
    <v-btn
      color="primary"
      variant="flat"
      size="small"
      prepend-icon="mdi-playlist-play"
      class="seq-bulk-run"
      :disabled="underMin || overCap"
      :title="underMin ? 'Elect at least 2 projects for a sequential run.' : undefined"
      :aria-label="underMin ? 'Run sequential (disabled — elect at least 2 projects)' : `Run sequential (${count}/${max})`"
      data-testid="seq-run-btn"
      @click="$emit('run')"
    >
      Run sequential ({{ count }}/{{ max }})
    </v-btn>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { MAX_SEQUENCE_PROJECTS } from '@/utils/sequenceOrder'

const props = defineProps({
  count: { type: Number, default: 0 },
})

defineEmits(['run', 'clear'])

const MIN_SEQUENCE_PROJECTS = 2
const max = MAX_SEQUENCE_PROJECTS
const overCap = computed(() => props.count > max)
const underMin = computed(() => props.count < MIN_SEQUENCE_PROJECTS)
</script>

<style scoped lang="scss">
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;

.seq-bulk-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  margin-bottom: 16px;
  border-radius: $border-radius-rounded;
  background: rgba($color-brand-yellow, 0.08);
  box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.3);
}

.seq-bulk-count {
  font-size: 0.82rem;
  font-weight: 600;
  color: $color-text-primary;
  white-space: nowrap;
}

.seq-bulk-warn {
  font-size: 0.74rem;
  color: $color-status-error;
  white-space: nowrap;
}

.seq-bulk-hint {
  font-size: 0.74rem;
  color: $color-text-muted;
  white-space: nowrap;
}

.seq-bulk-spacer {
  flex: 1;
}

.seq-bulk-run,
.seq-bulk-clear {
  text-transform: none;
  letter-spacing: 0;
}

@media (max-width: 600px) {
  .seq-bulk-bar {
    flex-wrap: wrap;
  }
}
</style>
