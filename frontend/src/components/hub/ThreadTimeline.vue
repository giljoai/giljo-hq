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

    <!-- FE-9368 (D): a filter that matches nothing is not an empty thread, and saying
         "No messages yet" there would read as data loss. -->
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
      <!-- FE-9410: the operator followed a "waiting on you" notification to THIS post.
           Landing in the thread is not enough on its own — a long thread still leaves
           them scanning — so the post that pulled them here says so out loud.

           FE-9436: three things can pull them here now — a hand-off, a mention, an
           approval — and per the operator ruling they share ONE flag. The reason picks
           the words and the tint; it adds no second element and no second scroll rule.
           The hand-off's reason is spelled `baton`, so its testid is unchanged. -->
      <span
        v-if="message.message_id === focusMessageId"
        class="timeline-msg__focus-flag"
        :class="`timeline-msg__focus-flag--${resolvedFocusReason}`"
        :data-testid="`hub-focus-${resolvedFocusReason}`"
      >
        {{ FOCUS_COPY[resolvedFocusReason] }}
      </span>
      <!-- Sender badge: user -> brand-yellow avatar+initials; agent -> tinted role color
           badge. A grouped continuation keeps the column but shows no badge, so the
           run of posts reads as one person speaking. -->
      <div
        v-if="!message._grouped"
        class="timeline-msg__avatar smooth-border"
        :class="{ 'timeline-msg__avatar--user': message._isUser }"
        :style="message._isUser ? undefined : avatarStyle(message._name)"
        :title="message._name"
        aria-hidden="true"
      >
        {{ avatarInitials(message._name) }}
      </div>
      <div v-else class="timeline-msg__avatar-spacer" aria-hidden="true" />

      <div class="timeline-msg__body">
        <!-- Header row: who / harness / time. NO host — the server cannot know a
             client's hostname, so it would have to be self-declared, which is the
             thing BE-9289a removed. -->
        <div v-if="!message._grouped" class="timeline-msg__header">
          <!-- FE-9365d: the name is WHITE for every agent. Role colour lives in the
               badge and only there. Tinting the name too made six agents in a thread
               read as six different levels of importance — a hierarchy the data does
               not contain and the operator cannot act on. -->
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
          <!-- Direct posts only. "broadcast" is the server-side DEFAULT, so badging it
               marked effectively every message and carried no information; the chip now
               fires only on the case that is actually a choice. -->
          <span
            v-if="message._isDirect"
            class="timeline-msg__type-chip smooth-border"
            :style="directChipStyle"
            data-testid="message-type-chip"
          >
            direct
          </span>
          <!-- requires_action marker -->
          <span
            v-if="message.requires_action"
            class="timeline-msg__action-flag smooth-border"
            data-testid="message-action-flag"
          >
            <v-icon size="12">mdi-alert-circle-outline</v-icon>
            action required
          </span>
        </div>

        <!-- SEC-0003: message bodies are agent-authored, so every one goes through
             useSanitizeMarkdown -> marked -> hardened DOMPurify (renderedBody is the
             only producer of this string and has no other path). Nothing reaches the
             DOM unsanitized. v-html sanctioned via eslint.config.js file override. -->
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
import { useSanitizeMarkdown } from '@/composables/useSanitizeMarkdown'
import { getAgentColor } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'
import { BATON_FOCUS, MENTION_FOCUS, APPROVAL_FOCUS } from '@/components/hub/hubThreadRoute'

/**
 * FE-9436: what the one flag SAYS, per reason.
 *
 * The hand-off's line is FE-9410's, word for word — the operator ruling harmonised the
 * surface, not the wording of a notification that was already right. The other two are
 * deliberately not variations on it: "Waiting on you" is a claim about whose turn it is,
 * and only the baton can make it.
 */
const FOCUS_COPY = {
  [BATON_FOCUS]: 'Waiting on you',
  [MENTION_FOCUS]: 'You were mentioned',
  [APPROVAL_FOCUS]: 'Needs your approval',
}

const props = defineProps({
  // Explicit thread to render (Phase 5 / D1(a) read-only surfaces). Falls back
  // to the store's selected thread when omitted, so existing callers like
  // HubView.vue (`<ThreadTimeline />` with no props) keep working identically.
  threadId: { type: String, default: null },
  // FE-9368 (D): free-text filter over the messages ALREADY loaded for this thread.
  // Empty string means "show everything", which is the default every other caller
  // gets by not passing it at all.
  search: { type: String, default: '' },
  // FE-9410: the message the operator was sent here to read, when they arrived from an
  // "Action needed" notification. Null for every ordinary arrival, which is why nothing
  // is marked unless a notification actually pointed at a post.
  focusMessageId: { type: String, default: null },
  // FE-9436: WHY they were sent — handover (`baton`), mention, or approval. It decides
  // the words and the tint on the flag above and nothing else; it cannot cause a mark,
  // because `focusMessageId` remains the only thing that does.
  focusReason: { type: String, default: BATON_FOCUS },
})

/**
 * FE-9436: the reason actually rendered.
 *
 * A reason this component has no copy for is treated as the hand-off, which is the
 * pre-FE-9436 behaviour of the only caller that can reach it — FE-9410's own spec mounts
 * with a focus id and no reason at all. Production cannot land here: HubView derives the
 * id and the reason from the SAME query, and `resolveFocusMessageId` returns no id
 * unless that query named a reason this module recognises.
 */
const resolvedFocusReason = computed(() =>
  FOCUS_COPY[props.focusReason] ? props.focusReason : BATON_FOCUS,
)

const commHub = useCommHubStore()
const { sanitizeMarkdown } = useSanitizeMarkdown()
const timelineEl = ref(null)

const effectiveThreadId = computed(() => props.threadId || commHub.selectedThreadId)
const messages = computed(() => {
  if (!effectiveThreadId.value) return []
  return commHub.messagesFor(effectiveThreadId.value)
})

// FE-9410: per-message elements, so a focused post can be scrolled to by id.
const messageEls = new Map()
function setMessageRef(messageId, el) {
  if (el) messageEls.set(messageId, el)
  else messageEls.delete(messageId)
}

/**
 * FE-9410: bring the focused post into view. Returns whether it found one, because the
 * bottom-scroll below hands over to it rather than both firing — two scrolls in one
 * frame is how a timeline lands somewhere neither of them meant.
 */
function scrollToFocused() {
  const el = props.focusMessageId ? messageEls.get(props.focusMessageId) : null
  if (!el || typeof el.scrollIntoView !== 'function') return false
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  return true
}

// Auto-scroll to bottom when new messages arrive
watch(
  () => messages.value.length,
  () => {
    nextTick(() => {
      if (scrollToFocused()) return
      if (timelineEl.value) {
        timelineEl.value.scrollTop = timelineEl.value.scrollHeight
      }
    })
  },
)

// The focus can also arrive AFTER the messages do — the operator clicks the banner from
// inside the Hub, and the thread is already loaded when the target is named.
watch(
  () => props.focusMessageId,
  () => nextTick(scrollToFocused),
)

// ---- display helpers ----

// WHAT the author is comes from the server: `from_kind` ('agent' | 'user') is resolved
// at post time, where the backend actually knows which attribution branch ran. The
// client does not decide this and must not try to.
//
// It used to guess from the SHAPE of from_agent_id ("looks like a UUID therefore
// human"), which broke the moment agents began posting under their own agent_id UUID:
// those posts rendered as the HUMAN user, right-aligned and brand-yellow, with a raw
// UUID for a name. The guess was unfixable on this side — from_agent_id is a
// self-declared functional key (recipient self-exclusion, baton matching, read
// cursors), so its shape carries no information about the author. BE-9289a made the
// server answer the question instead, and every poster is now registered, so the
// heuristic is gone rather than merely demoted to a fallback.
//
// The participant directory is still consulted, but only for the friendlier NAME and
// the harness the poster connected from.
function authorFor(message) {
  const p = commHub
    .participantsFor(effectiveThreadId.value)
    .find((x) => x.participant_id === message.from_agent_id)
  return {
    isUser: message.from_kind === 'user',
    name: p?.display_name || message.from_display_name || message.from_agent_id,
    harness: p?.harness || '',
  }
}

// `generic` is the resolver's fail-safe floor, not a harness name — label it. An
// author with no participant row shows NO harness rather than a guessed one.
function harnessLabel(harness) {
  if (!harness) return ''
  return harness === 'generic' ? 'Generic Harness' : harness
}

// A run of posts by the same author, close in time, reads as one person speaking:
// the continuation keeps the column but drops the badge and the header row.
const GROUP_WINDOW_MS = 5 * 60 * 1000

function continuesRun(message, previous) {
  if (!previous) return false
  if (previous.from_agent_id !== message.from_agent_id) return false
  if (previous.from_kind !== message.from_kind) return false
  if (message.requires_action) return false
  const a = new Date(previous.created_at).getTime()
  const b = new Date(message.created_at).getTime()
  if (Number.isNaN(a) || Number.isNaN(b)) return false
  return b - a < GROUP_WINDOW_MS
}

// Long posts fold to their first sentence until the reader asks for the rest.
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

// FE-9368 (D): the in-thread filter. Client-side over the timeline already loaded —
// the whole history for the open thread is in the store, so there is nothing to fetch
// and no debounce to get wrong. Matches the message text OR the author's RESOLVED name
// (what the operator actually sees on the post), not the raw from_agent_id they never
// read. A blank query means no filter at all.
const filteredMessages = computed(() => {
  const q = String(props.search || '').trim().toLowerCase()
  if (!q) return messages.value
  return messages.value.filter(
    (m) =>
      String(m.content || '').toLowerCase().includes(q) ||
      String(authorFor(m).name || '').toLowerCase().includes(q),
  )
})

// Enrich the visible messages with resolved author identity so the template binds
// off stable per-message fields instead of re-resolving per node.
//
// Grouping is computed over the FILTERED list on purpose: with a filter on, the post
// above a message on screen is its neighbour in that list, and grouping against the
// unfiltered one would hide the author badge of a post whose predecessor is not shown.
const decoratedMessages = computed(() =>
  filteredMessages.value.map((m, i) => {
    const author = authorFor(m)
    return {
      ...m,
      _isUser: author.isUser,
      _name: author.name,
      _harness: author.isUser ? '' : harnessLabel(author.harness),
      _isDirect: m.message_type === 'direct',
      _grouped: continuesRun(m, filteredMessages.value[i - 1]),
      _foldable: (m.content || '').length > FOLD_THRESHOLD,
    }
  }),
)

function avatarInitials(name) {
  if (!name) return '?'
  const parts = name.split(/[-_\s]+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return name.slice(0, 2).toUpperCase()
}

// Fallback to orchestrator color (the canonical default from agentColors.js)
const FALLBACK_HEX = getAgentColor('orchestrator')?.hex

function avatarStyle(name) {
  const colorObj = getAgentColor(name)
  const hex = colorObj?.hex || FALLBACK_HEX
  return {
    backgroundColor: hexToRgba(hex, 0.2),
    color: hex,
    borderRadius: '8px',
  }
}

// Direct chip: lavender (reviewer). Hex derived from getAgentColor() — no hardcoded hex.
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
