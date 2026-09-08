<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.

  ApprovalBannerRow.vue — FE-9511

  The raised-hand row's markup, extracted out of SystemStatusBanner.vue
  to keep that file within the project's file-size budget. Presentational: the parent still owns
  useApprovalsStore (its row COUNT feeds the FE-9377 space-reservation logic
  alongside the other rows), and passes the live approvals list down as a
  prop. This component owns only the canned-text + pill rendering
  (useApprovalBannerState.js) and emits `open` on click -- it never navigates
  on its own.

  FE-9589: this row IS dismissible, and that supersedes the reasoning it
  carried before ("a live read of a pending approval, it leaves the instant the
  approval is decided"). The operator ruled that anything on screen must be
  closeable from where it is on screen. Dismissal silences the ANNOUNCEMENT
  only: the approval stays pending, its bell row stays, and the Review
  destination is unchanged -- so the live-read property is intact, it just no
  longer obliges the operator to live with the strip until they act. The parent
  records the dismissal (bannerDismissStore, per user, survives a reload); this
  component only emits, like every other action it has.
-->
<template>
  <div
    v-if="approvals.length > 0"
    class="approval-banner-row"
    role="alert"
    data-testid="approval-banner"
    @click="$emit('open')"
  >
    <div class="approval-banner-row__content">
      <v-icon icon="mdi-hand-back-right-outline" size="18" class="approval-banner-row__hand" />
      <span
        v-for="alias in visibleApprovalPills"
        :key="alias"
        class="approval-banner-row__pill"
        data-testid="approval-banner-pill"
      >
        {{ alias }}
      </span>
      <span
        v-if="approvalPillOverflowCount > 0"
        class="approval-banner-row__pill approval-banner-row__pill--overflow"
        data-testid="approval-banner-pill-overflow"
      >
        +{{ approvalPillOverflowCount }}
      </span>
      <span class="approval-banner-row__text" data-testid="approval-banner-text">
        {{ approvalMessage }}
      </span>
    </div>

    <div class="approval-banner-row__actions">
      <button
        data-testid="approval-cta"
        class="unified-banner-btn unified-banner-btn--cta"
        @click.stop="$emit('open')"
      >
        Review
      </button>
      <button
        data-testid="approval-banner-dismiss"
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
import { useApprovalBannerState } from '@/composables/useApprovalBannerState'

const props = defineProps({
  approvals: {
    type: Array,
    default: () => [],
  },
})
defineEmits(['open', 'dismiss'])

const approvalsRef = computed(() => props.approvals)
const { approvalMessage, visibleApprovalPills, approvalPillOverflowCount } = useApprovalBannerState(approvalsRef)
</script>

<style scoped lang="scss">
@use '@/styles/banner-unified' as banner;

.approval-banner-row {
  @include banner.unified-banner-chrome;
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

  // FE-9511: the project pill -- a fixed-width identifier, never
  // agent-authored text, so the accent tint (not a status color) is correct.
  &__pill {
    flex-shrink: 0;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.3px;
    color: var(--color-accent-primary);
    background: rgba(255, 255, 255, 0.08);

    &--overflow {
      color: var(--text-muted);
    }
  }
}
</style>
