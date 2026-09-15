<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.
-->
<template>
  <div
    v-if="threads.length > 0"
    class="your-turn-banner-row"
    role="alert"
    data-testid="your-turn-banner"
    @click="$emit('open')"
  >
    <div class="your-turn-banner-row__content">
      <v-icon icon="mdi-hand-back-right-outline" size="18" class="your-turn-banner-row__hand" />
      <span class="your-turn-banner-row__text" data-testid="your-turn-banner-text">
        {{ message }}
      </span>
    </div>

    <div class="your-turn-banner-row__actions">
      <button
        data-testid="your-turn-cta"
        class="unified-banner-btn unified-banner-btn--cta"
        @click.stop="$emit('open')"
      >
        {{ cta }}
      </button>
      <button
        data-testid="your-turn-dismiss"
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

import { threadDisplayName } from '@/components/hub/threadDisplayName'

const props = defineProps({
  threads: {
    type: Array,
    default: () => [],
  },
})
defineEmits(['open', 'dismiss'])

const threadLabel = (thread) => threadDisplayName(thread)

const message = computed(() => {
  if (props.threads.length > 1) return 'Multiple chat threads are waiting for you'
  const thread = props.threads[0]
  const author = thread?.last_message?.author
  return author
    ? `${author} is waiting on you in "${threadLabel(thread)}"`
    : `Waiting on you in "${threadLabel(thread)}"`
})

const cta = computed(() => (props.threads.length > 1 ? 'Open Message Hub' : 'Open thread'))
</script>

<style scoped lang="scss">
@use '@/styles/banner-unified' as banner;

.your-turn-banner-row {
  @include banner.unified-banner-chrome;
  // FE-9368: the whole handover strip is the target, not just its button.
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
}
</style>
