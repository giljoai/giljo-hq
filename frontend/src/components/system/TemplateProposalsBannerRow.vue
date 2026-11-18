<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.
-->
<template>
  <div
    v-if="count > 0"
    class="template-proposals-row"
    role="status"
    data-testid="template-proposals-banner"
    @click="$emit('open')"
  >
    <div class="template-proposals-row__content">
      <v-icon
        icon="mdi-file-document-edit-outline"
        size="18"
        class="template-proposals-row__icon"
      />
      <span
        :id="messageId"
        ref="messageEl"
        class="template-proposals-row__text"
        :class="{ 'is-expanded': expanded }"
        data-testid="template-proposals-banner-text"
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

    <div class="template-proposals-row__actions">
      <button
        data-testid="template-proposals-cta"
        class="unified-banner-btn unified-banner-btn--cta"
        @click.stop="$emit('open')"
      >
        Review
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useBannerExpand } from '@/composables/useBannerExpand'
import BannerExpandToggle from './BannerExpandToggle.vue'

const props = defineProps({
  count: {
    type: Number,
    default: 0,
  },
})
defineEmits(['open'])

const message = computed(() =>
  props.count === 1 ? '1 template change waiting' : `${props.count} template changes waiting`,
)
const { messageEl, messageId, expanded, expandable, toggle, onTextClick } = useBannerExpand(message)
</script>

<style scoped lang="scss">
@use '@/styles/banner-unified' as banner;

.template-proposals-row {
  @include banner.unified-banner-chrome;
  cursor: pointer;

  &__content {
    @include banner.unified-banner-content;
  }

  &__icon {
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
