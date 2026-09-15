<template>
  <div class="jb-agent" data-testid="jb-agent-row">
    <v-tooltip location="bottom" open-delay="150">
      <template #activator="{ props: tooltipProps }">
        <div
          v-bind="tooltipProps"
          class="agent-badge-sq agent-badge-sq--sm"
          data-testid="jb-agent-badge"
          :style="getAgentBadgeStyle(colorKey)"
        >
          {{ getAgentInitials(primaryLabel) }}
        </div>
      </template>
      <div class="jb-badge-tip" data-testid="jb-agent-tooltip">
        <div class="jb-badge-tip-name">{{ primaryLabel }} &middot; {{ roleLabel }}</div>
        <div class="jb-badge-tip-line"><span class="jb-tip-k">agent</span> {{ agent.agent_id || '—' }}</div>
        <div class="jb-badge-tip-line"><span class="jb-tip-k">job</span> {{ agent.job_id || agent.id || '—' }}</div>
      </div>
    </v-tooltip>

    <span class="jb-steps" data-testid="jb-agent-steps">
      <template v-if="agent.steps && typeof agent.steps.completed === 'number' && typeof agent.steps.total === 'number'">
        {{ agent.steps.completed }}<span class="jb-steps-sub">/{{ agent.steps.total }}</span>
      </template>
      <span v-else>—</span>
    </span>

    <span class="jb-dur" data-testid="jb-agent-duration">{{ duration }}</span>

    <span
      class="jb-state"
      data-testid="jb-agent-status"
      :style="{ color: getStatusColor(agent.status, agent.block_reason) }"
    >
      {{ getStatusLabel(agent.status, agent.block_reason) }}
    </span>

    <span
      class="msg-badge"
      data-testid="jb-agent-messages"
      :class="messagesWaiting === 0 ? 'zero' : 'has-msgs'"
    >{{ messagesWaiting }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { getStatusLabel, getStatusColor } from '@/utils/statusConfig'
import { getAgentBadgeStyle } from '@/utils/colorUtils'
import { getAgentColorKey, getAgentInitials } from '@/config/agentColors'
import { getPrimaryAgentLabel, getAgentRoleLabel } from '@/utils/agentDisplay'
import { formatAgentDuration } from '@/utils/durationFormat'

const props = defineProps({
  agent: {
    type: Object,
    required: true,
  },
  now: {
    type: Number,
    required: true,
  },
})

const colorKey = computed(() => getAgentColorKey(props.agent))
const primaryLabel = computed(() => getPrimaryAgentLabel(props.agent))
const roleLabel = computed(() => getAgentRoleLabel(props.agent))
const duration = computed(() => formatAgentDuration(props.agent, props.now))
const messagesWaiting = computed(() => props.agent?.messages_waiting_count ?? 0)
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-agent {
  display: grid;
  grid-template-columns: 26px 1fr 1fr 1fr 30px;
  align-items: center;
  gap: 4px;
  font-size: 0.75rem;
  font-family: $typography-font-mono;
}

.jb-steps,
.jb-dur,
.jb-state {
  text-align: center;
}

.jb-steps {
  color: $color-text-tertiary;
}

.jb-steps-sub {
  color: $color-text-secondary;
}

.jb-dur {
  color: $color-text-secondary;
}

.jb-state {
  font-size: 0.71rem;
  font-family: $typography-font-primary;
}

.jb-badge-tip {
  font-family: $typography-font-mono;
  font-size: 0.68rem;
  line-height: 1.6;
  text-align: left;
  white-space: nowrap;

  .jb-badge-tip-name {
    font-family: $typography-font-primary;
    font-size: 0.76rem;
    font-weight: 600;
    color: $color-text-primary;
    margin-bottom: 2px;
  }

  .jb-tip-k {
    color: $color-text-secondary;
  }
}
</style>
