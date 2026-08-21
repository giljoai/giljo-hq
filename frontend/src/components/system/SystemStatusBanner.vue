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
    v-if="renderedRowCount > 0 || pendingReserveRows > 0"
    class="system-status-banner"
  >
    <!-- FE-9368 (E): the Message Hub handover, app-wide. The Hub's own attention strip
         and gold card only reach an operator who is already in the Hub, and they
         normally are not. Leads with the raised hand rather than the Gil avatar: this
         row is an agent waiting on you, not Gil talking. Not dismissible on purpose,
         it is a live read of the baton, so it leaves when the turn does. -->
    <div
      v-if="yourTurnThreads.length > 0"
      class="system-banner-alert system-banner-alert--info system-banner-alert--clickable"
      role="alert"
      data-testid="your-turn-banner"
      @click="openYourTurn"
    >
      <div class="system-banner-alert__content">
        <v-icon icon="mdi-hand-back-right-outline" size="18" class="system-banner-alert__hand" />
        <span class="system-banner-alert__text" data-testid="your-turn-banner-text">
          {{ yourTurnMessage }}
        </span>
      </div>

      <div class="system-banner-alert__actions">
        <button
          data-testid="your-turn-cta"
          class="system-banner-btn system-banner-btn--cta"
          @click.stop="openYourTurn"
        >
          {{ yourTurnCta }}
        </button>
      </div>
    </div>

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

    <!-- FE-9377: reserved space for rows whose eligibility is still resolving.
         Every row type above arms asynchronously (notification fetch, dashboard
         stats + git/serena status, hub thread list), so on a load with a due
         banner the strip used to insert ~30-300ms AFTER the page content painted
         and push the whole page down 42px — sliding content under a stationary
         cursor. The last settled row count is cached in localStorage; the next
         load reserves that height from the FIRST frame and arriving rows fill it
         in place. A stale reservation collapses at the settle timeout — a
         deliberate skeleton collapse beats an insertion under the cursor. -->
    <div
      v-if="pendingReserveRows > 0"
      class="system-banner-skeleton"
      data-testid="banner-reserved-space"
      aria-hidden="true"
      :style="{ height: pendingReserveRows * BANNER_ROW_PX + 'px' }"
    />
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
import { useYourTurnThreads } from '@/composables/useYourTurnThreads'
import { hubThreadRoute } from '@/components/hub/hubThreadRoute'
import { threadDisplayName } from '@/components/hub/threadDisplayName'

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

// ── FE-9368 (E): Message Hub "waiting on you", app-wide ──────────────────────
// A CLIENT-ARMED row like the two above: its visibility is a live read of the baton
// in commHubStore, not a Notification row. That is what makes it behave identically
// in both editions without touching either banner emitter, and it is honest by
// construction: the row cannot outlive the state that justifies it.
const { yourTurnThreads, ensureThreadsLoaded } = useYourTurnThreads()

// The list arrives on the WS event router for a baton handed over while the app is
// open; this covers the other case, a turn that was already yours when the page loaded.
watch(() => userStore.currentUser?.id, (id) => { if (id) ensureThreadsLoaded() }, { immediate: true })

// FE-9436: the shared naming rule. The comment below promises this surface says what the
// Hub says, word for word — a promise two copies of a fallback list cannot keep, and one
// of the two copies had already drifted into printing a UUID.
const threadLabel = (thread) => threadDisplayName(thread)

// Wording is the Hub's, kept word for word so the two surfaces do not describe the
// same event two different ways.
const yourTurnMessage = computed(() => {
  if (yourTurnThreads.value.length > 1) return 'Multiple chat threads are waiting for you'
  const thread = yourTurnThreads.value[0]
  const author = thread?.last_message?.author
  return author
    ? `${author} is waiting on you in "${threadLabel(thread)}"`
    : `Waiting on you in "${threadLabel(thread)}"`
})

const yourTurnCta = computed(() =>
  yourTurnThreads.value.length > 1 ? 'Open Message Hub' : 'Open thread',
)

/**
 * One pending thread opens it; several open the list, since we cannot pick for them.
 *
 * FE-9410: the single-thread route comes from hubThreadRoute() — the same helper the
 * Hub's own attention strip uses — so the two notifications raised by one hand-off land
 * identically. It carries the message context the bare `?thread=` link dropped, which
 * is what left the operator on the Hub instead of at the post waiting for them.
 */
function openYourTurn() {
  const threads = yourTurnThreads.value
  if (threads.length === 1) {
    router.push(hubThreadRoute(threads[0]))
    return
  }
  router.push({ path: '/hub' })
}

// ── FE-9377: first-frame space reservation (no post-paint layout shift) ───────
// Every row above arms asynchronously, so a due banner used to insert after the
// page content painted and shift the whole page down. The cure has to be known
// SYNCHRONOUSLY at first render, and the only sync source of truth is what this
// browser rendered last time: the settled row count is persisted to localStorage
// and the next load reserves that height from the first frame. Rows that arrive
// fill the reserved space in place (pendingReserveRows shrinks as
// renderedRowCount grows — total strip height stays constant).
//
// The settle timer only matters for a STALE reservation (a cached row that no
// longer arms — e.g. dismissed elsewhere, notification resolved server-side):
// the leftover skeleton collapses at SETTLE_TIMEOUT_MS. Deliberately generous
// and deliberately NOT short-circuited by per-source "done" signals — settling
// early right before a slow fetch lands would turn one shift into two.
//
// The record carries the OWNING user id: a shared
// browser with two accounts must not inherit the other account's reserved
// strip. Identity is NOT knowable at first frame (the session cookie is
// httpOnly and /auth/me is async), so the reservation renders optimistically
// from the stored record and is DROPPED the moment the resolved user id
// disagrees with the record's owner — it can never survive into the other
// account's steady state, and writes always stamp the current owner.
/** Height of one banner row (9px padding ×2 + 24px content — all rows nowrap). */
const BANNER_ROW_PX = 42
const RESERVE_STORAGE_KEY = 'giljo_banner_reserved_rows'
/** Reservation cap: never hold more than 3 rows of blank space on spec. */
const RESERVE_ROW_CAP = 3
const SETTLE_TIMEOUT_MS = 4000

/** Reads the stored {u: ownerUserId, n: rowCount} record; malformed → nothing. */
function readReserveRecord() {
  try {
    const rec = JSON.parse(localStorage.getItem(RESERVE_STORAGE_KEY) ?? 'null')
    const n = Number.isFinite(rec?.n) ? Math.min(Math.max(rec.n, 0), RESERVE_ROW_CAP) : 0
    return { owner: typeof rec?.u === 'string' ? rec.u : '', rows: n }
  } catch {
    return { owner: '', rows: 0 }
  }
}

const reserveRecord = readReserveRecord()
const reservedRows = ref(reserveRecord.rows)
const settled = ref(false)

// Drop an inherited reservation as soon as the session's real identity lands.
watch(
  () => userStore.currentUser?.id,
  (id) => {
    if (id && reserveRecord.owner && String(id) !== reserveRecord.owner) {
      reservedRows.value = 0
    }
  },
  { immediate: true },
)

/** Rows currently rendered in the strip (the your-turn strip is one row however many threads). */
const renderedRowCount = computed(
  () =>
    (yourTurnThreads.value.length > 0 ? 1 : 0) +
    visibleBanners.value.length +
    (showTutorialRow.value ? 1 : 0) +
    (showIntegRow.value ? 1 : 0) +
    (showAgentRow.value ? 1 : 0),
)

const pendingReserveRows = computed(() =>
  settled.value ? 0 : Math.max(0, reservedRows.value - renderedRowCount.value),
)

let settleTimer = null
onMounted(() => {
  settleTimer = setTimeout(() => {
    settled.value = true
  }, SETTLE_TIMEOUT_MS)
})
onBeforeUnmount(() => clearTimeout(settleTimer))

// After settle, mirror the rendered count so the NEXT load's first frame
// reserves exactly what this steady state shows (dismissals shrink it, newly
// armed rows grow it). Stamped with the owning user id; no write until the
// session's identity is known.
watch(
  [settled, renderedRowCount, () => userStore.currentUser?.id],
  ([isSettled, count, userId]) => {
    if (isSettled && userId) {
      localStorage.setItem(
        RESERVE_STORAGE_KEY,
        JSON.stringify({ u: String(userId), n: Math.min(count, RESERVE_ROW_CAP) }),
      )
    }
  },
)
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

  // FE-9368: the handover row's raised hand. Brand yellow, the same accent the
  // unified banner chrome gives every other banner icon and the Hub gives the hand.
  &__hand {
    flex-shrink: 0;
    color: var(--color-accent-primary);
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

  // FE-9368: the whole handover strip is the target, not just its button.
  &--clickable {
    cursor: pointer;
  }
}

// FE-9377: reserved space while row eligibility resolves — same tint as the
// rows that will fill it, inert to the pointer.
.system-banner-skeleton {
  background: var(--banner-bg);
  pointer-events: none;
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
