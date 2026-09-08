<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.

  LifecycleBannerRow.vue — FE-9538

  One row per project lifecycle moment (staged / activated / implementation
  launched), fed by lifecycleBannerStore -- see that store's doc comment for
  why this is its own ephemeral-row family rather than a Notification row.
  Presentational only, mirroring ApprovalBannerRow.vue's split:
  the parent (SystemStatusBanner) owns the store and passes `rows` down, and
  this component never navigates on its own -- it emits `open`
  with the row, and the parent's click handler carries the project id into
  the actual router.push.
-->
<template>
  <div
    v-for="row in rows"
    :key="row.id"
    class="lifecycle-banner-row"
    role="alert"
    data-testid="lifecycle-banner"
    @click="$emit('open', row)"
  >
    <div class="lifecycle-banner-row__content">
      <img src="/icons/Giljo_YW_Face.svg" alt="" class="lifecycle-banner-row__avatar" />
      <span
        v-if="row.taxonomyAlias"
        class="lifecycle-banner-row__pill"
        data-testid="lifecycle-banner-pill"
      >
        {{ row.taxonomyAlias }}
      </span>
      <span class="lifecycle-banner-row__text" data-testid="lifecycle-banner-text">
        {{ messageFor(row) }}
      </span>
    </div>

    <div class="lifecycle-banner-row__actions">
      <button
        data-testid="lifecycle-banner-cta"
        class="unified-banner-btn unified-banner-btn--cta"
        @click.stop="$emit('open', row)"
      >
        Go to job
      </button>
      <button
        data-testid="lifecycle-banner-dismiss"
        class="unified-banner-btn unified-banner-btn--dismiss"
        aria-label="Dismiss"
        @click.stop="$emit('dismiss', row.id)"
      >
        <v-icon icon="mdi-close" size="16" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { useLifecycleBannerStore } from '@/stores/lifecycleBannerStore'

defineProps({
  rows: {
    type: Array,
    default: () => [],
  },
})
defineEmits(['open', 'dismiss'])

const lifecycleBannerStore = useLifecycleBannerStore()

/**
 * "{taxonomy and title} project {has started/is ready to launch/...}" -- the
 * operator's own requested wording. A cache-miss project (never opened this
 * session) degrades to "A project" rather than dropping the row.
 */
function messageFor(row) {
  const name = row.title || 'A project'
  return `${name} ${lifecycleBannerStore.momentLabel(row.moment)}`
}
</script>

<style scoped lang="scss">
@use '@/styles/banner-unified' as banner;

.lifecycle-banner-row {
  @include banner.unified-banner-chrome;
  cursor: pointer;

  &__content {
    @include banner.unified-banner-content;
  }

  &__avatar {
    flex-shrink: 0;
    width: 18px;
    height: 18px;
    display: block;
  }

  &__text {
    @include banner.unified-banner-message;
  }

  &__pill {
    flex-shrink: 0;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.3px;
    color: var(--color-accent-primary);
    background: rgba(255, 255, 255, 0.08);
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }
}
</style>
