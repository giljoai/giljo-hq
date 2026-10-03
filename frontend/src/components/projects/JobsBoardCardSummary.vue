<template>
  <div class="jb-summary" data-testid="jb-summary">
    <span class="jb-summary-crew" data-testid="jb-summary-crew">
      <v-tooltip v-for="agent in agents" :key="agent.agent_id || agent.job_id || agent.id" location="bottom" open-delay="150">
        <template #activator="{ props: tooltipProps }">
          <span
            v-bind="tooltipProps"
            class="agent-badge-sq agent-badge-sq--sm jb-summary-badge"
            :class="{ 'live-badge': isLiveStatusWord(jobStatusWord(agent)) }"
            data-testid="jb-summary-badge"
            :style="getAgentBadgeStyle(getAgentColorKey(agent))"
          >
            {{ getAgentInitials(getPrimaryAgentLabel(agent)) }}
            <i class="jb-summary-dot" :style="{ backgroundColor: getStatusColor(jobStatusWord(agent)) }" aria-hidden="true" />
          </span>
        </template>
        <div>{{ getPrimaryAgentLabel(agent) }} &middot; {{ jobStatusLabel(agent) }}</div>
      </v-tooltip>
    </span>

    <span class="jb-summary-facts" data-testid="jb-summary-facts">
      <template v-if="steps.hasSteps">
        <span class="jb-summary-fact">{{ steps.completed }}<span class="jb-summary-sub">/{{ steps.total }}</span> steps</span>
        <span class="jb-summary-sep" aria-hidden="true">&middot;</span>
      </template>
      <template v-if="waiting > 0">
        <span class="jb-summary-fact jb-summary-warn">{{ waiting }} waiting</span>
        <span class="jb-summary-sep" aria-hidden="true">&middot;</span>
      </template>
      <span class="jb-summary-fact">{{ duration }}</span>
    </span>

    <span class="jb-summary-action" data-testid="jb-summary-action">
      <slot name="action" />
    </span>
  </div>
</template>

<script setup>
import { getAgentBadgeStyle } from '@/utils/colorUtils'
import { getAgentColorKey, getAgentInitials } from '@/config/agentColors'
import { getPrimaryAgentLabel } from '@/utils/agentDisplay'
import { getStatusColor } from '@/utils/statusConfig'
import { jobStatusWord, jobStatusLabel, isLiveStatusWord } from '@/utils/jobStatusWord'

defineProps({
  agents: {
    type: Array,
    default: () => [],
  },
  steps: {
    type: Object,
    required: true,
  },
  waiting: {
    type: Number,
    default: 0,
  },
  duration: {
    type: String,
    default: '',
  },
})
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 6px 0 2px;
  font-size: 0.72rem;
  color: $color-text-secondary;
  font-family: $typography-font-mono;
}

.jb-summary-crew {
  display: inline-flex;
  gap: $spacing-tight;
  align-items: center;
}

.jb-summary-badge {
  position: relative;
  cursor: help;
}

.jb-summary-dot {
  position: absolute;
  right: -2px;
  bottom: -2px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  border: 1.5px solid $color-background-primary;
}

.jb-summary-facts {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-variant-numeric: tabular-nums;
}

.jb-summary-sub {
  color: $color-text-secondary;
}

.jb-summary-fact {
  color: $color-text-tertiary;
}

.jb-summary-warn {
  color: $color-text-highlight;
}

.jb-summary-sep {
  opacity: 0.4;
}

.jb-summary-action {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
</style>
