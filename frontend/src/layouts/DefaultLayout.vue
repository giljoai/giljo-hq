<template>
  <v-app>
    <StarField />

    <NavigationDrawer
      v-if="!route.meta.hideDrawer"
      v-model="drawer"
      :rail="isMobile ? false : rail"
      :temporary="isMobile"
      :current-user="currentUser"
      @toggle-rail="rail = !rail"
    />

    <!-- FE-9502c: the tabbed product shell — one tab per open product, the
         viewed tab is a UI-local concept (not the server's single "active
         product"). Additive: with zero or one product open this renders at
         most one tab, so the pre-tabs single-product layout is unaffected. -->
    <v-app-bar
      v-if="!route.meta.hideDrawer && productStore.openProductTabs.length > 0"
      flat
      color="surface"
      class="product-tab-app-bar"
      density="compact"
    >
      <ProductTabStrip
        :tabs="tabsWithBadges"
        :viewed-id="productStore.currentProductId"
        :addable-products="addableProducts"
        @select="onProductTabSelect"
        @close="onProductTabClose"
        @add="onProductTabAdd"
      />
    </v-app-bar>

    <v-main>
      <!-- SaaS Trial Expiry Banner (loaded dynamically, absent in CE) -->
      <component :is="TrialBannerComponent" v-if="TrialBannerComponent" />
      <!-- Account Deletion Banner (loaded dynamically, absent in CE) -->
      <component :is="AccountDeletionBannerComponent" v-if="AccountDeletionBannerComponent" />
      <!-- FE-0017: Lapsed-state Banner (loaded dynamically, absent in CE) -->
      <component :is="LapsedStateBannerComponent" v-if="LapsedStateBannerComponent" />
      <!-- BE-1005: "Set a password" nudge for social-only users (loaded dynamically, absent in CE) -->
      <component :is="SetPasswordNudgeBannerComponent" v-if="SetPasswordNudgeBannerComponent" />
      <SystemStatusBanner />
      <!-- FE-9000e: key on the matched ROUTE RECORD's own path pattern (e.g.
           "/projects/:projectId"), not the resolved path/fullPath string, so a
           param-only nav within the same route record reuses the component
           instance (lets ProjectLaunchView.vue's FE-6174b watcher fire) while a
           route-record change still remounts and a query-only change still does
           not (710bc6c32 stays fixed — query never enters matched[].path). -->
      <router-view
        :key="$route.matched[$route.matched.length - 1]?.path ?? $route.path"
        :current-user="currentUser"
      />
    </v-main>

    <!-- Global Toast Notifications -->
    <ToastManager />

    <!-- Community Edition Licensing Reminder -->
    <LicensingDialog />

    <!-- SaaS Trial Expired Overlay (loaded dynamically, absent in CE) -->
    <component :is="TrialExpiredOverlayComponent" v-if="TrialExpiredOverlayComponent" />
  </v-app>
</template>

<script setup>
import { ref, computed, shallowRef, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useProductStore } from '@/stores/products'
import { useProjectStatusesStore } from '@/stores/projectStatusesStore'
import { useTaskStatusesStore } from '@/stores/taskStatusesStore'
import { useWebSocketStore } from '@/stores/websocket'
import { useProjectStore } from '@/stores/projects'
import { initWebsocketEventRouter, registerReconnectResync } from '@/stores/websocketEventRouter'
import { useHubNotifications } from '@/composables/useHubNotifications'
import { useBannerPopoutLifecycle } from '@/composables/useBannerPopoutLifecycle'
import { useActiveProductReconciliation } from '@/composables/useActiveProductReconciliation'
import { withProductActivityBadges } from '@/composables/useProductTabBadges'
import { useProductActivityStore } from '@/stores/productActivityStore'
import StarField from '@/components/StarField.vue'
import NavigationDrawer from '@/components/navigation/NavigationDrawer.vue'
import ProductTabStrip from '@/components/navigation/ProductTabStrip.vue'
import ToastManager from '@/components/ToastManager.vue'
import { defineAsyncComponent } from 'vue'
const LicensingDialog = defineAsyncComponent(() => import('@/components/LicensingDialog.vue'))
import SystemStatusBanner from '@/components/system/SystemStatusBanner.vue'
import setupService from '@/services/setupService'
import { useGiljoMode } from '@/composables/useGiljoMode'

// SaaS trial components -- loaded dynamically so CE export stays clean.
// When the saas/ directory is absent (CE build), the import fails silently.
const TrialBannerComponent = shallowRef(null)
const TrialExpiredOverlayComponent = shallowRef(null)
// account deletion banner (also lazy-loaded for CE-export safety).
const AccountDeletionBannerComponent = shallowRef(null)
// FE-0017: lapsed-state banner (also lazy-loaded for CE-export safety).
const LapsedStateBannerComponent = shallowRef(null)
// BE-1005: "set a password" nudge banner (also lazy-loaded for CE-export safety).
const SetPasswordNudgeBannerComponent = shallowRef(null)

const { isNonCeMode } = useGiljoMode()

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const productStore = useProductStore()
const productActivityStore = useProductActivityStore()
const projectStatusesStore = useProjectStatusesStore()
const taskStatusesStore = useTaskStatusesStore()
const wsStore = useWebSocketStore()
const projectStore = useProjectStore()

// FE-9289c: the Hub handover bell is mounted HERE, app-wide, not in HubView. The
// operator does not live in the Hub, so a "waiting on you" handover has to reach them
// from any page. The WS->window-event bridge (commHubEventRoutes via
// initWebsocketEventRouter, below) is already app-wide; this is the one consumer, and
// it belongs at the same level. Mount it in EXACTLY ONE place: the de-dupe set is
// per-instance, so a second mount (e.g. re-adding it to HubView) would double-fire
// every browser notification.
//
// FE-9553: it no longer fires a toast at all (rulings 3 and 6 -- these signals are
// actionable and agent-initiated, so they are the banner's and the bell's, not the
// toast's), and what keeps it silent is now Page Visibility rather than Hub presence:
// a popout fires only when the app is HIDDEN, so a visible tab gets the banner alone.
useHubNotifications()

// FE-9553 ruling 4(c): popouts follow banner state including its death. This is the
// half that notices the death -- it watches the same your-turn state the banner
// watches and closes any popout whose banner has gone. Mounted beside its producer
// and, like it, in exactly one place; a second mount would just reconcile twice
// against the same registry, but there is no reason to.
useBannerPopoutLifecycle()

// FE-3007b: unregister fns for the reconnect-resync callbacks this layout owns.
const resyncUnregisters = []

const drawer = ref(true)
const rail = ref(false)
const windowWidth = ref(window.innerWidth)
const SIDEBAR_BREAKPOINT = 1024
const isMobile = computed(() => windowWidth.value <= SIDEBAR_BREAKPOINT)

function onResize() {
  windowWidth.value = window.innerWidth
  if (isMobile.value) {
    drawer.value = false
  }
}

window.addEventListener('resize', onResize)
const currentUser = ref(null)

// FE-9502c: tab strip wiring. addableProducts is every product NOT currently
// open as a tab, offered in the strip's "+" add-tab menu.
const addableProducts = computed(() =>
  productStore.products.filter((p) => !productStore.openProductIds.includes(p.id)),
)

// FE-9502d: badge each background tab with its accumulated activity count
// (productActivityStore, fed by routeProductActivityEvent) so "an agent is
// working on Product B" reads on Product B's tab while you watch Product A --
// visualization only, no auto-switching.
const tabsWithBadges = computed(() =>
  withProductActivityBadges(
    productStore.openProductTabs,
    productStore.currentProductId,
    productActivityStore.getCount,
  ),
)

function onProductTabSelect(productId) {
  productStore.switchTab(productId)
  productActivityStore.clearActivity(productId)
}

function onProductTabClose(productId) {
  productStore.closeTab(productId)
}

function onProductTabAdd(productId) {
  productStore.openTab(productId)
  productActivityStore.clearActivity(productId)
}

const loadCurrentUser = async () => {
  try {
    const success = await userStore.fetchCurrentUser()
    if (success) {
      currentUser.value = userStore.currentUser
      return true
    }
    // fetchCurrentUser returned false (API failed internally)
    currentUser.value = null
    router.push('/login')
    return false
  } catch (error) {
    console.error('[DefaultLayout] Failed to load user:', error)
    currentUser.value = null
    router.push('/login')
    return false
  }
}

onMounted(async () => {
  // CRITICAL FIX (Handover 0034): Check fresh install status FIRST
  // This prevents race condition where DefaultLayout redirects to /login
  // before router guard can redirect to /welcome
  try {
    const setupData = await setupService.checkEnhancedStatus()
    if (setupData.is_fresh_install) {
      router.push('/welcome')
      return
    }
  } catch (setupError) {
    console.warn('[DefaultLayout] Failed to check fresh install status:', setupError)
  }

  // Normal operation: load current user
  const userLoaded = await loadCurrentUser()

  // Restore active product state from localStorage + backend
  if (userLoaded && currentUser.value) {
    await productStore.initializeFromStorage()
  }

  // BE-5039: prime the canonical project-status metadata cache once per
  // session. ensureLoaded() is idempotent and rejects on transport
  // failure so we only catch + log here; consumers (StatusBadge,
  // useProjectFilters) degrade gracefully when the cache is empty.
  if (userLoaded && currentUser.value) {
    projectStatusesStore.ensureLoaded().catch((error) => {
      console.warn('[DefaultLayout] Failed to load project statuses:', error)
    })
  }

  // FE-5041 Phase 2: prime the canonical task-status metadata cache once
  // per session. Same coalesced/idempotent pattern as project statuses.
  if (userLoaded && currentUser.value) {
    taskStatusesStore.ensureLoaded().catch((error) => {
      console.warn('[DefaultLayout] Failed to load task statuses:', error)
    })
  }

  // Load SaaS trial components when in SaaS/Demo mode.
  // FE-6058: fire-and-forget (void async IIFE) so these lazy SaaS chunk loads
  // do NOT serially delay the WebSocket connect + first message fetch below.
  // Self-contained and catches its own errors; CE builds skip via empty glob.
  if (userLoaded && currentUser.value) {
    void (async () => {
      if (isNonCeMode()) {
        try {
          // Vite-aware lazy load via import.meta.glob (CE export safe).
          // CE builds have saas/ stripped → glob returns empty → silently skip.
          // SaaS/private builds → Vite bundles each into a lazy chunk.
          // Replaces an earlier @vite-ignore + runtime-URL pattern that 404'd
          // into the SPA fallback in production builds and broke trial UI.
          const bannerLoaders = import.meta.glob('@/saas/components/TrialBanner.vue')
          const overlayLoaders = import.meta.glob('@/saas/components/TrialExpiredOverlay.vue')
          const guardLoaders = import.meta.glob('@/saas/composables/useTrialGuard.js')
          // deletion banner + account-state store (lazy, CE-stripped).
          const deletionBannerLoaders = import.meta.glob(
            '@/saas/components/AccountDeletionBanner.vue',
          )
          const accountStateStoreLoaders = import.meta.glob('@/saas/stores/useAccountStateStore.js')
          const [bannerLoader] = Object.values(bannerLoaders)
          const [overlayLoader] = Object.values(overlayLoaders)
          const [guardLoader] = Object.values(guardLoaders)
          const [deletionBannerLoader] = Object.values(deletionBannerLoaders)
          const [accountStateStoreLoader] = Object.values(accountStateStoreLoaders)
          if (bannerLoader && overlayLoader && guardLoader) {
            const [bannerMod, overlayMod, guardMod] = await Promise.all([
              bannerLoader(),
              overlayLoader(),
              guardLoader(),
            ])
            TrialBannerComponent.value = bannerMod.default
            TrialExpiredOverlayComponent.value = overlayMod.default
            guardMod.installTrialGuardInterceptor()
          }
          // wire deletion banner + start polling combined account state.
          if (deletionBannerLoader && accountStateStoreLoader) {
            const [deletionBannerMod, storeMod] = await Promise.all([
              deletionBannerLoader(),
              accountStateStoreLoader(),
            ])
            AccountDeletionBannerComponent.value = deletionBannerMod.default
            const accountStateStore = storeMod.useAccountStateStore()
            accountStateStore.startPolling()
          }

          // FE-0017: lazy-load LapsedStateBanner + install the
          // X-License-State axios interceptor. The interceptor is the
          // ADR-002-compliant gate: only installed in SaaS/demo mode, never
          // in CE (where the import.meta.glob returns empty and these blocks
          // silently skip).
          const lapsedBannerLoaders = import.meta.glob('@/saas/components/LapsedStateBanner.vue')
          const licenseInterceptorLoaders = import.meta.glob(
            '@/saas/composables/installLicenseStateInterceptor.js',
          )
          const [lapsedBannerLoader] = Object.values(lapsedBannerLoaders)
          const [licenseInterceptorLoader] = Object.values(licenseInterceptorLoaders)
          if (lapsedBannerLoader && licenseInterceptorLoader) {
            const [lapsedBannerMod, interceptorMod] = await Promise.all([
              lapsedBannerLoader(),
              licenseInterceptorLoader(),
            ])
            LapsedStateBannerComponent.value = lapsedBannerMod.default
            interceptorMod.installLicenseStateInterceptor()
          }

          // BE-1005: "set a password" nudge for social-only users. Self-contained
          // (fetches its own GET /auth/identities on mount) -- no store to wire.
          const nudgeBannerLoaders = import.meta.glob('@/saas/components/auth/SetPasswordNudgeBanner.vue')
          const [nudgeBannerLoader] = Object.values(nudgeBannerLoaders)
          if (nudgeBannerLoader) {
            const nudgeBannerMod = await nudgeBannerLoader()
            SetPasswordNudgeBannerComponent.value = nudgeBannerMod.default
          }
        } catch (error) {
          console.warn('[DefaultLayout] SaaS trial UI failed to load:', error)
        }
      }
    })()
  }

  // Initialize WebSocket and data polling only if user is authenticated
  if (userLoaded && currentUser.value) {
    try {
      // Connect WebSocket - browser will automatically send httpOnly access_token cookie
      await wsStore.connect()

      // Initialize the centralized router once (0379a)
      initWebsocketEventRouter()

      // FE-3007b: register the GLOBAL reconnect resync (project list). The
      // open-project resync (entity + jobs) registers itself from
      // useProjectTabsLifecycle while a tab is open; the Hub's own resync
      // registers itself from HubView. On any reconnect — automatic or
      // manual — the router fans out to all of them. BE-9012d: the global
      // message-inbox resync (messageStore.fetchMessages, bus-backed) is
      // retired along with the bus.
      resyncUnregisters.push(
        // refreshList() replays the active filter/sort/page; a bare fetchProjects()
        // on reconnect would clobber a filtered view with the active-lifecycle default.
        registerReconnectResync(() => projectStore.refreshList()),
      )

      // FE-9412: the active product must survive a socket that missed the
      // activation event — re-validate it on tab focus/visibility and on
      // reconnect. Torn down with the resync registrations below (this runs
      // in onMounted, so the composable's own scope-dispose cannot fire).
      resyncUnregisters.push(useActiveProductReconciliation().stop)
    } catch (error) {
      console.error('[DefaultLayout] Failed to initialize WebSocket:', error)
    }
  }
})

onUnmounted(async () => {
  wsStore.disconnect()
  // FE-3007b: drop this layout's reconnect-resync registrations.
  resyncUnregisters.forEach((unregister) => unregister?.())
  resyncUnregisters.length = 0
  window.removeEventListener('resize', onResize)
  // stop polling when leaving the authenticated layout.
  try {
    const storeLoaders = import.meta.glob('@/saas/stores/useAccountStateStore.js')
    const [loader] = Object.values(storeLoaders)
    if (loader) {
      const mod = await loader()
      mod.useAccountStateStore().stopPolling()
    }
  } catch {
    // CE bundle has no store module — silent skip.
  }
})

// Reload user after login (navigation from /login)
router.afterEach(async (to, from) => {
  if (to.meta.layout === 'default' && from.path === '/login') {
    await loadCurrentUser()
  }
})
</script>

<style scoped>
/* Mobile: add top padding to clear the hamburger FAB */
@media (max-width: 1024px) {
  :deep(.v-main) {
    padding-top: 48px !important;
  }
}

/* FE-9502c: product tab strip app bar */
.product-tab-app-bar {
  padding: 0 16px;
}
</style>
