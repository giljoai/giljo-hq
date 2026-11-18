<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.
-->
<template>
  <div
    class="system-banner-alert"
    :class="[`system-banner-alert--${notice.severity}`, { 'is-expandable': expandable }]"
    role="alert"
    data-testid="system-banner"
    @click="onBarClick"
  >
    <div class="system-banner-alert__content">
      <img src="/icons/Giljo_YW_Face.svg" alt="" class="system-banner-alert__avatar" />
      <span
        :id="messageId"
        ref="messageEl"
        class="system-banner-alert__text"
        :class="{ 'is-expanded': expanded }"
        >{{ message }}</span
      >
      <BannerExpandToggle
        v-if="expandable"
        :expanded="expanded"
        :controls="messageId"
        @toggle="toggle"
      />
    </div>

    <div class="system-banner-alert__actions">
      <button
        v-if="hasCta"
        data-testid="banner-cta-btn"
        class="system-banner-btn system-banner-btn--cta"
        @click="$emit('cta')"
      >
        {{ notice.cta_label || 'Go to settings' }}
      </button>

      <button
        v-if="notice.dismissible"
        data-testid="banner-dismiss-btn"
        class="system-banner-btn system-banner-btn--dismiss"
        aria-label="Dismiss notification"
        @click="$emit('dismiss')"
      >
        <v-icon icon="mdi-close" size="16" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useBannerExpand } from '@/composables/useBannerExpand'
import BannerExpandToggle from './BannerExpandToggle.vue'

const props = defineProps({
  notice: { type: Object, required: true },
  hasCta: { type: Boolean, default: false },
})
defineEmits(['cta', 'dismiss'])

const message = computed(() => props.notice.body || props.notice.title)
const { messageEl, messageId, expanded, expandable, toggle, onBarClick } = useBannerExpand(message)
</script>

<style scoped lang="scss">
@use '@/styles/banner-unified' as banner;

@include banner.unified-system-row;
</style>
