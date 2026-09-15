<template>
  <tr
    data-testid="agent-row"
    :data-agent-display-name="agent.agent_display_name"
    :data-agent-status="agent.status"
  >
    <td class="phase-cell" data-testid="phase-badge">
      <span v-if="isSubagentMode" class="phase-badge">All</span>
      <span v-else-if="isOrchestratorAgent" class="phase-badge">Start</span>
      <span v-else-if="agent.phase == null" class="phase-badge phase-badge--none">&mdash;</span>
      <span v-else class="phase-badge">P{{ agent.phase }}</span>
    </td>

    <td class="play-cell">
      <div class="play-btn-slot">
        <template v-if="shouldShowCopy">
          <v-tooltip text="Copy prompt">
            <template #activator="{ props: tooltipProps }">
              <button
                v-bind="tooltipProps"
                type="button"
                class="play-circle-btn icon-interactive-play"
                :class="{ 'play-btn-faded': playFaded }"
                :disabled="playFaded"
                aria-label="Copy agent prompt"
                @click="emit('play', agent)"
              >
                <v-icon size="18">mdi-play</v-icon>
              </button>
            </template>
          </v-tooltip>
        </template>
      </div>
    </td>

    <td class="agent-display-name-cell">
      <div class="agent-card-row">
        <button
          type="button"
          class="agent-avatar-button"
          aria-label="View agent details"
          @click="emit('agent-role', agent)"
        >
          <div
            class="agent-badge"
            :class="{ 'agent-badge--active': agent.status === 'working' }"
            :style="getAgentBadgeStyle(getAgentColorKey(agent))"
          >
            {{ getAgentAbbr(getPrimaryAgentLabel(agent)) }}
          </div>
        </button>
        <div class="agent-info">
          <button
            type="button"
            class="agent-name-primary agent-name-button"
            aria-label="View assigned job"
            @click="emit('agent-job', agent)"
          >
            {{ getPrimaryAgentLabel(agent) }}
          </button>
          <span
            v-if="agent.agent_name && !isOrchestratorAgent"
            class="agent-display-name-secondary"
          >
            Skills: {{ agent.agent_name }}
          </span>
          <button
            v-else-if="isOrchestratorAgent"
            type="button"
            class="agent-display-name-secondary agent-name-button"
            @click="emit('agent-job', agent)"
          >
            Skills: Fixed system agent
          </button>
        </div>
      </div>
    </td>

    <td
      class="status-cell"
      data-testid="status-chip"
      :style="{
        color: getStatusColor(agent.status, agent.block_reason),
        fontStyle: isStatusItalic(agent.status) ? 'italic' : 'normal'
      }"
    >
      {{ getStatusLabel(agent.status, agent.block_reason) }}<span v-if="agent.status === 'working'" class="working-dots"><span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></span>
    </td>

    <td class="duration-cell hide-mobile" data-testid="duration">
      {{ formatDuration(agent) }}
    </td>

    <td class="steps-cell text-center hide-mobile">
      <button
        v-if="agent.steps && typeof agent.steps.completed === 'number' && typeof agent.steps.total === 'number'"
        type="button"
        class="steps-trigger"
        aria-label="View execution plan"
        data-testid="steps-trigger"
        @click="emit('steps', agent)"
      >
        {{ agent.steps.completed }}<span v-if="agent.steps.skipped" class="steps-skipped">({{ agent.steps.skipped }})</span> / {{ agent.steps.total }}
      </button>
      <span v-else>—</span>
    </td>

    <td class="messages-waiting-cell text-center hide-mobile">
      <button
        type="button"
        class="message-count-button"
        :aria-label="getActionRequiredUnread(agent) > 0 ? 'View messages — action required' : 'View messages'"
        @click="emit('messages', agent)"
      >
        <span
          class="msg-badge"
          data-testid="messages-badge"
          :class="getMessageBadgeClass(agent)"
          :title="getActionRequiredUnread(agent) > 0 ? `${getActionRequiredUnread(agent)} message(s) need your action` : undefined"
        >{{ getMessagesWaiting(agent) }}</span>
      </button>
    </td>

    <td class="actions-cell">
      <div class="actions-inline">
        <v-tooltip v-if="prUrl" text="Open pull request">
          <template #activator="{ props: tooltipProps }">
            <a
              v-bind="tooltipProps"
              :href="prUrl"
              target="_blank"
              rel="noopener noreferrer"
              class="pr-link-btn icon-interactive"
              aria-label="Open pull request"
              data-testid="jobs-pr-link"
            >
              <v-icon size="18">mdi-source-pull</v-icon>
            </a>
          </template>
        </v-tooltip>

        <v-tooltip v-if="playFaded" text="Re-copy prompt">
          <template #activator="{ props: tooltipProps }">
            <v-btn
              v-bind="tooltipProps"
              icon="mdi-refresh"
              size="small"
              variant="text"
              class="icon-interactive"
              aria-label="Re-copy prompt"
              @click="emit('reactivate-play', agent)"
            />
          </template>
        </v-tooltip>

        <v-tooltip text="View messages">
          <template #activator="{ props: tooltipProps }">
            <v-btn
              v-bind="tooltipProps"
              icon="mdi-message-outline"
              size="small"
              variant="text"
              class="icon-interactive"
              aria-label="View messages"
              data-testid="jobs-messages-btn"
              @click="emit('messages', agent)"
            />
          </template>
        </v-tooltip>

        <v-tooltip text="View agent role">
          <template #activator="{ props: tooltipProps }">
            <v-btn
              v-bind="tooltipProps"
              size="small"
              variant="text"
              class="icon-interactive giljo-face-btn"
              aria-label="View agent role"
              data-testid="jobs-role-btn"
              @click="emit('agent-role', agent)"
            >
              <img
                :src="giljoFaceIcon"
                alt="Agent Role"
                class="giljo-face-icon giljo-face-default"
              />
              <img
                :src="giljoFaceIconActive"
                alt="Agent Role"
                class="giljo-face-icon giljo-face-hover"
              />
            </v-btn>
          </template>
        </v-tooltip>

        <v-tooltip text="View assigned job">
          <template #activator="{ props: tooltipProps }">
            <v-btn
              v-bind="tooltipProps"
              icon="mdi-briefcase-outline"
              size="small"
              variant="text"
              class="icon-interactive"
              aria-label="View assigned job"
              data-testid="jobs-info-btn"
              @click="emit('agent-job', agent)"
            />
          </template>
        </v-tooltip>

        <v-tooltip
          v-if="agent.agent_display_name === 'orchestrator' && !['decommissioned', 'handed_over', 'waiting'].includes(agent.status)"
          text="Hand over"
        >
          <template #activator="{ props: tooltipProps }">
            <v-btn
              v-bind="tooltipProps"
              icon="mdi-logout"
              size="small"
              variant="text"
              class="icon-interactive"
              aria-label="Hand over session"
              @click="emit('handover', agent)"
            />
          </template>
        </v-tooltip>

        <v-tooltip
          v-if="agent.agent_display_name === 'orchestrator' && agent.status === 'working'"
          text="Stop project"
        >
          <template #activator="{ props: tooltipProps }">
            <v-btn
              v-bind="tooltipProps"
              icon="mdi-stop-circle-outline"
              size="small"
              variant="text"
              color="error"
              aria-label="Stop project"
              data-testid="jobs-stop-btn"
              @click="emit('stop-project')"
            />
          </template>
        </v-tooltip>
      </div>

      <div class="actions-menu">
        <v-menu>
          <template #activator="{ props: menuProps }">
            <v-btn
              v-bind="menuProps"
              icon="mdi-dots-vertical"
              size="small"
              variant="text"
              class="icon-interactive"
              aria-label="Agent actions"
            />
          </template>
          <v-list density="compact">
            <v-list-item
              v-if="prUrl"
              prepend-icon="mdi-source-pull"
              title="Open pull request"
              :href="prUrl"
              target="_blank"
              rel="noopener noreferrer"
            />
            <v-list-item prepend-icon="mdi-message-outline" title="View messages" @click="emit('messages', agent)" />
            <v-list-item title="View agent role" @click="emit('agent-role', agent)">
              <template #prepend>
                <img :src="giljoFaceIcon" alt="Agent Role" class="giljo-face-icon menu-icon" />
              </template>
            </v-list-item>
            <v-list-item prepend-icon="mdi-briefcase-outline" title="View assigned job" @click="emit('agent-job', agent)" />
            <v-list-item
              v-if="agent.agent_display_name === 'orchestrator' && !['decommissioned', 'handed_over', 'waiting'].includes(agent.status)"
              prepend-icon="mdi-logout"
              title="Hand over"
              @click="emit('handover', agent)"
            />
            <v-list-item
              v-if="agent.agent_display_name === 'orchestrator' && agent.status === 'working'"
              prepend-icon="mdi-stop-circle-outline"
              title="Stop project"
              class="text-error"
              @click="emit('stop-project')"
            />
          </v-list>
        </v-menu>
      </div>
    </td>
  </tr>
</template>

<script setup>
import { computed } from 'vue'
import { getStatusLabel, getStatusColor, isStatusItalic } from '@/utils/statusConfig'
import { getAgentBadgeStyle } from '@/utils/colorUtils'
import { getAgentColorKey, getAgentInitials } from '@/config/agentColors'
import { isOrchestrator, getPrimaryAgentLabel } from '@/utils/agentDisplay'
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
  isSubagentMode: {
    type: Boolean,
    default: false,
  },
  shouldShowCopy: {
    type: Boolean,
    default: false,
  },
  playFaded: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits([
  'play',
  'reactivate-play',
  'messages',
  'steps',
  'agent-role',
  'agent-job',
  'handover',
  'stop-project',
])


const isOrchestratorAgent = computed(() => isOrchestrator(props.agent))

const prUrl = computed(() => {
  const url = props.agent?.result?.pr_url
  return typeof url === 'string' && url.trim() ? url.trim() : null
})

const giljoFaceIcon = '/icons/Giljo_Inactive_Dark.svg'
const giljoFaceIconActive = '/icons/Giljo_YW_Face.svg'

function getAgentAbbr(displayName) {
  return getAgentInitials(displayName)
}

function getMessagesWaiting(agent) {
  return agent?.messages_waiting_count ?? 0
}

function getActionRequiredUnread(agent) {
  return agent?.action_required_unread ?? 0
}

function getMessageBadgeClass(agent) {
  if (getActionRequiredUnread(agent) > 0) return 'needs-action'
  return getMessagesWaiting(agent) > 0 ? 'has-msgs' : 'zero'
}

function formatDuration(agent) {
  return formatAgentDuration(agent, props.now)
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

// ---------------------------------------------------------------------------
// All tbody td rules live here — scoped CSS leaf is <td>, must be in AgentRow
// ---------------------------------------------------------------------------

tbody td {
  padding: 12px 14px;
  font-size: 0.78rem;
  @include table-row-separator;
  vertical-align: middle;

  &.phase-cell {
    width: 56px;
    text-align: center;
    padding: 12px 8px;

    .phase-badge {
      display: inline-block;
      font-size: 0.68rem;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: $border-radius-default;
      background-color: rgba($color-phase-amber, 0.15);
      color: $color-phase-amber;
      white-space: nowrap;

      &--none {
        background: transparent;
        color: rgba(var(--v-theme-on-surface), 0.35);
      }
    }
  }

  &.play-cell {
    width: 40px;
    padding: 12px 4px 12px 14px;
    text-align: center;

    .play-btn-slot {
      display: flex;
      align-items: center;
      gap: 2px;
    }

    .play-circle-btn {
      width: 30px;
      height: 30px;
      border: none;
      display: grid;
      place-items: center;
      padding: 0;

      .v-icon {
        color: $color-brand-yellow;
      }

      &.play-btn-faded {
        background: transparent;
        color: $color-text-muted;
        opacity: 0.2;
        cursor: default;
        pointer-events: none;

        .v-icon {
          color: $color-text-muted;
        }
      }
    }
  }

  &.agent-display-name-cell {
    width: 1%;
    white-space: nowrap;
    padding-left: 4px;

    .agent-card-row {
      display: flex;
      align-items: center;
      gap: 10px;
      white-space: nowrap;
    }

    .agent-badge {
      width: 32px;
      height: 32px;
      border-radius: $border-radius-default;
      display: grid;
      place-items: center;
      font-size: 0.62rem;
      font-weight: 700;
      flex-shrink: 0;
      position: relative;
      transition: filter 0.3s ease;
    }

    // Active agent: breathing glow + expanding pulse ring
    .agent-badge--active {
      animation: badgeBreathe 2.4s ease-in-out infinite;

      &::before,
      &::after {
        content: '';
        position: absolute;
        inset: 0;
        border-radius: inherit;
        pointer-events: none;
        animation: badgePulseRing 2.4s ease-out infinite;
      }

      &::after {
        animation-delay: 1.2s;
      }
    }

    @keyframes badgeBreathe {
      0%, 100% { filter: brightness(1); }
      50% { filter: brightness(1.3); }
    }

    @keyframes badgePulseRing {
      0% { box-shadow: 0 0 0 0 currentColor; opacity: 0.4; }
      70% { box-shadow: 0 0 0 10px currentColor; opacity: 0; }
      100% { box-shadow: 0 0 0 10px currentColor; opacity: 0; }
    }

    .agent-avatar-button,
    .agent-name-button {
      background: none;
      border: none;
      padding: 0;
      cursor: pointer;
      text-align: left;
      color: inherit;
    }

    .agent-info {
      display: flex;
      flex-direction: column;
      min-width: 0;

      .agent-name-primary {
        font-size: 0.8rem;
        font-weight: 500;
        text-transform: capitalize;
      }

      .agent-display-name-secondary {
        font-size: 0.62rem;
        color: $color-text-muted;
        text-transform: capitalize;
      }
    }
  }

  &.status-cell {
    text-align: center;
    font-size: 0.75rem;

    .working-dots {
      display: inline;

      .dot {
        animation: dot-blink 1.4s infinite steps(1);
        opacity: 0;
      }

      .dot:nth-child(1) { animation-delay: 0s; }
      .dot:nth-child(2) { animation-delay: 0.3s; }
      .dot:nth-child(3) { animation-delay: 0.6s; }
    }
  }

  @keyframes dot-blink {
    0%, 100% { opacity: 0; }
    30%, 70% { opacity: 1; }
  }

  &.duration-cell {
    text-align: center;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    color: $color-text-secondary;
  }

  .steps-trigger {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    white-space: nowrap;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    color: $color-text-secondary;
  }

  .steps-skipped {
    color: $color-status-blocked;
    font-weight: 600;
  }

  .message-count-button {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    color: inherit;
  }

  // .msg-badge itself is promoted to the shared, unscoped main.scss
  // (FE-9551) so JobsBoardAgentRow.vue/JobsBoardDetailModal.vue can reuse the
  // exact same messages-waiting pill instead of a bespoke one.

  &.actions-cell {
    text-align: right;
    white-space: nowrap;

    .actions-inline {
      display: flex;
      gap: 2px;

      .v-btn {
        min-width: auto;
        width: 30px;
        height: 30px;
        padding: 0;
      }

      // BE-8003j: PR link is an <a>, not a v-btn — match the icon-button footprint.
      .pr-link-btn {
        width: 30px;
        height: 30px;
        display: grid;
        place-items: center;
        border-radius: $border-radius-default;
        color: $color-brand-yellow;
      }
    }

    .actions-menu {
      display: none;

      .giljo-face-icon.menu-icon {
        width: 20px;
        height: 20px;
        margin-right: 8px;
      }
    }
  }
}

// Remove border-bottom on last row
// :last-child evaluates against sibling <tr>s in the container's <tbody>
tbody tr:last-child td {
  border-bottom: none;
}

/* GiljoAI Face Icon — gray default, yellow on hover */
.giljo-face-icon {
  width: 18px;
  height: 18px;
  object-fit: contain;
}

.giljo-face-btn {
  .giljo-face-hover { display: none; }
  .giljo-face-default { display: block; }

  &:hover {
    .giljo-face-hover { display: block; }
    .giljo-face-default { display: none; }
  }
}

/* Responsive: below 1200px — collapse action icons to three-dot menu */
@media (max-width: 1200px) {
  tbody td.actions-cell {
    .actions-inline {
      display: none;
    }

    .actions-menu {
      display: inline-flex;
    }
  }
}

/* Responsive: below 840px — hide agent name text, show badge only */
@media (max-width: 840px) {
  tbody td.agent-display-name-cell {
    text-align: center;
    padding-left: 14px;

    .agent-card-row {
      justify-content: center;
    }

    .agent-info {
      display: none;
    }
  }
}

/* Responsive: portrait / narrow screens — hide extra columns.
   FE-9536: harmonized from a bespoke 768px onto $breakpoint-mobile (600px) --
   MUST stay identical to JobsTab's thead th.hide-mobile breakpoint below, or
   headers and cells hide at different widths and the columns misalign. */
/* DUPLICATED in JobsTab for thead th.hide-mobile; here covers td.hide-mobile */
@media (max-width: $breakpoint-mobile) {
  .hide-mobile {
    display: none;
  }
}
</style>
