<template>
  <div ref="timelineEl" class="thread-timeline" data-testid="thread-timeline">
    <div
      v-if="!effectiveThreadId"
      class="thread-timeline__empty"
      data-testid="timeline-no-thread"
    >
      Select a thread to view messages.
    </div>

    <div
      v-else-if="messages.length === 0"
      class="thread-timeline__empty"
      data-testid="timeline-empty"
    >
      No messages yet.
    </div>

    <div
      v-else-if="filteredMessages.length === 0"
      class="thread-timeline__empty"
      data-testid="timeline-search-empty"
    >
      No messages match this search.
    </div>

    <div
      v-for="message in decoratedMessages"
      :key="message.message_id"
      :ref="(el) => setMessageRef(message.message_id, el)"
      class="timeline-msg"
      :class="[
        message._isUser ? 'timeline-msg--user' : 'timeline-msg--agent',
        {
          'timeline-msg--grouped': message._grouped,
          'timeline-msg--focus': message.message_id === focusMessageId,
        },
      ]"
      :data-testid="`timeline-message-${message.message_id}`"
    >
      <span
        v-if="message.message_id === focusMessageId"
        class="timeline-msg__focus-flag"
        :class="`timeline-msg__focus-flag--${resolvedFocusReason}`"
        :data-testid="`hub-focus-${resolvedFocusReason}`"
      >
        {{ FOCUS_COPY[resolvedFocusReason] }}
      </span>
      <div
        v-if="!message._grouped"
        class="timeline-msg__avatar smooth-border"
        :class="{ 'timeline-msg__avatar--user': message._isUser }"
        :style="message._isUser ? undefined : avatarStyle({ role: message._role, name: message._name })"
        :title="message._name"
        aria-hidden="true"
      >
        {{ avatarInitials(message._name) }}
      </div>
      <div v-else class="timeline-msg__avatar-spacer" aria-hidden="true" />

      <div class="timeline-msg__body">
        <div v-if="!message._grouped" class="timeline-msg__header">
          <span
            class="timeline-msg__sender"
            :class="{ 'timeline-msg__sender--user': message._isUser }"
          >
            {{ message._name }}
          </span>
          <span
            v-if="message._harness"
            class="timeline-msg__harness"
            data-testid="message-harness"
          >
            {{ message._harness }}
          </span>
          <span class="timeline-msg__time" data-testid="message-time">
            {{ formatTime(message.created_at) }}
          </span>
          <span
            v-if="message._isDirect"
            class="timeline-msg__type-chip smooth-border"
            :style="directChipStyle"
            data-testid="message-type-chip"
          >
            direct
          </span>
          <span
            v-if="message.requires_action"
            class="timeline-msg__action-flag smooth-border"
            data-testid="message-action-flag"
          >
            <v-icon size="12">mdi-alert-circle-outline</v-icon>
            action required
          </span>
        </div>

        <div class="timeline-msg__content" data-testid="message-content">
          <div class="timeline-msg__md" v-html="renderedBody(message)" />
          <button
            v-if="message._foldable"
            type="button"
            class="timeline-msg__unfold"
            :data-testid="`message-unfold-${message.message_id}`"
            @click="toggleExpanded(message.message_id)"
          >
            {{ expanded.has(message.message_id) ? 'show less' : '…show the full post' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick } from 'vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { useHubMessageOrder } from '@/components/hub/useHubMessageOrder'
import { useSanitizeMarkdown } from '@/composables/useSanitizeMarkdown'
import { getAgentColor, getAgentColorKey, getAgentInitials } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'
import { BATON_FOCUS, MENTION_FOCUS, APPROVAL_FOCUS } from '@/components/hub/hubThreadRoute'

const FOCUS_COPY = {
  [BATON_FOCUS]: 'Waiting on you',
  [MENTION_FOCUS]: 'You were mentioned',
  [APPROVAL_FOCUS]: 'Needs your approval',
}

const props = defineProps({
  threadId: { type: String, default: null },
  search: { type: String, default: '' },
  focusMessageId: { type: String, default: null },
  focusReason: { type: String, default: BATON_FOCUS },
})

const resolvedFocusReason = computed(() =>
  FOCUS_COPY[props.focusReason] ? props.focusReason : BATON_FOCUS,
)

const commHub = useCommHubStore()
const { sanitizeMarkdown } = useSanitizeMarkdown()
const timelineEl = ref(null)
const { newestFirst } = useHubMessageOrder()

const effectiveThreadId = computed(() => props.threadId || commHub.selectedThreadId)
const messages = computed(() => {
  if (!effectiveThreadId.value) return []
  return commHub.messagesFor(effectiveThreadId.value)
})

const messageEls = new Map()
function setMessageRef(messageId, el) {
  if (el) messageEls.set(messageId, el)
  else messageEls.delete(messageId)
}

function scrollToFocused() {
  const el = props.focusMessageId ? messageEls.get(props.focusMessageId) : null
  if (!el || typeof el.scrollIntoView !== 'function') return false
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  return true
}

watch(
  () => messages.value.length,
  () => {
    nextTick(() => {
      if (scrollToFocused()) return
      if (timelineEl.value) {
        timelineEl.value.scrollTop = newestFirst.value ? 0 : timelineEl.value.scrollHeight
      }
    })
  },
)

watch(
  () => props.focusMessageId,
  () => nextTick(scrollToFocused),
)


function authorFor(message) {
  const p = commHub
    .participantsFor(effectiveThreadId.value)
    .find((x) => x.participant_id === message.from_agent_id)
  return {
    isUser: message.from_kind === 'user',
    name: p?.display_name || message.from_display_name || message.from_agent_id,
    role: p?.role || '',
    harness: p?.harness || '',
  }
}

function harnessLabel(harness) {
  if (!harness) return ''
  return harness === 'generic' ? 'Generic Harness' : harness
}

const GROUP_WINDOW_MS = 5 * 60 * 1000

function continuesRun(message, previous) {
  if (!previous) return false
  if (previous.from_agent_id !== message.from_agent_id) return false
  if (previous.from_kind !== message.from_kind) return false
  if (message.requires_action) return false
  const a = new Date(previous.created_at).getTime()
  const b = new Date(message.created_at).getTime()
  if (Number.isNaN(a) || Number.isNaN(b)) return false
  return Math.abs(b - a) < GROUP_WINDOW_MS
}

const FOLD_THRESHOLD = 420
const expanded = reactive(new Set())

function toggleExpanded(id) {
  if (expanded.has(id)) expanded.delete(id)
  else expanded.add(id)
}

function firstSentence(text) {
  const match = text.match(/^[\s\S]*?[.!?](?=\s|$)/)
  const lead = match ? match[0] : text.slice(0, 200)
  return lead.length < text.length ? lead : text
}

function renderedBody(message) {
  const raw = message.content || ''
  const body = message._foldable && !expanded.has(message.message_id) ? firstSentence(raw) : raw
  return sanitizeMarkdown(body)
}

const filteredMessages = computed(() => {
  const q = String(props.search || '').trim().toLowerCase()
  if (!q) return messages.value
  return messages.value.filter(
    (m) =>
      String(m.content || '').toLowerCase().includes(q) ||
      String(authorFor(m).name || '').toLowerCase().includes(q),
  )
})

const orderedMessages = computed(() =>
  newestFirst.value ? [...filteredMessages.value].reverse() : filteredMessages.value,
)

const decoratedMessages = computed(() =>
  orderedMessages.value.map((m, i) => {
    const author = authorFor(m)
    return {
      ...m,
      _isUser: author.isUser,
      _name: author.name,
      _role: author.role,
      _harness: author.isUser ? '' : harnessLabel(author.harness),
      _isDirect: m.message_type === 'direct',
      _grouped: continuesRun(m, orderedMessages.value[i - 1]),
      _foldable: (m.content || '').length > FOLD_THRESHOLD,
    }
  }),
)

function avatarInitials(name) {
  return getAgentInitials(name)
}

const FALLBACK_HEX = getAgentColor('orchestrator')?.hex

function avatarStyle({ role, name } = {}) {
  const colorObj = getAgentColor(getAgentColorKey({ role, display_name: name }))
  const hex = colorObj?.hex || FALLBACK_HEX
  return {
    backgroundColor: hexToRgba(hex, 0.2),
    color: hex,
    borderRadius: '8px',
  }
}

const directChipStyle = computed(() => {
  const hex = getAgentColor('reviewer')?.hex
  return {
    backgroundColor: hexToRgba(hex, 0.15),
    color: hex,
    borderRadius: '8px',
  }
})

function formatTime(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;
@use '../../styles/variables' as v;

.thread-timeline {
  flex: 1;
  overflow-y: auto;
  padding: v.$spacing-md;
  display: flex;
  flex-direction: column;
  gap: v.$spacing-md;

  &__empty {
    margin: auto;
    color: var(--text-muted);
    font-size: 0.85rem;
    text-align: center;
    padding: v.$spacing-xl 0;
  }
}

.timeline-msg {
  display: flex;
  gap: v.$spacing-sm;
  align-items: flex-start;

  // A continuation sits tighter against the post above it.
  &--grouped {
    margin-top: -#{v.$spacing-sm};
  }

  // FE-9410: the post a baton notification sent the operator to. Brand yellow is the
  // Hub's existing "this is about YOU" colour (the hand icon on both attention
  // surfaces), so the mark reads as the same event, not a new kind of alert.
  &--focus {
    position: relative;

    .timeline-msg__content {
      box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.55);
    }
  }

  // FE-9436: one flag, three tints. Geometry, type and placement are FE-9410's and are
  // shared by all three reasons — per the operator ruling the chip's colour is the ONLY
  // thing that differs, so it is the only thing a modifier sets. Tinted-badge pattern
  // from design-system-sample-v2.html §2: rgba(token, ~0.15) ground, bright token ink,
  // 8px square geometry. Every colour is a token; no hex is written here.
  &__focus-flag {
    position: absolute;
    top: -0.5rem;
    right: 0;
    padding: 0 v.$spacing-xs;
    border-radius: 8px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6875rem; // 11 — the floor
    letter-spacing: 0.02em;
    white-space: nowrap;

    // Hand-off: FE-9410's brand yellow, unchanged — 10.54:1.
    &--baton {
      background: rgba($color-brand-yellow, 0.18);
      color: $color-brand-yellow;
    }

    // Mention: luminous-pastel sky blue — 6.64:1. Informational next to the hand-off's
    // brand yellow, which stays the loudest because it is the only one that owns a turn.
    &--mention {
      background: rgba($color-agent-implementor, 0.18);
      color: $color-agent-implementor;
    }

    // Approval: luminous-pastel lavender — 9.08:1. The decision colour in the palette,
    // and distinct from both blocked-orange and error-magenta, which this is not.
    &--approval {
      background: rgba($color-agent-reviewer, 0.18);
      color: $color-agent-reviewer;
    }
  }

  &--user {
    flex-direction: row-reverse;

    .timeline-msg__body {
      align-items: flex-end;
    }

    .timeline-msg__header {
      flex-direction: row-reverse;
    }

    .timeline-msg__content {
      background: rgba($color-agent-implementor, 0.1);
      border-radius: $border-radius-md $border-radius-sharp $border-radius-md $border-radius-md;
    }
  }

  &--agent {
    .timeline-msg__content {
      background: rgba(255, 255, 255, 0.04);
      border-radius: $border-radius-sharp $border-radius-md $border-radius-md $border-radius-md;
    }
  }

  &__avatar {
    width: 32px;
    height: 32px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.6875rem; // 11 — the floor
    font-weight: 700;
    letter-spacing: 0.02em;

    // USER identity: brand-yellow avatar + initials (matches the nav avatar orb),
    // visually distinct from the agent role-color badges.
    &--user {
      background: rgba($color-brand-yellow, 0.18);
      color: $color-brand-yellow;
      border-radius: 8px;
    }
  }

  &__avatar-spacer {
    width: 32px;
    flex-shrink: 0;
  }

  &__body {
    display: flex;
    flex-direction: column;
    gap: v.$spacing-xs;
    max-width: calc(100% - 44px);
  }

  &__header {
    display: flex;
    align-items: center;
    gap: v.$spacing-xs;
    flex-wrap: wrap;
  }

  &__sender {
    font-size: 0.78125rem; // 12.5
    font-weight: 600;
    // White for every agent — the badge beside it already carries the role colour.
    color: #fff;
    // Names are identifiers (LANE_A, worker-2). Capitalising them rewrites the
    // string the operator quotes back to an agent.
    text-transform: none;

    &--user {
      color: $color-brand-yellow;
    }
  }

  &__harness,
  &__time {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6875rem; // 11 — the floor
    color: var(--text-muted);
  }

  &__type-chip,
  &__action-flag {
    font-size: 0.6875rem; // 11 — the floor
    font-weight: 600;
    padding: 1px 6px;
    text-transform: lowercase;
  }

  &__action-flag {
    background: rgba($color-agent-analyzer, 0.15);
    color: $color-agent-analyzer;
    border-radius: $border-radius-default;
    display: inline-flex;
    align-items: center;
    gap: 3px;
  }

  &__content {
    font-size: 0.83rem;
    line-height: 1.55;
    color: $color-text-primary;
    padding: v.$spacing-sm v.$spacing-md;
    word-break: break-word;
  }

  // Markdown output. Kept close to the plain-text rhythm the pane had before, so a
  // post without any markdown looks unchanged.
  &__md {
    // pre-wrap inside the paragraph, not on the container: agents write single
    // newlines and `marked` leaves them as raw newlines inside the <p>, so without
    // this a hard-wrapped post reflows into one block. Scoping it to <p> keeps the
    // inter-block whitespace from rendering as stray blank lines.
    :deep(p) { margin: 0 0 0.5em; white-space: pre-wrap; }
    :deep(p:last-child) { margin-bottom: 0; }
    :deep(ul),
    :deep(ol) { margin: 0 0 0.5em; padding-left: 1.2em; }
    :deep(h1),
    :deep(h2),
    :deep(h3),
    :deep(h4) { font-size: 0.9rem; font-weight: 700; margin: 0.4em 0 0.3em; }
    :deep(code) {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 0.75rem;
      background: rgba(255, 255, 255, 0.07);
      border-radius: $border-radius-sharp;
      padding: 1px 4px;
    }
    :deep(pre) {
      background: rgba(0, 0, 0, 0.28);
      border-radius: $border-radius-default;
      padding: v.$spacing-sm;
      overflow-x: auto;
      margin: 0 0 0.5em;

      code { background: none; padding: 0; }
    }
    :deep(blockquote) {
      margin: 0 0 0.5em;
      padding-left: v.$spacing-sm;
      border-left: 2px solid rgba(255, 255, 255, 0.18);
      color: var(--text-secondary);
    }
    :deep(a) { color: $color-brand-yellow; }
    :deep(table) { border-collapse: collapse; }
    :deep(th),
    :deep(td) { border: 1px solid rgba(255, 255, 255, 0.12); padding: 2px 6px; }
  }

  &__unfold {
    display: inline-block;
    margin-top: 2px;
    padding: 0;
    border: none;
    background: none;
    color: $color-brand-yellow;
    font-size: 0.75rem;
    cursor: pointer;

    &:hover { text-decoration: underline; }
  }
}
</style>
