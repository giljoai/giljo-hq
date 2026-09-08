<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.

  ThreadPostBannerRow.vue — FE-9586

  The row for thread-post signals: somebody NAMED you, or directed an
  action-request at you. The banner that mention and directed-ask popouts had
  never had, which is why FE-9553 could only ship them event-shaped with a
  ten-minute TTL instead of as projections of banner state.

  ONE ROW FOR BOTH CLASSES, not two. The one-live-surface rule and the fold's
  never-stack rule both push the same way, and the operator's decision is the
  same either way: an agent is waiting on you in a thread, go look. The wording
  distinguishes them; the row does not multiply.

  Presentational, like its ApprovalBannerRow sibling: the parent owns the
  projection (its row count also feeds the FE-9377 space reservation), passes
  the lists down, and this emits `open` rather than navigating (ruling 3 — the
  UI never auto-navigates on agent activity; banners announce, the user chooses
  to look).

  Same visual language as the baton and raised-hand rows on purpose — one look
  for "an agent needs you".

  FE-9589: this row IS dismissible, superseding the reasoning it carried before
  ("not dismissible ... it is a live read of server state and it leaves when
  the state does. Reading the thread is what clears it"). That was true in
  principle and false in practice: with two or more entries live the row's own
  CTA could not perform the read that clears it -- `primaryThreadId` is null,
  so the parent landed on the Hub LIST, which selects no thread and writes no
  watermark. Agents keep posting, so the row was permanent. Both halves are
  fixed here: the CTA now advances the watermark across every thread it names
  (commHubStore.markThreadsRead), and the operator can close the strip outright
  without that being the only escape. Dismissal silences the announcement only
  -- the posts stay unread, the threads stay in the Hub, and the bell keeps its
  rows. The parent records it (bannerDismissStore, per user, survives a
  reload); this component only emits.
-->
<template>
  <div
    v-if="rowCount > 0"
    class="thread-post-banner-row"
    role="alert"
    data-testid="thread-post-banner"
    @click="$emit('open', primaryThreadId)"
  >
    <div class="thread-post-banner-row__content">
      <v-icon icon="mdi-hand-back-right-outline" size="18" class="thread-post-banner-row__hand" />
      <span
        v-for="chatId in visibleChatIds"
        :key="chatId"
        class="thread-post-banner-row__pill"
        data-testid="thread-post-banner-pill"
      >
        {{ chatId }}
      </span>
      <span
        v-if="pillOverflowCount > 0"
        class="thread-post-banner-row__pill thread-post-banner-row__pill--overflow"
        data-testid="thread-post-banner-pill-overflow"
      >
        +{{ pillOverflowCount }}
      </span>
      <span class="thread-post-banner-row__text" data-testid="thread-post-banner-text">
        {{ message }}
      </span>
    </div>

    <div class="thread-post-banner-row__actions">
      <button
        data-testid="thread-post-cta"
        class="unified-banner-btn unified-banner-btn--cta"
        @click.stop="$emit('open', primaryThreadId)"
      >
        {{ cta }}
      </button>
      <button
        data-testid="thread-post-banner-dismiss"
        class="unified-banner-btn unified-banner-btn--dismiss"
        aria-label="Dismiss"
        @click.stop="$emit('dismiss')"
      >
        <v-icon icon="mdi-close" size="16" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

/** One row, never a stack — the same cap and "+N" tail the approval row uses. */
const MAX_PILLS = 4

const props = defineProps({
  /** [{thread_id, chat_id, message_ids}] — already filtered for fold visibility. */
  mentions: {
    type: Array,
    default: () => [],
  },
  /** [{thread_id, chat_id}] — pending DIRECTED action-requests. */
  directedAsks: {
    type: Array,
    default: () => [],
  },
})
defineEmits(['open', 'dismiss'])

// Directed asks first: an explicit ask of you outranks being named in passing,
// and when both are live the CTA should land on the one that obligates you.
const entries = computed(() => [...props.directedAsks, ...props.mentions])
const rowCount = computed(() => entries.value.length)

/** Where the CTA goes. Null when several are live — the Hub list is the honest landing. */
const primaryThreadId = computed(() =>
  rowCount.value === 1 ? entries.value[0]?.thread_id || null : null,
)

const message = computed(() => {
  const asks = props.directedAsks.length
  const named = props.mentions.length

  // Say which KIND when only one kind is live; count threads when both are, because
  // "2 threads need you" is true and "an agent asked you and also named you" is a
  // sentence nobody wants in a 24px strip.
  if (asks && named) {
    const total = asks + named
    return `${total} chat threads are waiting for you`
  }
  if (asks) {
    return asks > 1 ? `${asks} agents are waiting on your answer` : 'An agent is waiting on your answer'
  }
  if (named > 1) return `You were mentioned in ${named} chat threads`
  return 'You were mentioned in a chat thread'
})

const cta = computed(() => (rowCount.value > 1 ? 'Open Message Hub' : 'Open thread'))

const chatIds = computed(() => {
  const seen = new Set()
  const ids = []
  for (const entry of entries.value) {
    const id = entry?.chat_id
    if (id && !seen.has(id)) {
      seen.add(id)
      ids.push(id)
    }
  }
  return ids
})

const visibleChatIds = computed(() => chatIds.value.slice(0, MAX_PILLS))
const pillOverflowCount = computed(() => Math.max(0, chatIds.value.length - MAX_PILLS))
</script>

<style scoped lang="scss">
@use '@/styles/banner-unified' as banner;

.thread-post-banner-row {
  @include banner.unified-banner-chrome;
  cursor: pointer;

  &__content {
    @include banner.unified-banner-content;
  }

  &__hand {
    @include banner.unified-banner-icon;
  }

  &__text {
    @include banner.unified-banner-message;
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }

  // The CHAT id (CHT-0001), a fixed-width identifier and never agent-authored
  // text, so the accent tint rather than a status colour is correct — same
  // reasoning as the approval row's project pill.
  &__pill {
    flex-shrink: 0;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.3px;
    color: var(--color-accent-primary);
    background: rgba(255, 255, 255, 0.08);

    &--overflow {
      color: var(--text-muted);
    }
  }
}
</style>
