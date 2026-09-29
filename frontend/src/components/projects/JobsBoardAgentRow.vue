<template>
  <div class="jb-agent" :class="{ 'jb-agent--interactive': interactive }" data-testid="jb-agent-row">
    <span v-if="interactive" class="jb-play-slot">
      <template v-if="showCopy">
        <button
          v-if="canReplay"
          type="button"
          class="jb-row-btn"
          :title="REPLAY_LABEL"
          :aria-label="REPLAY_LABEL"
          data-testid="jb-agent-recopy"
          @click="emit('replay', agent)"
        >
          <v-icon size="16">mdi-refresh</v-icon>
        </button>
        <button
          v-else
          type="button"
          class="jb-row-btn jb-row-btn--play"
          :class="{ 'jb-row-btn--faded': playFaded }"
          :disabled="playFaded"
          :title="playTooltip"
          aria-label="Copy agent prompt"
          data-testid="jb-agent-play"
          @click="emit('play', agent)"
        >
          <v-icon size="16">mdi-play</v-icon>
        </button>
      </template>
    </span>
    <v-tooltip location="bottom" open-delay="150">
      <template #activator="{ props: tooltipProps }">
        <div
          v-bind="tooltipProps"
          class="agent-badge-sq agent-badge-sq--sm"
          :class="{ 'live-badge': live }"
          data-testid="jb-agent-badge"
          :style="getAgentBadgeStyle(colorKey)"
        >
          {{ getAgentInitials(primaryLabel) }}
        </div>
      </template>
      <div class="jb-badge-tip" data-testid="jb-agent-tooltip">
        <div class="jb-badge-tip-name">{{ primaryLabel }} &middot; {{ roleLabel }}</div>
      </div>
    </v-tooltip>

    <component
      :is="interactive && hasSteps ? 'button' : 'span'"
      class="jb-steps"
      :class="{ 'jb-steps--link': interactive && hasSteps }"
      :type="interactive && hasSteps ? 'button' : undefined"
      :title="interactive && hasSteps ? 'Open the task list' : undefined"
      data-testid="jb-agent-steps"
      @click="interactive && hasSteps && emit('steps', agent)"
    >
      <template v-if="hasSteps">
        {{ agent.steps.completed }}<span class="jb-steps-sub">/{{ agent.steps.total }}</span>
      </template>
      <span v-else>—</span>
    </component>

    <span class="jb-dur" data-testid="jb-agent-duration">{{ duration }}</span>

    <span
      v-if="notPickedUp"
      class="jb-state jb-state--not-picked-up"
      data-testid="jb-agent-status"
      title="Still waiting well after launch: nobody started this agent. Launch it with its stored prompt."
    >
      Not picked up
    </span>
    <span
      v-else
      class="jb-state"
      data-testid="jb-agent-status"
      :style="{ color: getStatusColor(statusWord) }"
    >
      {{ getStatusLabel(statusWord, agent.block_reason) }}<LiveDots v-if="live" />
    </span>

    <button
      v-if="interactive"
      type="button"
      class="jb-msg-btn"
      :aria-label="`View messages (${messagesWaiting} waiting)`"
      data-testid="jb-agent-messages-btn"
      @click="emit('messages', agent)"
    >
      <span
        class="msg-badge"
        data-testid="jb-agent-messages"
        :class="messagesWaiting === 0 ? 'zero' : 'has-msgs'"
      >{{ messagesWaiting }}</span>
    </button>
    <span
      v-else
      class="msg-badge"
      data-testid="jb-agent-messages"
      :class="messagesWaiting === 0 ? 'zero' : 'has-msgs'"
    >{{ messagesWaiting }}</span>

    <v-menu v-if="interactive" location="bottom end">
      <template #activator="{ props: menuProps }">
        <button
          v-bind="menuProps"
          type="button"
          class="jb-row-btn"
          :aria-label="`Actions for ${primaryLabel}`"
          data-testid="jb-agent-kebab"
        >
          <v-icon size="16">mdi-dots-vertical</v-icon>
        </button>
      </template>
      <v-list density="compact" data-testid="jb-agent-menu">
        <v-list-item
          prepend-icon="mdi-message-outline"
          title="View messages"
          data-testid="jb-agent-menu-messages"
          @click="emit('messages', agent)"
        />
        <v-list-item
          prepend-icon="mdi-account-badge-outline"
          title="View agent role"
          data-testid="jb-agent-menu-role"
          @click="emit('agent-role', agent)"
        />
        <v-list-item
          prepend-icon="mdi-briefcase-outline"
          title="View assigned job"
          data-testid="jb-agent-menu-job"
          @click="emit('agent-job', agent)"
        />
        <v-list-item
          v-if="prUrl"
          prepend-icon="mdi-source-pull"
          title="Open pull request"
          :href="prUrl"
          target="_blank"
          rel="noopener noreferrer"
          data-testid="jb-agent-menu-pr"
        />
      </v-list>
    </v-menu>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { REPLAY_LABEL } from '@/composables/usePlayButton'
import { getStatusLabel, getStatusColor } from '@/utils/statusConfig'
import { getAgentBadgeStyle } from '@/utils/colorUtils'
import { getAgentColorKey, getAgentInitials } from '@/config/agentColors'
import { getPrimaryAgentLabel, getAgentRoleLabel } from '@/utils/agentDisplay'
import { formatAgentDuration } from '@/utils/durationFormat'
import { jobStatusWord, isLiveStatusWord } from '@/utils/jobStatusWord'
import LiveDots from './LiveDots.vue'

const props = defineProps({
  agent: {
    type: Object,
    required: true,
  },
  now: {
    type: Number,
    required: true,
  },
  interactive: {
    type: Boolean,
    default: false,
  },
  showCopy: {
    type: Boolean,
    default: false,
  },
  playFaded: {
    type: Boolean,
    default: false,
  },
  playTooltip: {
    type: String,
    default: 'Copy prompt',
  },
  canReplay: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['play', 'replay', 'messages', 'agent-role', 'agent-job', 'steps'])

const colorKey = computed(() => getAgentColorKey(props.agent))
const primaryLabel = computed(() => getPrimaryAgentLabel(props.agent))
const roleLabel = computed(() => getAgentRoleLabel(props.agent))
const duration = computed(() => formatAgentDuration(props.agent, props.now))
const statusWord = computed(() => jobStatusWord(props.agent))
const live = computed(() => !notPickedUp.value && isLiveStatusWord(statusWord.value))
const messagesWaiting = computed(() => props.agent?.messages_waiting_count ?? 0)
const hasSteps = computed(
  () => Boolean(props.agent?.steps) && typeof props.agent.steps.completed === 'number' && typeof props.agent.steps.total === 'number',
)
const notPickedUp = computed(() => props.agent?.status === 'waiting' && props.agent?.not_picked_up === true)
const prUrl = computed(() => {
  const url = props.agent?.result?.pr_url
  return typeof url === 'string' && url.trim() ? url.trim() : null
})
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

.jb-agent--interactive {
  grid-template-columns: 24px 26px 1fr 1fr 1fr 30px 24px;
}

.jb-steps--link {
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  color: inherit;
  cursor: pointer;
  text-decoration: underline dotted;
  text-underline-offset: 2px;

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
  }
}

.jb-state--not-picked-up {
  color: $color-status-silent;
  font-style: italic;
  cursor: help;
}

.jb-play-slot {
  display: inline-flex;
  justify-content: center;
}

.jb-row-btn,
.jb-msg-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: none;
  border: none;
  cursor: pointer;
  color: $color-text-secondary;
  border-radius: $border-radius-pill;

  &:hover,
  &:focus-visible {
    color: $color-text-primary;
  }
}

.jb-row-btn {
  width: 24px;
  height: 24px;
}

.jb-row-btn--play {
  color: $color-brand-yellow;
}

.jb-row-btn--faded {
  color: $color-text-muted;
  opacity: 0.35;
  cursor: default;
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
  }
}
</style>
