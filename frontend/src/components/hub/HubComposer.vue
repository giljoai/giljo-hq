<template>
  <div class="hub-composer smooth-border" data-testid="hub-composer">
    <div v-if="isYourTurn" class="hub-composer__your-turn" data-testid="composer-your-turn">
      <span
        class="hub-composer__your-turn-badge smooth-border"
        :style="yourTurnBadgeStyle()"
      >
        <v-icon size="12" class="mr-1">mdi-hand-back-right-outline</v-icon>
        Your turn
      </span>
      <MarkHandledToggle
        :active="isYourTurn"
        :disabled="clearing"
        pulse
        data-testid="composer-mark-handled"
        @click="markHandled"
      />
    </div>

    <div class="hub-composer__controls">
      <div class="hub-composer__row">
        <span class="hub-composer__to-label">To</span>

        <v-select
          v-model="recipient"
          :items="recipientItems"
          item-title="display_name"
          item-value="participant_id"
          variant="solo"
          density="compact"
          flat
          hide-details
          class="hub-composer__to"
          data-testid="composer-to"
          :menu-props="{ location: 'top', contentClass: 'hub-composer__menu' }"
          @update:menu="onRecipientMenu"
        >
          <template #selection="{ item }">
            <img
              v-if="item.participant_id === EVERYONE"
              src="/icons/Giljo_YW_Face.svg"
              alt=""
              class="hub-composer__mascot"
            />
            <span
              v-else
              class="agent-badge-sq agent-badge-sq--sm hub-composer__agent-badge"
              :style="agentBadgeStyle(item)"
              aria-hidden="true"
            >{{ agentAbbr(item.display_name) }}</span>
            <span class="hub-composer__agent-name">{{ item.display_name }}</span>
          </template>

          <template #item="{ item, props: itemProps }">
            <v-list-item
              v-bind="itemProps"
              :title="undefined"
              :subtitle="undefined"
              class="hub-composer__option"
              :class="{ 'hub-composer__option--selected': recipient === item.participant_id }"
              data-testid="composer-to-item"
            >
              <template #prepend>
                <img
                  v-if="item.participant_id === EVERYONE"
                  src="/icons/Giljo_YW_Face.svg"
                  alt=""
                  class="hub-composer__mascot"
                />
                <span
                  v-else
                  class="agent-badge-sq agent-badge-sq--sm"
                  :style="agentBadgeStyle(item)"
                  aria-hidden="true"
                >{{ agentAbbr(item.display_name) }}</span>
              </template>

              <div class="hub-composer__option-body">
                <span class="hub-composer__option-name">{{ item.display_name }}</span>
                <span class="hub-composer__option-sub">{{ optionSubLabel(item) }}</span>
              </div>

              <template #append>
                <span
                  v-if="item.participant_id !== EVERYONE"
                  class="hub-composer__option-dot"
                  :style="dotStyle(item)"
                  :title="agentStatusDot(item).label"
                />
                <v-icon v-if="recipient === item.participant_id" size="16" color="warning">mdi-check</v-icon>
              </template>
            </v-list-item>
          </template>
        </v-select>

        <v-textarea
          v-model="content"
          placeholder="Type a message..."
          variant="solo"
          density="compact"
          flat
          rows="1"
          auto-grow
          max-rows="6"
          hide-details
          class="hub-composer__input"
          data-testid="message-input"
          @keydown.enter.exact="onEnterKey"
        />

        <v-btn
          :disabled="!canSend"
          :loading="sending"
          size="small"
          variant="tonal"
          color="primary"
          class="hub-composer__send-btn"
          data-testid="send-btn"
          @click="onSend"
        >
          <v-icon size="16">mdi-send</v-icon>
        </v-btn>
      </div>

      <p class="hub-composer__caption" data-testid="composer-caption">
        {{ caption }}
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { useToast } from '@/composables/useToast'
import { getAgentColor, getAgentColorKey, getAgentInitials } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'
import { parseErrorResponse } from '@/utils/errorMessages'
import { agentStatusDot } from '@/composables/useAgentStatusDot'
import MarkHandledToggle from '@/components/hub/MarkHandledToggle.vue'
import { useMarkHandled } from '@/components/hub/useMarkHandled'

const commHub = useCommHubStore()
const { showToast } = useToast()

const { isYourTurn, clearing, markHandled } = useMarkHandled()

function yourTurnBadgeStyle() {
  const hex = getAgentColor('orchestrator')?.hex
  return {
    backgroundColor: hexToRgba(hex, 0.18),
    color: hex,
    borderRadius: '8px',
  }
}

function agentBadgeStyle(participant) {
  const hex = getAgentColor(getAgentColorKey(participant))?.hex
  return {
    backgroundColor: hexToRgba(hex, 0.2),
    color: hex,
  }
}

function agentAbbr(name) {
  return getAgentInitials(name)
}

function dotStyle(participant) {
  const dot = agentStatusDot(participant)
  return { backgroundColor: dot.color, boxShadow: dot.ring }
}

function optionSubLabel(item) {
  if (item.participant_id === EVERYONE) {
    const n = agentCount.value
    return `broadcast · ${n} registered`
  }
  return `direct · ${harnessLabel(item.harness)}`
}

function harnessLabel(harness) {
  if (!harness || harness === 'generic') return 'Generic Harness'
  return String(harness).split(' · ')[0]
}

const content = ref('')
const sending = ref(false)

const EVERYONE = '__everyone__'
const recipient = ref(EVERYONE)

const threadAgents = computed(() => {
  const threadId = commHub.selectedThreadId
  return threadId ? commHub.participantsFor(threadId).filter((p) => p.participant_type !== 'user') : []
})

const agentCount = computed(() => threadAgents.value.length)

const recipientItems = computed(() => [
  { participant_id: EVERYONE, display_name: 'Everyone here' },
  ...threadAgents.value.map((p) => ({ ...p, display_name: p.display_name || p.participant_id })),
])

const isBroadcast = computed(() => recipient.value === EVERYONE)

const selectedName = computed(
  () => threadAgents.value.find((p) => p.participant_id === recipient.value)?.display_name || 'that agent',
)

const caption = computed(() =>
  isBroadcast.value
    ? 'Broadcast — everyone registered on this thread sees it on their next poll.'
    : `Direct — only ${selectedName.value} sees this post.`,
)

function onRecipientMenu(open) {
  const threadId = commHub.selectedThreadId
  if (open && threadId) commHub.loadParticipants(threadId)
}

watch(
  () => commHub.selectedThreadId,
  () => {
    recipient.value = EVERYONE
  },
)


const canSend = computed(() => {
  if (!commHub.selectedThreadId) return false
  if (!content.value.trim()) return false
  return true
})

function onEnterKey(event) {
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  onSend()
}

async function onSend() {
  if (!canSend.value) return
  const threadId = commHub.selectedThreadId
  const body = {
    content: content.value.trim(),
  }
  if (!isBroadcast.value) {
    body.to_participant = recipient.value
  }

  sending.value = true
  try {
    await commHub.postMessage(threadId, body)
    content.value = ''
    showToast({ type: 'success', message: 'Message sent.' })
  } catch (err) {
    const msg = parseErrorResponse(err).message || 'Failed to send message.'
    showToast({ type: 'error', message: msg })
  } finally {
    sending.value = false
  }
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;
@use '../../styles/variables' as v;

.hub-composer {
  flex-shrink: 0;
  // Panel container echoing the project jobs-tab composer (MessageComposer):
  // raised surface + inset smooth-border + rounded corners.
  background: $elevation-raised;
  border-radius: $border-radius-rounded; // 16
  margin: v.$spacing-sm v.$spacing-md v.$spacing-md;
  overflow: hidden;

  &__your-turn {
    padding: v.$spacing-xs v.$spacing-sm 0;
    display: flex;
    align-items: center;
    gap: v.$spacing-sm;
  }

  &__your-turn-badge {
    display: inline-flex;
    align-items: center;
    font-size: 0.75rem; // 12
    font-weight: 600;
    padding: 2px 8px;
  }

  &__controls {
    padding: v.$spacing-sm;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  &__row {
    display: flex;
    align-items: flex-start;
    gap: v.$spacing-xs;
  }

  &__to-label {
    font-size: 0.75rem; // 12
    color: var(--text-muted);
    line-height: 32px;
    flex-shrink: 0;
  }

  &__to {
    flex: 0 0 auto;
    width: 190px;

    :deep(.v-field) {
      font-size: 0.78rem;
      background: $elevation-elevated;
      box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.10));
      border-radius: $border-radius-md; // 12 — inputs
    }
  }

  &__cadence-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    flex-shrink: 0;
    border: none;
    background: transparent;
    color: var(--text-muted);
    border-radius: $border-radius-default; // 8
    cursor: pointer;
    transition: color $transition-fast, background $transition-fast;

    &:hover { color: var(--text-secondary); background: rgba(255, 255, 255, 0.06); }
    &--on { color: $color-brand-yellow; background: rgba($color-brand-yellow, 0.14); }
  }

  &__agent-badge {
    margin-right: v.$spacing-xs;
  }

  // The mascot marks the broadcast row. It is the same asset as the Jobs nav icon, so
  // "everyone" reads as the house rather than as another agent.
  &__mascot {
    width: 20px;
    height: 20px;
    flex: none;
    margin-right: v.$spacing-xs;
  }

  &__option-body {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  &__option-name {
    font-size: 0.8125rem; // 13
    color: var(--text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__option-sub {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6875rem; // 11 — the floor
    color: var(--text-muted);
  }

  &__option--selected {
    background: rgba(255, 195, 0, 0.09);

    .hub-composer__option-name { color: #fff; }
  }

  // Round by design — a status dot, the standing exception to the square rule.
  &__option-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex: none;
    margin-right: 6px;
  }

  &__agent-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  // Filled message field matching MessageComposer: recessed elevated surface,
  // inset smooth-border, brand-yellow focus ring (no Vuetify outline).
  &__input {
    flex: 1;
    min-width: 0;

    :deep(.v-field) {
      font-size: 0.85rem;
      background: $elevation-elevated;
      box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.10));
      border-radius: $border-radius-md; // 12 — inputs
    }
    :deep(.v-field:hover) {
      box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.14));
    }
    :deep(.v-field--focused) {
      box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.3);
    }
  }

  &__send-btn {
    min-width: 40px;
    flex-shrink: 0;
  }

  &__caption {
    font-size: 0.6875rem; // 11 — the floor
    color: var(--text-muted);
    margin: 0;
  }
}
</style>
