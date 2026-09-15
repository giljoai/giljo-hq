<template>
  <span
    v-if="dates.created || dates.lastMessage"
    class="thread-dates"
    :class="`thread-dates--${size}`"
    data-testid="thread-dates"
  >
    <span v-if="dates.created" class="thread-dates__item" data-testid="thread-dates-created">
      <span class="thread-dates__label">{{ CREATED_LABEL }}</span>
      <time :datetime="thread.created_at">{{ dates.created }}</time>
    </span>
    <span v-if="dates.lastMessage" class="thread-dates__item" data-testid="thread-dates-last-message">
      <span class="thread-dates__label">{{ LAST_MESSAGE_LABEL }}</span>
      <time :datetime="thread.last_message?.created_at || thread.last_activity_at">{{ dates.lastMessage }}</time>
    </span>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { threadDates, CREATED_LABEL, LAST_MESSAGE_LABEL } from '@/components/hub/hubDateTime'

const props = defineProps({
  thread: { type: Object, required: true },
  size: { type: String, default: 'sm', validator: (v) => ['sm', 'md'].includes(v) },
})

const dates = computed(() => threadDates(props.thread))
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.thread-dates {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  font-family: 'IBM Plex Mono', monospace;
  color: var(--text-muted, #{$color-text-secondary});

  &--sm { font-size: 0.6875rem; } // 11 — the floor
  &--md { font-size: 0.75rem; } // 12

  &__item { white-space: nowrap; }

  &__label {
    margin-right: 5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    opacity: 0.85; // the label is quieter than its value, at the same size
  }
}
</style>
