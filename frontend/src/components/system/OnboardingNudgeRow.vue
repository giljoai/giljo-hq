<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.
-->
<template>
  <div
    class="system-banner-alert system-banner-alert--info"
    role="alert"
    :data-testid="rowTestid"
  >
    <div class="system-banner-alert__content">
      <img src="/icons/Giljo_YW_Face.svg" alt="" class="system-banner-alert__avatar" />
      <span class="system-banner-alert__text"><slot /></span>
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
defineProps({
  rowTestid: { type: String, required: true },
  ctaTestid: { type: String, required: true },
  ctaLabel: { type: String, required: true },
  dismissTestid: { type: String, required: true },
})
defineEmits(['cta', 'dismiss'])
</script>

<style scoped lang="scss">
// Verbatim copy of SystemStatusBanner.vue's pre-extraction rules for this
// exact shape -- a mechanical move, not a restyle, so nothing here should
// ever need to change independently of that file's own banner chrome.
.system-banner-alert {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 16px;
  font-size: 13px;
  border-radius: 0;
  background: var(--banner-bg);
  --smooth-border-color: var(--banner-border);

  &__content {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1;
    min-width: 0;
  }

  &__avatar {
    flex-shrink: 0;
    width: 18px;
    height: 18px;
    display: block;
  }

  &__text {
    color: var(--color-text-primary);
    line-height: 1.4;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }
}

.system-banner-btn {
  border: none;
  cursor: pointer;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  transition: opacity 0.15s ease;
  line-height: 1;

  &:hover {
    opacity: 0.85;
  }

  &:focus-visible {
    outline: 2px solid var(--color-accent-primary);
    outline-offset: 2px;
  }

  &--cta {
    background-color: var(--color-accent-primary);
    color: var(--badge-text);
    padding: 5px 12px;
  }

  &--dismiss {
    background: transparent;
    color: rgba(255, 255, 255, 0.7);
    padding: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
}
</style>
