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
      <component :is="TrialBannerComponent" v-if="TrialBannerComponent" />
      <component :is="AccountDeletionBannerComponent" v-if="AccountDeletionBannerComponent" />
      <component :is="LapsedStateBannerComponent" v-if="LapsedStateBannerComponent" />
      <component :is="SetPasswordNudgeBannerComponent" v-if="SetPasswordNudgeBannerComponent" />
      <SystemStatusBanner />
      <router-view
        :key="$route.matched[$route.matched.length - 1]?.path ?? $route.path"
        :current-user="currentUser"
      />
    </v-main>

    <ToastManager />

    <LicensingDialog />

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

const TrialBannerComponent = shallowRef(null)
const TrialExpiredOverlayComponent = shallowRef(null)
const AccountDeletionBannerComponent = shallowRef(null)
const LapsedStateBannerComponent = shallowRef(null)
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

useHubNotifications()

useBannerPopoutLifecycle()

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

const addableProducts = computed(() =>
  productStore.products.filter((p) => !productStore.openProductIds.includes(p.id)),
)

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
  try {
    const setupData = await setupService.checkEnhancedStatus()
    if (setupData.is_fresh_install) {
      router.push('/welcome')
      return
    }
  } catch (setupError) {
    console.warn('[DefaultLayout] Failed to check fresh install status:', setupError)
  }

  const userLoaded = await loadCurrentUser()

  if (userLoaded && currentUser.value) {
    await productStore.initializeFromStorage()
  }

  if (userLoaded && currentUser.value) {
    projectStatusesStore.ensureLoaded().catch((error) => {
      console.warn('[DefaultLayout] Failed to load project statuses:', error)
    })
  }

  if (userLoaded && currentUser.value) {
    taskStatusesStore.ensureLoaded().catch((error) => {
      console.warn('[DefaultLayout] Failed to load task statuses:', error)
    })
  }

  if (userLoaded && currentUser.value) {
    void (async () => {
      if (isNonCeMode()) {
        try {
          const bannerLoaders = import.meta.glob('@/saas/components/TrialBanner.vue')
          const overlayLoaders = import.meta.glob('@/saas/components/TrialExpiredOverlay.vue')
          const guardLoaders = import.meta.glob('@/saas/composables/useTrialGuard.js')
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
          if (deletionBannerLoader && accountStateStoreLoader) {
            const [deletionBannerMod, storeMod] = await Promise.all([
              deletionBannerLoader(),
              accountStateStoreLoader(),
            ])
            AccountDeletionBannerComponent.value = deletionBannerMod.default
            const accountStateStore = storeMod.useAccountStateStore()
            accountStateStore.startPolling()
          }

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

  if (userLoaded && currentUser.value) {
    try {
      await wsStore.connect()

      initWebsocketEventRouter()

      resyncUnregisters.push(
        registerReconnectResync(() => projectStore.refreshList()),
      )

      resyncUnregisters.push(useActiveProductReconciliation().stop)
    } catch (error) {
      console.error('[DefaultLayout] Failed to initialize WebSocket:', error)
    }
  }
})

onUnmounted(async () => {
  wsStore.disconnect()
  resyncUnregisters.forEach((unregister) => unregister?.())
  resyncUnregisters.length = 0
  window.removeEventListener('resize', onResize)
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
