<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.
-->
<template>
  <div
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
      <span
        :id="messageId"
        ref="messageEl"
        class="lifecycle-banner-row__text"
        :class="{ 'is-expanded': expanded }"
        data-testid="lifecycle-banner-text"
        @click="onTextClick"
      >
        {{ message }}
      </span>
      <BannerExpandToggle
        v-if="expandable"
        :expanded="expanded"
        :controls="messageId"
        @toggle="toggle"
      />
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
import { computed } from 'vue'
import { useLifecycleBannerStore } from '@/stores/lifecycleBannerStore'
import { useBannerExpand } from '@/composables/useBannerExpand'
import BannerExpandToggle from './BannerExpandToggle.vue'

const props = defineProps({
  row: {
    type: Object,
    required: true,
  },
})
defineEmits(['open', 'dismiss'])

const lifecycleBannerStore = useLifecycleBannerStore()

const message = computed(
  () => `${props.row.title || 'A project'} ${lifecycleBannerStore.momentLabel(props.row.moment)}`,
)
const { messageEl, messageId, expanded, expandable, toggle, onTextClick } = useBannerExpand(message)
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
