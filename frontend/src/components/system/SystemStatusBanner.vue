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
  <div v-if="renderedRowCount > 0 || pendingReserveRows > 0" class="system-status-banner">
    <!-- FE-9552: never stack -- chevron, qty, then the top family block; only
         visibility is gated (isBannerVisible), so this IS the fold mechanic. -->
    <div class="banner-fold-strip">
      <BannerFoldControls
        v-if="totalBannerCount > 1"
        v-model="foldExpanded"
        :qty="totalBannerCount"
      />

      <div class="banner-fold-rows">
        <!-- FE-9368 (E) / FE-9589: the Message Hub handover row, extracted to
             YourTurnBannerRow.vue (Guardrail 1) alongside its two siblings. -->
        <YourTurnBannerRow
          :threads="isBannerVisible('your-turn') ? visibleYourTurnThreads : []"
          @open="openYourTurn"
          @dismiss="dismissYourTurn"
        />

        <!-- FE-9501b (D6) / FE-9511: the raised-hand row for a request_approval
             question on a project you may not have open. Same shape as the Hub
             baton row above (FE-9368) on purpose -- one visual language for "an
             agent needs you" -- but a DIFFERENT data source: UserApprovalService's
             awaiting_user gate has no Hub thread/baton of its own (checked
             user_approval_service.py), so this reads useApprovalsStore directly
             instead of commHubStore. Not dismissible for the same reason the Hub
             row isn't: it is a live read of a pending approval and leaves the
             instant the approval is decided.

             FE-9511: markup + canned-text/pill rendering live in
             ApprovalBannerRow.vue to keep that file within the project's file-size budget. The text is a
             CANNED string keyed off the server-derived `banner_state` on each
             approval -- never `approval.reason`, which stays agent-authored
             prose demoted to the Review screen (ApprovalCard). Pills are the
             project taxonomy_alias, carried on the payload so they render for a
             project this session never opened (FE-9508's trap).

             FE-9552: fed an empty array when folded away (renders nothing for zero). -->
        <ApprovalBannerRow
          :approvals="isBannerVisible('approval') ? visibleApprovals : []"
          @open="openApprovals"
          @dismiss="dismissApprovals"
        />

        <!-- FE-9586: the thread-post family — somebody NAMED you, or directed an
             action-request at you. The banner these two signals never had, which is
             why FE-9553 could only ship their popouts event-shaped with a TTL rather
             than as projections of banner state.

             Server-projected, not derived here: useThreadPostAttention reads
             GET /api/v1/threads/attention. The client used to decide "was I
             mentioned" by matching a display name against the post body, and could
             not see all of it — a mention past the broker's excerpt cut-off was
             invisible to the reader it named.

             A BROADCAST action-request is deliberately absent: BE-9197 rules it
             "whoever picks it up", obligating nobody in particular. It keeps its bell
             row and raises no banner.

             Fed empty arrays when folded away, like the approval row (FE-9552). -->
        <ThreadPostBannerRow
          :mentions="isBannerVisible('thread-post') ? visibleMentions : []"
          :directed-asks="isBannerVisible('thread-post') ? visibleDirectedAsks : []"
          @open="openThreadPost"
          @dismiss="dismissThreadPosts"
        />

        <!-- FE-9538. FE-9552: rows filtered to visible fold keys; @open now also
             dismisses (acting on the CTA IS handling it), matching goTo() below. -->
        <LifecycleBannerRow
          :rows="visibleLifecycleRows"
          @open="openLifecycleRow"
          @dismiss="lifecycleBannerStore.dismiss"
        />

        <div
          v-for="n in visibleSystemBanners"
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

        <!-- FE-9202: CLIENT-ARMED tutorial row (useTutorialState localStorage, not
             a Notification row). FE-9552: markup in OnboardingNudgeRow.vue. -->
        <OnboardingNudgeRow
          v-if="showTutorialRow && isBannerVisible('tutorial')"
          row-testid="tutorial-activate-banner"
          cta-testid="tutorial-activate-cta"
          cta-label="Go to Products"
          dismiss-testid="tutorial-activate-dismiss"
          @cta="onTutorialCta"
          @dismiss="dismissTutorialRow"
        >
          Next: activate your product
        </OnboardingNudgeRow>

        <!-- FE-9202: onboarding nudges (byte-preserved useOnboardingReminders cadence). -->
        <OnboardingNudgeRow
          v-if="showIntegRow && isBannerVisible('integ')"
          row-testid="onboarding-integration-banner"
          cta-testid="onboarding-integration-cta"
          cta-label="Go to Tools"
          dismiss-testid="onboarding-integration-dismiss"
          @cta="onIntegCta"
          @dismiss="dismissIntegRow"
        >
          Enable Git and Serena MCP in your connect settings to give your agents more context.
        </OnboardingNudgeRow>

        <OnboardingNudgeRow
          v-if="showAgentRow && isBannerVisible('agent')"
          row-testid="onboarding-agent-banner"
          cta-testid="onboarding-agent-cta"
          cta-label="Go to Tools"
          dismiss-testid="onboarding-agent-dismiss"
          @cta="onAgentCta"
          @dismiss="dismissAgentRow"
        >
          Tune your agent templates and product context in Tools — make the defaults yours.
        </OnboardingNudgeRow>
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
import { useApprovalsStore } from '@/stores/useApprovalsStore'
import { useLifecycleBannerNav } from '@/composables/useLifecycleBannerNav'
import { useBannerFold } from '@/composables/useBannerFold'
import { useThreadPostAttention } from '@/composables/useThreadPostAttention'
import { useBannerSpaceReserve } from '@/composables/useBannerSpaceReserve'
import { useBannerDismiss } from '@/composables/useBannerDismiss'
import { useCommHubStore } from '@/stores/commHubStore'
import YourTurnBannerRow from './YourTurnBannerRow.vue'
import ApprovalBannerRow from './ApprovalBannerRow.vue'
import ThreadPostBannerRow from './ThreadPostBannerRow.vue'
import LifecycleBannerRow from './LifecycleBannerRow.vue'
import OnboardingNudgeRow from './OnboardingNudgeRow.vue'
import BannerFoldControls from './BannerFoldControls.vue'

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
  // D17: CE-only tool-rename notice — was missing here, so it never rendered.
  'system.tool_rename_notice',
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
  // FE-9552: CTA also dismisses -- fires first, before any early return below.
  if (n.dismissible) dismiss(n)

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

function onTutorialCta() { // FE-9552: CTA also dismisses
  goToProducts()
  dismissTutorialRow()
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

function onIntegCta() {
  goToTools()
  dismissIntegRow()
}

function onAgentCta() {
  goToTools()
  dismissAgentRow()
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

// ── FE-9501b (D6): raised hand for a request_approval question ───────────────
// The store itself is already app-wide (keyed by approval id, not scoped to
// whatever project is open) -- it was just never FED for an unopened project,
// because its only feed sat inside the project-scoped agent:status_changed
// handler. websocketEventRouter's new global-activity pass fixes the feed; this
// is the surface that was missing on top of it.
const approvalsStore = useApprovalsStore()
const pendingApprovals = computed(() => approvalsStore.pendingApprovals)

// ── FE-9586: the thread-post family ─────────────────────────────────────────
// Server-projected (useThreadPostAttention). `mentions`/`directedAsks` are null
// until the read lands -- the empty arrays below are for RENDERING only, and the
// popout lifecycle reads the same projection's `loaded` flag rather than these,
// because an empty list from an unhydrated read must never read as "cleared".
const {
  mentions: rawMentions,
  directedAsks: rawDirectedAsks,
  loaded: attentionLoaded,
  ensureLoaded: ensureAttentionLoaded,
} = useThreadPostAttention()
const threadPostMentions = computed(() => rawMentions.value || [])
const threadPostDirectedAsks = computed(() => rawDirectedAsks.value || [])
onMounted(ensureAttentionLoaded)

/**
 * Open the thread that is asking for you, or the Hub when several are.
 *
 * Ruling 3: the banner never navigates on its own -- this runs because the
 * operator clicked. Reading the thread is also what CLEARS the row: selectThread
 * persists the read watermark, the projection re-reads, and both the banner and
 * its popout go with it.
 */
function openThreadPost(threadId) {
  if (threadId) {
    router.push(hubThreadRoute(threadId)).catch(() => {})
    return
  }
  // FE-9589: with several entries live the row cannot name one thread, and the
  // Hub LIST selects none -- so this landed somewhere that wrote no watermark
  // and the row could never clear itself. Advance the watermark across every
  // thread the row names, then go where the CTA has always gone. The
  // single-thread path above is untouched: selectThread still does the write.
  commHub
    .markThreadsRead([
      ...visibleMentions.value.map((m) => m.thread_id),
      ...visibleDirectedAsks.value.map((a) => a.thread_id),
    ])
    .catch(() => {})
  router.push({ path: '/hub' }).catch(() => {})
}

// The other half of "within one broadcast": an approval already pending when
// the page loads, which no live event will ever re-announce. Mirrors
// useYourTurnThreads' ensureThreadsLoaded -- one list read per mount, its own
// transport errors swallowed so a failure here costs the banner, never the page.
let approvalsRequested = false
// FE-9589: hydration proof, not emptiness. Dismissal reconciliation must never
// run against a list that has not been read yet -- an unloaded read and "nothing
// pending" are the same empty array.
const approvalsLoaded = ref(false)
async function ensureApprovalsLoaded() {
  if (approvalsRequested) return
  approvalsRequested = true
  try {
    await approvalsStore.fetchPending()
    approvalsLoaded.value = true
  } catch {
    /* leave the row absent on a failed read -- non-fatal */
  }
}
onMounted(ensureApprovalsLoaded)

/**
 * One approval opens its project; several prefer a VIEWED-product match
 * (BE-9525c/FE-9525d) before falling back to the untargeted Projects list.
 * FE-9538 (Ask 2): every project-targeted push carries `tab=jobs`+
 * `decide=1`, consumed once by ProjectTabs.vue to open DecisionModal (hosts
 * ApprovalCard) -- its only route entry point.
 */
const DECISION_NAV_QUERY = { tab: 'jobs', decide: '1' }
function openApprovals() {
  const approvals = pendingApprovals.value
  if (approvals.length === 1 && approvals[0]?.project_id) {
    router.push({ name: 'ProjectLaunch', params: { projectId: approvals[0].project_id }, query: DECISION_NAV_QUERY })
    return
  }
  const viewedProductId = productStore.effectiveProductId
  const inViewedProduct = approvals.find((a) => a.product_id === viewedProductId && a.project_id)
  if (inViewedProduct) {
    router.push({ name: 'ProjectLaunch', params: { projectId: inViewedProduct.project_id }, query: DECISION_NAV_QUERY })
    return
  }
  router.push({ path: '/projects' })
}

const commHub = useCommHubStore()

// ── FE-9589: dismissal for the three live-read families ─────────────────────
// Keys, filtering and reconciliation live in useBannerDismiss (Guardrail 1);
// persistence in bannerDismissStore (per user, localStorage, survives a
// reload). Dismissing silences the ANNOUNCEMENT only -- nothing here writes
// server state, so a dismissed approval is still pending, a dismissed baton is
// still yours, and both are still in the Hub and the bell.
const {
  visibleApprovals,
  visibleMentions,
  visibleDirectedAsks,
  visibleYourTurnThreads,
  dismissApprovals,
  dismissThreadPosts,
  dismissYourTurn,
} = useBannerDismiss({
  approvals: pendingApprovals,
  approvalsLoaded,
  mentions: threadPostMentions,
  directedAsks: threadPostDirectedAsks,
  attentionLoaded,
  yourTurnThreads,
  threadsLoaded: computed(() => commHub.threadList.length > 0),
})

const { lifecycleBannerStore, openLifecycleBanner } = useLifecycleBannerNav(router) // FE-9538

function openLifecycleRow(row) { // FE-9552: CTA also dismisses (row+CTA both emit 'open')
  openLifecycleBanner(row)
  lifecycleBannerStore.dismiss(row.id)
}

// FE-9552: never stack -- fold state lives in useBannerFold.
const { totalBannerCount, foldExpanded, visibleBannerKeys, isBannerVisible } = useBannerFold({
  // FE-9589: the DISMISSED-FILTERED lists. The fold counts what is painted; a
  // dismissed row that still counted would reserve height for nothing and put a
  // qty on the chevron the operator cannot reach.
  yourTurnCount: computed(() => visibleYourTurnThreads.value.length),
  approvalCount: computed(() => visibleApprovals.value.length),
  threadPostCount: computed(
    () => visibleMentions.value.length + visibleDirectedAsks.value.length,
  ),
  lifecycleRows: computed(() => lifecycleBannerStore.rows),
  systemBanners: visibleBanners,
  showTutorial: showTutorialRow,
  showInteg: showIntegRow,
  showAgent: showAgentRow,
})
const visibleLifecycleRows = computed(() => lifecycleBannerStore.rows.filter((row) => isBannerVisible(`lifecycle:${row.id}`)))
const visibleSystemBanners = computed(() => visibleBanners.value.filter((n) => isBannerVisible(`system:${n.id}`)))

// ── FE-9377: first-frame space reservation (no post-paint layout shift) ───────
// The mechanism moved to useBannerSpaceReserve (FE-9586) unchanged;
// its docblock carries the reasoning. It needs the PAINTED row set, so it is
// constructed after useBannerFold above.
const { BANNER_ROW_PX, renderedRowCount, pendingReserveRows } = useBannerSpaceReserve({
  visibleBannerKeys,
  currentUserId: computed(() => userStore.currentUser?.id),
})
</script>

<style scoped lang="scss">
@use '@/styles/banner-unified' as banner;

.system-status-banner {
  position: sticky;
  top: 0;
  z-index: 100;
}

// FE-9552: collapsed = 1 row (no shift); expanded = normal-flow stack, not
// the "violent" shift the DoD rules out. Header lives in BannerFoldControls.vue.
.banner-fold-strip {
  @include banner.unified-fold-strip;
}

.banner-fold-rows {
  flex: 1;
  min-width: 0;
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
