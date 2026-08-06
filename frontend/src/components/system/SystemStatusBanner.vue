<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.

  IMP-5037b: SystemStatusBanner is now a filtered view of bannerNotifications.
  Each server-emitted sub-banner (pending_migrations, update_available,
  skills_drift, context_tuning_due) is rendered by iterating the notification
  rows the backend emits. For those SERVER rows there is no client-side status
  polling for banner VISIBILITY; the Notification row IS the source of truth for
  whether the banner should be shown.

  FE-9202: the banner is voiced as "Gil" — every row leads with the Gil avatar.
  It also folds in the tutorial "activate your product" nudge as a CLIENT-ARMED
  row (see the marked section below): unlike the server rows, its visibility is
  driven by useTutorialState localStorage (armed on tutorial exit, retired on
  first product activation), not by a Notification row. One banner strip, one
  visual language.
-->
<template>
  <div
    v-if="visibleBanners.length > 0 || showTutorialRow || showIntegRow || showAgentRow"
    class="system-status-banner"
  >
    <div
      v-for="n in visibleBanners"
      :key="n.id"
      class="system-banner-alert"
      :class="`system-banner-alert--${n.severity}`"
      role="alert"
      data-testid="system-banner"
    >
      <div class="system-banner-alert__content">
        <img src="/icons/Giljo_YW_Face.svg" alt="" class="system-banner-alert__avatar" />
        <span class="system-banner-alert__text">{{ n.body || n.title }}</span>
      </div>

      <div class="system-banner-alert__actions">
        <button
          v-if="hasCta(n)"
          data-testid="banner-cta-btn"
          class="system-banner-btn system-banner-btn--cta"
          @click="goTo(n)"
        >
          {{ n.cta_label || 'Go to settings' }}
        </button>

        <button
          v-if="n.dismissible"
          data-testid="banner-dismiss-btn"
          class="system-banner-btn system-banner-btn--dismiss"
          aria-label="Dismiss notification"
          @click="dismiss(n)"
        >
          <v-icon icon="mdi-close" size="16" />
        </button>
      </div>
    </div>

    <!-- FE-9202: CLIENT-ARMED tutorial "activate your product" row. Visibility
         comes from useTutorialState localStorage, NOT a Notification row. -->
    <div
      v-if="showTutorialRow"
      class="system-banner-alert system-banner-alert--info"
      role="alert"
      data-testid="tutorial-activate-banner"
    >
      <div class="system-banner-alert__content">
        <img src="/icons/Giljo_YW_Face.svg" alt="" class="system-banner-alert__avatar" />
        <span class="system-banner-alert__text">Next: activate your product</span>
      </div>

      <div class="system-banner-alert__actions">
        <button
          data-testid="tutorial-activate-cta"
          class="system-banner-btn system-banner-btn--cta"
          @click="goToProducts"
        >
          Go to Products
        </button>
        <button
          data-testid="tutorial-activate-dismiss"
          class="system-banner-btn system-banner-btn--dismiss"
          aria-label="Dismiss"
          @click="dismissTutorialRow"
        >
          <v-icon icon="mdi-close" size="16" />
        </button>
      </div>
    </div>

    <!-- FE-9202: CLIENT-ARMED onboarding nudges, converted from the former Home
         popup cards (OnboardingReminders). Trigger + dismissal cadence are
         byte-preserved via useOnboardingReminders (same localStorage state). -->
    <div
      v-if="showIntegRow"
      class="system-banner-alert system-banner-alert--info"
      role="alert"
      data-testid="onboarding-integration-banner"
    >
      <div class="system-banner-alert__content">
        <img src="/icons/Giljo_YW_Face.svg" alt="" class="system-banner-alert__avatar" />
        <span class="system-banner-alert__text">
          Enable Git and Serena MCP in your connect settings to give your agents more context.
        </span>
      </div>
      <div class="system-banner-alert__actions">
        <button
          data-testid="onboarding-integration-cta"
          class="system-banner-btn system-banner-btn--cta"
          @click="goToTools"
        >
          Go to Tools
        </button>
        <button
          data-testid="onboarding-integration-dismiss"
          class="system-banner-btn system-banner-btn--dismiss"
          aria-label="Dismiss"
          @click="dismissIntegRow"
        >
          <v-icon icon="mdi-close" size="16" />
        </button>
      </div>
    </div>

    <div
      v-if="showAgentRow"
      class="system-banner-alert system-banner-alert--info"
      role="alert"
      data-testid="onboarding-agent-banner"
    >
      <div class="system-banner-alert__content">
        <img src="/icons/Giljo_YW_Face.svg" alt="" class="system-banner-alert__avatar" />
        <span class="system-banner-alert__text">
          Tune your agent templates and product context in Tools — make the defaults yours.
        </span>
      </div>
      <div class="system-banner-alert__actions">
        <button
          data-testid="onboarding-agent-cta"
          class="system-banner-btn system-banner-btn--cta"
          @click="goToTools"
        >
          Go to Tools
        </button>
        <button
          data-testid="onboarding-agent-dismiss"
          class="system-banner-btn system-banner-btn--dismiss"
          aria-label="Dismiss"
          @click="dismissAgentRow"
        >
          <v-icon icon="mdi-close" size="16" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useNotificationStore } from '@/stores/notifications'
import { useUserStore } from '@/stores/user'
import { useProductStore } from '@/stores/products'
import configService from '@/services/configService'
import api from '@/services/api'
import { isSaasModeValue } from '@/composables/useGiljoMode'
import {
  ACTIVATE_BREADCRUMB_ARMED_EVENT,
  clearActivateBreadcrumb,
  isActivateBreadcrumbArmed,
} from '@/composables/useTutorialState'
import { useOnboardingReminders } from '@/composables/useOnboardingReminders'
import { useIntegrationStatus } from '@/composables/useIntegrationStatus'
import { resolveNotificationRoute } from '@/components/navigation/notificationRouting'

const router = useRouter()
const notifStore = useNotificationStore()
const userStore = useUserStore()
const productStore = useProductStore()

/** CE system notification types handled by this banner. */
const CE_SYSTEM_TYPES = new Set([
  'system.pending_migrations',
  'system.update_available',
  'system.skills_drift',
  // FE-9202: 14-day context-tuning reminder (both editions).
  'system.context_tuning_due',
])

/**
 * BE-6031c: SaaS defense-in-depth.
 * update_available and pending_migrations are CE self-host concepts; the
 * authoritative backend gate already suppresses them in SaaS mode.  This
 * computed provides a secondary render-layer guard so the banner never
 * displays those types even if a stale notification row survives a mode
 * transition.  skills_drift is retained: SaaS operators still need to know
 * when skills are out of sync. context_tuning_due is retained: context tuning
 * is a core concern in both editions (FE-9202).
 */
const giljoMode = ref('ce')
onMounted(async () => {
  try {
    await configService.fetchConfig()
    giljoMode.value = configService.getGiljoMode()
  } catch {
    giljoMode.value = 'ce'
  }
})

const ALLOWED_TYPES = computed(() => {
  if (isSaasModeValue(giljoMode.value)) {
    return new Set(['system.skills_drift', 'system.context_tuning_due'])
  }
  return CE_SYSTEM_TYPES
})

/** Defense-in-depth role guard. Server already enforces this; we guard render too. */
function userHasRole(roleFilter) {
  if (!roleFilter) return true
  const role = userStore.currentUser?.role?.toLowerCase() ?? ''
  return role === roleFilter.toLowerCase()
}

/**
 * Filter bannerNotifications down to allowed types visible to this user.
 * FE-9202 co-occurrence guard: the recurring system.context_tuning_due row is
 * suppressed whenever the one-shot tune-agents nudge is eligible — the two are
 * different nudges and must not stack in the strip; the one-shot wins and the
 * recurring one waits a tick.
 */
const visibleBanners = computed(() =>
  notifStore.bannerNotifications.filter(
    (n) =>
      ALLOWED_TYPES.value.has(n.type) &&
      userHasRole(n.role_filter) &&
      !(n.type === 'system.context_tuning_due' && showAgentRow.value),
  ),
)

/** GitHub releases landing page; fallback when a row carries no release_url. */
const RELEASES_URL = 'https://github.com/giljoai/giljo-hq/releases'

/**
 * External CTA target for "update available" banners. Self-host upgrades happen
 * in the user's terminal (git pull + restart, or re-run the installer), so the
 * button links out to GitHub releases rather than deep-linking in-app.
 * Returns null for every other banner type (those use an in-app cta_route).
 */
function externalHref(n) {
  if (n.type === 'system.update_available') {
    return n.payload?.release_url || RELEASES_URL
  }
  return null
}

/** A banner shows a CTA button if it has an in-app route OR an external link. */
function hasCta(n) {
  return Boolean(n.cta_route) || Boolean(externalHref(n))
}

function goTo(n) {
  const href = externalHref(n)
  if (href) {
    window.open(href, '_blank', 'noopener')
    return
  }
  // FE-9222: resolve entity-aware destinations through the SAME shared map the
  // notification bell uses (notificationRouting.js) — e.g. the context-tuning
  // banner opens the Products tune dialog for its product. Plain system banners
  // (pending_migrations / skills_drift) are not in the map, so they fall back to
  // their bare cta_route named-route, unchanged.
  const resolved = resolveNotificationRoute(n)
  if (resolved) {
    router.push(resolved)
    return
  }
  if (n.cta_route) {
    router.push({ name: n.cta_route })
  }
}

function dismiss(n) {
  notifStore.markDismissed(n.id)
}

// ── FE-9202: client-armed tutorial "activate your product" row ───────────────
// Byte-preserved arm/retire semantics from the former TutorialActivateBreadcrumb:
// visible when the breadcrumb is armed AND no product is active; first activation
// retires it for good.
const showTutorialRow = ref(isActivateBreadcrumbArmed() && !productStore.activeProduct)

// FE-9320: this banner is mounted in DefaultLayout OUTSIDE <router-view> and
// carries no :key, so it never remounts — the ref above is read exactly once,
// at app start. The breadcrumb is armed LATER (leaving the tutorial by the
// manual-form door), so without this listener the nudge could never appear in
// the session that armed it. armActivateBreadcrumb() dispatches this event.
function syncTutorialRow() {
  showTutorialRow.value = isActivateBreadcrumbArmed() && !productStore.activeProduct
}

onMounted(() => window.addEventListener(ACTIVATE_BREADCRUMB_ARMED_EVENT, syncTutorialRow))
onBeforeUnmount(() => window.removeEventListener(ACTIVATE_BREADCRUMB_ARMED_EVENT, syncTutorialRow))

function dismissTutorialRow() {
  clearActivateBreadcrumb()
  showTutorialRow.value = false
}

function goToProducts() {
  router.push('/Products')
}

watch(
  () => productStore.activeProduct,
  (active) => {
    if (active) dismissTutorialRow()
  },
)

// ── FE-9202: onboarding nudge rows (converted from the Home popup cards) ──────
// Cadence + dismissal state come VERBATIM from useOnboardingReminders (same
// localStorage keys), so a user who already dismissed the popups never sees them
// reborn as banners. This banner is layout-mounted, so the trigger inputs are
// fetched ONCE per session and only when a card could still show.
const {
  showIntegrationReminder: integReminderCheck,
  showAgentReminder: agentReminderCheck,
  dismissIntegrationReminder,
  dismissAgentReminder,
} = useOnboardingReminders()
const {
  gitEnabled,
  serenaEnabled,
  resolved: integStatusResolved,
  refresh: refreshIntegrationStatus,
} = useIntegrationStatus({
  immediate: false,
})

const hasProjects = ref(false)
const hasCompletedProject = ref(false)
const integHidden = ref(false)
const agentHidden = ref(false)

// Integration nudge: >=1 project AND NOT(git AND serena enabled), gated by the
// composable's dismissal cadence (count<2 / 2-day resurface).
//
// FE-9233: integStatusResolved is load-bearing, do not drop it. hasProjects is
// set by the dashboard read BEFORE refreshIntegrationStatus() is awaited, so
// without this gate the row renders for one tick against the composable's
// default-false git/serena and then vanishes -- the reported flash. `resolved`
// is also false when the status fetch ERRORED, which keeps a fully-configured
// box from being nagged during a transient outage. A nudge is optional UI:
// when the status is unknown, show nothing.
const showIntegRow = computed(
  () =>
    !integHidden.value &&
    integStatusResolved.value &&
    integReminderCheck.value(hasProjects.value) &&
    !(gitEnabled.value && serenaEnabled.value),
)
// Tune-agents nudge: first completed project, one-shot, permanent after dismiss.
const showAgentRow = computed(() => !agentHidden.value && agentReminderCheck.value(hasCompletedProject.value))

function goToTools() {
  router.push('/tools')
}

function dismissIntegRow() {
  dismissIntegrationReminder()
  integHidden.value = true
}

function dismissAgentRow() {
  dismissAgentReminder()
  agentHidden.value = true
}

// Load the nudge trigger inputs ONCE, gated so a permanently-dismissed card
// fires no network call. Driven by a watch on effectiveProductId (not onMounted)
// because the banner mounts app-wide before the product store is populated — the
// fetch must wait until a product id is actually available.
let nudgeInputsLoaded = false
async function loadNudgeInputs() {
  if (nudgeInputsLoaded) return
  // Optimistic gate: could either card show at all given its dismissal state?
  // (Pass true so we test the dismissal cadence, not the not-yet-loaded data.)
  const couldInteg = integReminderCheck.value(true)
  const couldAgent = agentReminderCheck.value(true)
  if (!couldInteg && !couldAgent) return // dismissed / cooling down — never fetch

  const pid = productStore.effectiveProductId
  if (!pid) return // no product yet — the watcher re-runs when one loads
  nudgeInputsLoaded = true

  try {
    const resp = await api.stats.getDashboard(pid)
    const dist = resp.data?.project_status_dist || {}
    const total = Object.values(dist).reduce((a, b) => a + b, 0)
    hasProjects.value = total > 0
    hasCompletedProject.value = (dist.completed || 0) > 0
  } catch {
    /* keep both false — nudges simply stay hidden on a stats read failure */
  }

  if (couldInteg) {
    try {
      await refreshIntegrationStatus()
    } catch {
      /* keep git/serena false */
    }
  }
}

watch(() => productStore.effectiveProductId, loadNudgeInputs, { immediate: true })
</script>

<style scoped lang="scss">
@use '@/styles/banner-unified' as banner;

.system-status-banner {
  position: sticky;
  top: 0;
  z-index: 100;
}

.system-banner-alert {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 16px;
  font-size: 13px;
  border-radius: 0;
  // FE-6012: tint-over-surface fill (matches avatar-menu account-status notice exactly)
  background: var(--banner-bg);
  --smooth-border-color: var(--banner-border);

  &__content {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1;
    min-width: 0;
  }

  // FE-9202: Gil avatar — the banner speaks in Gil's voice (generic-agent branding rule).
  &__avatar {
    flex-shrink: 0;
    width: 18px;
    height: 18px;
    display: block;
  }

  &__text {
    // Light text on the translucent tint over the dark app surface → high contrast.
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
