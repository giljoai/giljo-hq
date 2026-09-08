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
/**
 * JobsBoardAgentRow.vue — FE-9548
 *
 * The Jobs board card's COMPACT per-agent row: [Badge] [Steps] [Duration]
 * [Status] [Messages], no agent name text (badges only, per the v4 mock --
 * the operator asked for this to save card real estate). Reuses AgentRow's
 * underlying display logic rather than re-implementing it:
 *   - getAgentBadgeStyle/getAgentInitials for the tinted square badge (same
 *     rgba(color,0.15)+full-brightness-text treatment as design-system-sample-v2.html),
 *     rendered on the SHARED .agent-badge-sq square (main.scss) rather than a
 *     bespoke .jb-badge (FE-9551) -- --sm is the closest existing size
 *     modifier to this row's original 26px/8px-radius badge (20x20/5px)
 *   - getStatusLabel/getStatusColor from statusConfig.js (same vocabulary as
 *     every other status surface in the product)
 *   - formatAgentDuration from durationFormat.js (extracted out of AgentRow
 *     so both rows render byte-identical duration strings)
 *   - getPrimaryAgentLabel/getAgentRoleLabel from agentDisplay.js for the
 *     hover-tooltip identity (name/role/agent UUID/job UUID) the mock asks for
 *   - the messages pill uses the SHARED .msg-badge class (promoted out of
 *     AgentRow.vue's own scoped CSS into main.scss, FE-9551) with its
 *     'zero'/'has-msgs' modifiers, rather than a bespoke .jb-msg
 *
 * No timer of its own -- `now` is a ticking prop owned by the parent (same
 * pattern as AgentRow), so one interval drives every row on the board.
 *
 * Edition scope: Both.
 */
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
