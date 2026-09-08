<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.

  OnboardingNudgeRow.vue — FE-9552

  The tutorial "activate your product" row and the two converted onboarding
  nudges (FE-9202) were three near-identical copies of the same
  avatar+text+CTA+dismiss shape, extracted out of SystemStatusBanner.vue
  (to keep that file within the project's file-size budget -- the same reason ApprovalBannerRow.vue and
  LifecycleBannerRow.vue were split out before it). Presentational only: the
  parent still owns every trigger condition (localStorage/composable reads),
  dismissal side-effect, and CTA destination -- this component only renders
  whichever ONE of the three is currently on top of the fold and emits `cta`
  / `dismiss` for the parent to act on (FE-9552's "the CTA also dismisses"
  rule lives in the parent's handlers, not here).

  Class names and markup are BYTE-IDENTICAL to the pre-extraction inline rows
  (`system-banner-alert` / `system-banner-btn`, not a renamed set) so every
  existing assertion on this shape (`img.system-banner-alert__avatar`, etc.)
  keeps passing unchanged.
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
