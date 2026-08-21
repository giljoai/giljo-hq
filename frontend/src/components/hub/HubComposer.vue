<!--
  HubComposer.vue — FE-9289c

  One row: To [everyone here ▾] + input + send. The Hub is an occasional check-in
  surface, so saying something takes no ceremony — pick who, type, press Enter.

  The broadcast/direct pair of toggle buttons plus a separate agent dropdown collapsed
  into ONE `To` selector: "everyone here" is the default and posts a broadcast; picking
  a participant makes it direct. Same two outcomes, one control, and the default is
  visible rather than implied.

  FE-9365d: the auto check-in slider is REMOVED, not relocated (absorbs FE-9296b).
  Asking "how often should they poll?" on the send path made a cadence decision out of
  every message. The framing moved into the protocol prompts where a durable default
  belongs; the loop_directive plumbing is untouched and still reachable over MCP.
-->
<template>
  <div class="hub-composer smooth-border" data-testid="hub-composer">
    <!-- Your turn badge — the one accent on the screen, shown when the selected
         thread's baton points at the operator. -->
    <div v-if="isYourTurn" class="hub-composer__your-turn" data-testid="composer-your-turn">
      <span
        class="hub-composer__your-turn-badge smooth-border"
        :style="yourTurnBadgeStyle()"
      >
        <v-icon size="12" class="mr-1">mdi-hand-back-right-outline</v-icon>
        Your turn
      </span>
      <!-- FE-9365g: the release valve. Until it existed the ONLY way to clear "waiting
           on you" was to post a message — so a thread that needed nothing from the
           operator stayed gold forever, and a signal that cannot be dismissed becomes
           noise. This clears the baton server-side; the thread stays open and nothing
           is posted.

           FE-9439: it was a small text button here and the operator could not find it —
           "it exists at the bottom by the chat bar but is not very distinct". Now the
           shared hand toggle, standard size, PULSING while the turn is theirs so the eye
           lands on it. The testid is unchanged deliberately: the same control in better
           clothes, and the regression spec that pins the route fix reads it on both
           sides of this change. -->
      <MarkHandledToggle
        :active="isYourTurn"
        :disabled="clearing"
        pulse
        data-testid="composer-mark-handled"
        @click="markHandled"
      />
    </div>

    <div class="hub-composer__controls">
      <!-- THE row -->
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
          <!-- FE-9365d — `item` is the RAW object under Vuetify 4 (VSelect.js passes
               `item: item.raw`; the InternalItem now arrives separately as
               `internalItem`). Reading `item.title` / `item.value` here is what
               produced a dropdown of bare `??` chips with no names. Read the raw
               fields the items were built with. -->
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
                <!-- The broadcast row is the mascot, not a letter: it is not an agent,
                     and giving it initials would make it read as one. -->
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
import { getAgentColor } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'
import { agentStatusDot } from '@/composables/useAgentStatusDot'
import MarkHandledToggle from '@/components/hub/MarkHandledToggle.vue'
import { useMarkHandled } from '@/components/hub/useMarkHandled'

const commHub = useCommHubStore()
const { showToast } = useToast()

// FE-9439: `isYourTurn` and the clear itself moved to useMarkHandled, because the search
// bar now offers the same action and two copies of it would drift. This component keeps
// the badge and the composer; it no longer owns what the toggle does.
const { isYourTurn, clearing, markHandled } = useMarkHandled()

function yourTurnBadgeStyle() {
  const hex = getAgentColor('orchestrator')?.hex
  return {
    backgroundColor: hexToRgba(hex, 0.18),
    color: hex,
    borderRadius: '8px',
  }
}

// Agent identity in the To selector — tinted color badge + abbrev from the same
// source of truth as the timeline/Home screen (FE-6122). No new map.
// Roles colour the badge where one is known, matching the card pills.
function agentBadgeStyle(participant) {
  const hex = getAgentColor(participant?.role || participant?.display_name)?.hex
  return {
    backgroundColor: hexToRgba(hex, 0.2),
    color: hex,
  }
}

function agentAbbr(name) {
  if (!name) return '??'
  const parts = String(name).split(/[-_\s]+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return String(name).slice(0, 2).toUpperCase()
}

function dotStyle(participant) {
  const dot = agentStatusDot(participant)
  return { backgroundColor: dot.color, boxShadow: dot.ring }
}

// `broadcast · N registered` for the mascot row; `direct · {harness}` for an agent.
// This is one of only two places the full agent NAME is shown, now that the card pills
// carry the badge alone — so the row has room to say who and on what.
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

// ---- state ----
const content = ref('')
const sending = ref(false)

// ---- the To selector ----
// A sentinel value rather than null, so the DEFAULT is a visible choice in the list
// instead of an empty field the operator has to interpret. Selecting it broadcasts.
const EVERYONE = '__everyone__'
const recipient = ref(EVERYONE)

const threadAgents = computed(() => {
  const threadId = commHub.selectedThreadId
  return threadId ? commHub.participantsFor(threadId).filter((p) => p.participant_type !== 'user') : []
})

const agentCount = computed(() => threadAgents.value.length)

// The whole participant object rides through, not a {id, name} pair: the rows render a
// status dot and a harness sub-label, and Vuetify 4 hands the RAW item to the slots.
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

// Participants are fetched once on thread-select, so a freshly join_thread'd agent
// would not appear in the To selector without a manual page refresh. Refetch at the
// moment the operator actually opens it (FE-6121 DoD-3).
function onRecipientMenu(open) {
  const threadId = commHub.selectedThreadId
  if (open && threadId) commHub.loadParticipants(threadId)
}

// A recipient chosen on one thread must not leak onto the next one — the id would not
// exist there, and the post would silently go to nobody.
watch(
  () => commHub.selectedThreadId,
  () => {
    recipient.value = EVERYONE
  },
)

// FE-9365d (absorbs FE-9296b): the auto check-in control is GONE from the composer,
// not hidden behind a toggle in it. Asking "how often should they poll?" on the send
// path made a cadence decision out of every message. The framing moved into the
// protocol prompts, where a durable default belongs; the loop_directive plumbing is
// untouched and still reachable from the MCP tool surface.

// ---- derived ----
const canSend = computed(() => {
  if (!commHub.selectedThreadId) return false
  if (!content.value.trim()) return false
  return true
})

// ---- send ----
// TSK-9295: Enter is the send key, but a user typing with an Input Method Editor
// (Japanese, Chinese, Korean and other composition-based input) presses Enter to
// CONFIRM a candidate word. That keydown reaches this handler regardless — `.exact`
// filters ctrl/alt/shift/meta, not composition — so the half-written message posted
// mid-sentence instead of the candidate committing to the input.
//
// `.prevent` is deliberately NOT a template modifier any more. Vue applies it before
// the handler runs, so it fired on the composing keydown too: suppressing only the
// send would have left the message unsent AND the candidate uncommitted. Calling
// preventDefault here keeps it on the send path, where the newline is what we mean to
// suppress.
//
// Both signals are checked because they cover different browsers. `isComposing` is the
// standard one; `keyCode === 229` is the fallback for browsers that dispatch
// compositionend BEFORE the keydown, leaving isComposing false on an Enter that is
// still confirming a candidate.
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
    // Only clear once the send is known to have LANDED. TSK-9300: the store used to
    // return the server's structured refusal as though it were a sent message, so a
    // declined post cleared the box and toasted success — the operator's text was gone
    // and nothing told them. Clearing is the irreversible step here; it belongs after
    // the await, never before, and never on the error path below.
    content.value = ''
    showToast({ type: 'success', message: 'Message sent.' })
  } catch (err) {
    // The message survives a failure, so the operator can retry or copy it out. The
    // server's refusal hint arrives as err.message and says what to do about it.
    const msg = err?.response?.data?.detail || err?.message || 'Failed to send message.'
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
