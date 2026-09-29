<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.
-->
<template>
  <div v-if="renderedRowCount > 0 || pendingReserveRows > 0" class="system-status-banner">
    <div class="banner-fold-strip">
      <BannerFoldControls
        v-if="totalBannerCount > 1"
        v-model="foldExpanded"
        :qty="totalBannerCount"
      />

      <div class="banner-fold-rows">
        <YourTurnBannerRow
          :threads="isBannerVisible('your-turn') ? visibleYourTurnThreads : []"
          @open="openYourTurn"
          @dismiss="dismissYourTurn"
        />

        <ApprovalBannerRow
          :approvals="isBannerVisible('approval') ? visibleApprovals : []"
          @open="openApprovals"
          @dismiss="dismissApprovals"
        />

        <ThreadPostBannerRow
          :mentions="isBannerVisible('thread-post') ? visibleMentions : []"
          :directed-asks="isBannerVisible('thread-post') ? visibleDirectedAsks : []"
          @open="openThreadPost"
          @dismiss="dismissThreadPosts"
        />

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

const CE_SYSTEM_TYPES = new Set([
  'system.pending_migrations',
  'system.update_available',
  'system.skills_drift',
  'system.context_tuning_due',
  'system.tool_rename_notice',
])

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

function userHasRole(roleFilter) {
  if (!roleFilter) return true
  const role = userStore.currentUser?.role?.toLowerCase() ?? ''
  return role === roleFilter.toLowerCase()
}

const visibleBanners = computed(() =>
  notifStore.bannerNotifications.filter(
    (n) =>
      ALLOWED_TYPES.value.has(n.type) &&
      userHasRole(n.role_filter) &&
      !(n.type === 'system.context_tuning_due' && showAgentRow.value),
  ),
)

const RELEASES_URL = 'https://github.com/giljoai/giljo-hq/releases'

function externalHref(n) {
  if (n.type === 'system.update_available') {
    return n.payload?.release_url || RELEASES_URL
  }
  return null
}

function hasCta(n) {
  return Boolean(n.cta_route) || Boolean(externalHref(n))
}

function goTo(n) {
  if (n.dismissible) dismiss(n)

  const href = externalHref(n)
  if (href) {
    window.open(href, '_blank', 'noopener')
    return
  }
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

const showTutorialRow = ref(isActivateBreadcrumbArmed() && !productStore.activeProduct)

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

function onTutorialCta() {
  goToProducts()
  dismissTutorialRow()
}

watch(
  () => productStore.activeProduct,
  (active) => {
    if (active) dismissTutorialRow()
  },
)

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

const showIntegRow = computed(
  () =>
    !integHidden.value &&
    integStatusResolved.value &&
    integReminderCheck.value(hasProjects.value) &&
    !(gitEnabled.value && serenaEnabled.value),
)
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

let nudgeInputsLoaded = false
async function loadNudgeInputs() {
  if (nudgeInputsLoaded) return
  const couldInteg = integReminderCheck.value(true)
  const couldAgent = agentReminderCheck.value(true)
  if (!couldInteg && !couldAgent) return

  const pid = productStore.effectiveProductId
  if (!pid) return
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

const { yourTurnThreads, ensureThreadsLoaded } = useYourTurnThreads()

watch(() => userStore.currentUser?.id, (id) => { if (id) ensureThreadsLoaded() }, { immediate: true })

function openYourTurn() {
  const threads = yourTurnThreads.value
  if (threads.length === 1) {
    router.push(hubThreadRoute(threads[0]))
    return
  }
  router.push({ path: '/hub' })
}

const approvalsStore = useApprovalsStore()
const pendingApprovals = computed(() => approvalsStore.pendingApprovals)

const {
  mentions: rawMentions,
  directedAsks: rawDirectedAsks,
  loaded: attentionLoaded,
  ensureLoaded: ensureAttentionLoaded,
} = useThreadPostAttention()
const threadPostMentions = computed(() => rawMentions.value || [])
const threadPostDirectedAsks = computed(() => rawDirectedAsks.value || [])
onMounted(ensureAttentionLoaded)

function openThreadPost(threadId) {
  if (threadId) {
    router.push(hubThreadRoute(threadId)).catch(() => {})
    return
  }
  commHub
    .markThreadsRead([
      ...visibleMentions.value.map((m) => m.thread_id),
      ...visibleDirectedAsks.value.map((a) => a.thread_id),
    ])
    .catch(() => {})
  router.push({ path: '/hub' }).catch(() => {})
}

let approvalsRequested = false
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

function decisionRoute(projectId) {
  return { name: 'JobsViewport', query: { project: projectId, decide: '1' } }
}
function openApprovals() {
  const approvals = pendingApprovals.value
  if (approvals.length === 1 && approvals[0]?.project_id) {
    router.push(decisionRoute(approvals[0].project_id))
    return
  }
  const viewedProductId = productStore.effectiveProductId
  const inViewedProduct = approvals.find((a) => a.product_id === viewedProductId && a.project_id)
  if (inViewedProduct) {
    router.push(decisionRoute(inViewedProduct.project_id))
    return
  }
  router.push({ path: '/projects' })
}

const commHub = useCommHubStore()

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

const { lifecycleBannerStore, openLifecycleBanner } = useLifecycleBannerNav(router)

function openLifecycleRow(row) {
  openLifecycleBanner(row)
  lifecycleBannerStore.dismiss(row.id)
}

const { totalBannerCount, foldExpanded, visibleBannerKeys, isBannerVisible } = useBannerFold({
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
