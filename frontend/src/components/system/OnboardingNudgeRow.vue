<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.
-->
<template>
  <div
    class="system-banner-alert system-banner-alert--info"
    :class="{ 'is-expandable': expandable }"
    role="alert"
    :data-testid="rowTestid"
    @click="onBarClick"
  >
    <div class="system-banner-alert__content">
      <img src="/icons/Giljo_YW_Face.svg" alt="" class="system-banner-alert__avatar" />
      <span
        :id="messageId"
        ref="messageEl"
        class="system-banner-alert__text"
        :class="{ 'is-expanded': expanded }"
        ><slot
      /></span>
      <BannerExpandToggle
        v-if="expandable"
        :expanded="expanded"
        :controls="messageId"
        @toggle="toggle"
      />
    </div>

    <div class="system-banner-alert__actions">
      <button
        :data-testid="ctaTestid"
        class="system-banner-btn system-banner-btn--cta"
        @click="$emit('cta')"
      >
        {{ ctaLabel }}
      </button>
      <button
        :data-testid="dismissTestid"
        class="system-banner-btn system-banner-btn--dismiss"
        aria-label="Dismiss"
        @click="$emit('dismiss')"
      >
        <v-icon icon="mdi-close" size="16" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { useBannerExpand } from '@/composables/useBannerExpand'
import BannerExpandToggle from './BannerExpandToggle.vue'

defineProps({
  rowTestid: { type: String, required: true },
  ctaTestid: { type: String, required: true },
  ctaLabel: { type: String, required: true },
  dismissTestid: { type: String, required: true },
})
defineEmits(['cta', 'dismiss'])

const { messageEl, messageId, expanded, expandable, toggle, onBarClick } = useBannerExpand()
</script>

<style scoped lang="scss">
@use '@/styles/banner-unified' as banner;

@include banner.unified-system-row;
</style>
