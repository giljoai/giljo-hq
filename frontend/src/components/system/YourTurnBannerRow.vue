<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.

  YourTurnBannerRow.vue — FE-9368 (E), extracted FE-9589

  The Message Hub handover row, app-wide. The Hub's own attention strip and gold
  card only reach an operator who is already in the Hub, and they normally are
  not. Leads with the raised hand rather than the Gil avatar: this row is an
  agent waiting on you, not Gil talking.

  Extracted out of SystemStatusBanner.vue on the ApprovalBannerRow (FE-9511)
  precedent, for the same reason: Guardrail 1, the 800-line cap. It picks up
  the shared banner-unified chrome its two siblings already use, which is what
  "same visual language for an agent needs you" was always describing.

  Presentational: the parent owns the thread list (its count also feeds the
  FE-9377 space reservation) and this emits rather than navigating (ruling 3).

  FE-9589: dismissible, superseding "not dismissible on purpose, it is a live
  read of the baton, so it leaves when the turn does". Still a live read --
  dismissal writes no server state, the baton stays yours, the thread stays in
  the Hub and the bell keeps its row -- but the operator can close the strip
  where it stands. The FE-9589 survey listed four families and missed this one;
  a baton row with no X would have been the last banner nobody could close.

  Edition Scope: Both
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
  /** Non-terminal threads whose baton points at the current user, newest first. */
  threads: {
    type: Array,
    default: () => [],
  },
})
defineEmits(['open', 'dismiss'])

// FE-9436: the shared naming rule. Two copies of a fallback list cannot keep the
// promise below, and one of the two had already drifted into printing a UUID.
const threadLabel = (thread) => threadDisplayName(thread)

// Wording is the Hub's, kept word for word so the two surfaces do not describe
// the same event two different ways.
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
