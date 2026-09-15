<template>
  <div class="chain-conductor-card smooth-border" data-testid="chain-conductor-card">
    <div class="chain-conductor-card__header">
      <span
        class="chain-conductor-card__badge agent-badge-sq"
        :style="badgeStyle"
      >
        {{ conductorInitial }}
      </span>
      <div class="chain-conductor-card__meta">
        <span class="chain-conductor-card__role">Chain Conductor</span>
        <span class="chain-conductor-card__label">{{ label }}</span>
      </div>
    </div>
    <div class="chain-conductor-card__status">
      <v-chip
        :color="statusColor"
        size="x-small"
        variant="tonal"
        class="chain-conductor-card__chip"
      >
        {{ statusLabel }}
      </v-chip>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { getAgentColor } from '@/config/agentColors'

const props = defineProps({
  conductor: {
    type: Object,
    required: true,
  },
  label: {
    type: String,
    default: 'Conductor',
  },
})

const conductorInitial = computed(() => {
  const name = props.conductor?.agent_display_name || props.label || 'C'
  return name.charAt(0).toUpperCase()
})

const agentColors = computed(() => getAgentColor(props.conductor?.agent_display_name || 'orchestrator'))

const badgeStyle = computed(() => ({
  '--agent-badge-bg': `var(--agent-orchestrator-primary, ${agentColors.value.hex})`,
  background: `rgba(${agentColors.value.rgb}, 0.18)`,
  color: agentColors.value.hex,
}))

const statusLabel = computed(() => {
  const s = props.conductor?.status || 'unknown'
  const map = {
    waiting: 'Waiting',
    running: 'Running',
    completed: 'Done',
    error: 'Error',
    stopped: 'Stopped',
  }
  return map[s] || s
})

const statusColor = computed(() => {
  const s = props.conductor?.status || ''
  if (s === 'running') return 'success'
  if (s === 'completed') return 'default'
  if (s === 'error' || s === 'stopped') return 'error'
  return 'default'
})
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

.chain-conductor-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  padding: 12px 16px;
  margin-bottom: 16px;

  &__header {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  &__badge {
    width: 32px;
    height: 32px;
    border-radius: $border-radius-default;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.8rem;
    font-weight: 700;
    flex-shrink: 0;
  }

  &__meta {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  &__role {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: $color-text-muted;
    font-weight: 600;
  }

  &__label {
    font-size: 0.78rem;
    font-weight: 500;
    color: $color-text-secondary;
  }

  &__status {
    flex-shrink: 0;
  }

  &__chip {
    font-size: 0.65rem;
  }
}
</style>
