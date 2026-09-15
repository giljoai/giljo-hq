<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.
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
      <button
        v-for="pill in visiblePills"
        :key="pill.chat_id"
        type="button"
        class="thread-post-banner-row__pill thread-post-banner-row__pill--link"
        :title="`Open ${pill.chat_id}`"
        :aria-label="`Open thread ${pill.chat_id}`"
        data-testid="thread-post-banner-pill"
        @click.stop="$emit('open', pill.thread_id)"
      >
        {{ pill.chat_id }}
      </button>
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

const MAX_PILLS = 4

const props = defineProps({
  mentions: {
    type: Array,
    default: () => [],
  },
  directedAsks: {
    type: Array,
    default: () => [],
  },
})
defineEmits(['open', 'dismiss'])

const entries = computed(() => [...props.directedAsks, ...props.mentions])
const rowCount = computed(() => entries.value.length)

const primaryThreadId = computed(() =>
  rowCount.value === 1 ? entries.value[0]?.thread_id || null : null,
)

const message = computed(() => {
  const asks = props.directedAsks.length
  const named = props.mentions.length

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

const pills = computed(() => {
  const seen = new Set()
  const out = []
  for (const entry of entries.value) {
    const id = entry?.chat_id
    if (id && !seen.has(id)) {
      seen.add(id)
      out.push({ chat_id: id, thread_id: entry.thread_id || null })
    }
  }
  return out
})

const visiblePills = computed(() => pills.value.slice(0, MAX_PILLS))
const pillOverflowCount = computed(() => Math.max(0, pills.value.length - MAX_PILLS))
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

    // FE-9593: the badge is a button now. Reset the UA chrome, keep the pill look, and
    // say so on hover — an underline is the one affordance every reader recognises.
    &--link {
      border: none;
      font: inherit;
      font-size: 11px;
      font-weight: 700;
      line-height: inherit;
      cursor: pointer;
      transition: background 0.15s ease;

      &:hover,
      &:focus-visible {
        background: rgba(255, 255, 255, 0.16);
        text-decoration: underline;
        outline: none;
      }
    }
  }
}
</style>
