<template>
  <v-navigation-drawer
    id="navigation"
    :model-value="modelValue"
    :rail="rail"
    :permanent="!temporary"
    :temporary="temporary"
    :mobile="false"
    color="surface"
    width="180"
    class="navigation-drawer-container"
    @update:model-value="$emit('update:model-value', $event)"
  >
    <div
      v-if="(!rail || temporary) && modelValue"
      class="edge-toggle-tab"
      :aria-label="temporary ? 'Close navigation' : 'Collapse sidebar'"
      role="button"
      tabindex="0"
      @click="temporary ? $emit('update:model-value', false) : $emit('toggle-rail')"
      @keydown.enter="temporary ? $emit('update:model-value', false) : $emit('toggle-rail')"
      @keydown.space.prevent="temporary ? $emit('update:model-value', false) : $emit('toggle-rail')"
    >
      <v-icon size="20">mdi-chevron-left</v-icon>
    </div>

    <div class="nav-top">
      <div class="nav-logo" :class="{ 'nav-logo--rail': rail }">
        <v-img
          v-if="!rail"
          src="/Giljo_YW.svg"
          alt="GiljoAI"
          height="32"
          width="auto"
          max-width="120"
          class="nav-logo-full"
          :class="{ 'nav-logo-full--attention': !hasProduct }"
        />
        <v-img
          v-else
          src="/icons/Giljo_YW_Face.svg"
          alt="GiljoAI"
          height="28"
          width="28"
          class="nav-logo-icon"
          :class="{ 'nav-logo-icon--attention': !hasProduct }"
        />
      </div>

      <div
        v-if="rail && !temporary"
        class="nav-expand-btn"
        role="button"
        tabindex="0"
        aria-label="Expand sidebar"
        @click="$emit('toggle-rail')"
        @keydown.enter="$emit('toggle-rail')"
      >
        <v-icon size="22">mdi-chevron-right</v-icon>
      </div>

      <router-link
        v-if="!rail"
        :to="{ name: 'Products' }"
        class="nav-product-subtitle"
        :class="{ 'nav-product-subtitle--inactive': !productsStore.currentProduct }"
      >
        {{ productsStore.currentProduct ? productsStore.currentProduct.name : 'No product open' }}
      </router-link>
    </div>

    <v-list
      v-model:selected="selected"
      density="compact"
      nav
      select-strategy="single"
      class="nav-items"
    >
      <v-list-item
        v-for="item in navigationItems"
        :key="item.name"
        :to="item.path"
        :title="item.title"
        :value="item.name"
        :disabled="item.disabled"
        :class="{ 'nav-item--attention': item.attention }"
        :data-test="item.dataTest"
        color="primary"
        role="listitem"
        :exact="true"
      >
        <template #prepend>
          <v-img
            v-if="item.customIcon"
            :src="item.customIcon"
            width="28"
            height="28"
            :style="{
              marginLeft: '-2px',
              marginRight: '30px',
            }"
          ></v-img>
          <v-icon v-else>{{ item.icon }}</v-icon>
        </template>
        <template v-if="badgeCount(item) > 0" #append>
          <span :style="hubUnreadBadgeStyle()" :data-testid="badgeTestId(item)">{{ badgeCount(item) > 99 ? '99+' : badgeCount(item) }}</span>
        </template>
      </v-list-item>
    </v-list>

    <template #append>
      <div class="nav-bottom">
        <div class="nav-orb-row" :class="{ 'nav-orb-row--stacked': rail }">
          <NotificationDropdown :compact="true" />

          <v-tooltip location="right">
            <template #activator="{ props: tipProps }">
              <div
                v-bind="tipProps"
                class="nav-orb nav-orb--connection"
                :class="{
                  'nav-orb--warning': connectionColor === 'warning',
                  'nav-orb--error': connectionColor === 'error',
                }"
                role="button"
                tabindex="0"
                aria-label="Connection status"
                @click="showConnectionDebug = true"
              >
                <v-icon :icon="connectionIcon" size="18" />
              </div>
            </template>
            {{ connectionText }}
          </v-tooltip>

          <NavLogMenu
            v-if="isCeConfirmed"
            :open="logMenuOpen"
            :log-archives="logArchives"
            :log-archives-loading="logArchivesLoading"
            @menu-toggle="onLogMenuToggle"
            @download-current="downloadCurrentLog"
            @download-archive="downloadArchive"
          />

          <NavAvatarMenu
            :current-user="currentUser"
            :user-initials="userInitials"
            :giljo-mode="giljoMode"
            :is-admin="userStore.isAdmin"
            :org-name="userStore.currentOrg?.name ?? null"
            :org-role="userStore.orgRole ?? null"
            :account-status-badge-component="AccountStatusBadgeComponent"
            :account-badge-state="accountBadgeState"
            :is-account-scheduled-for-deletion="isAccountScheduledForDeletion"
            :account-badge-state-modifier="accountBadgeStateModifier"
            :account-status-title="accountStatusTitle"
            :account-status-subtitle="accountStatusSubtitle"
            :cancelling-deletion="cancellingDeletion"
            :version-label="versionLabel"
            :license-status="licenseStatus"
            :reset-password-loading="resetPasswordLoading"
            @logout="handleLogout"
            @cancel-deletion="onCancelDeletion"
            @upgrade="goUpgrade"
            @confirm-reset-password="confirmResetPassword"
          />
        </div>

        <div class="edition-footer">
          <span class="edition-label">{{ editionFooterLabel }}</span>
        </div>
      </div>

      <ConnectionDebugDialog v-model="showConnectionDebug" />
    </template>
  </v-navigation-drawer>

  <v-btn
    v-if="temporary && !modelValue"
    icon="mdi-menu"
    size="small"
    variant="flat"
    color="surface"
    class="mobile-menu-fab"
    aria-label="Open navigation"
    @click="$emit('update:model-value', true)"
  />
</template>

<script setup>
import { computed, ref, watch, onMounted, defineAsyncComponent } from 'vue'
import axios from 'axios'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/projects'
import { useProductStore } from '@/stores/products'
import { useUserStore } from '@/stores/user'
import { useWebSocketStore } from '@/stores/websocket'
import { useCommHubStore } from '@/stores/commHubStore'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { useGlobalActivityStore } from '@/stores/globalActivityStore'
import { useToast } from '@/composables/useToast'
import { useNavDrawerAccount } from '@/composables/useNavDrawerAccount'
import { useNavConnectionStatus } from '@/composables/useNavConnectionStatus'
import configService from '@/services/configService'
import setupService from '@/services/setupService'
import { isCeModeValue } from '@/composables/useGiljoMode'
import { getApiBaseUrl } from '@/composables/useApiUrl'
import { parseErrorResponse } from '@/utils/errorMessages'
import { resolveJobsNavPath, resolveJobsNavIcon, isJobsRouteActive, hubUnreadBadgeStyle } from '@/utils/jobsNavTarget'
import NotificationDropdown from '@/components/navigation/NotificationDropdown.vue'
const ConnectionDebugDialog = defineAsyncComponent(
  () => import('@/components/navigation/ConnectionDebugDialog.vue'),
)
import NavLogMenu from './nav-drawer/NavLogMenu.vue'
import NavAvatarMenu from './nav-drawer/NavAvatarMenu.vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: true,
  },
  rail: {
    type: Boolean,
    default: false,
  },
  temporary: {
    type: Boolean,
    default: false,
  },
  currentUser: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['update:model-value', 'toggle-rail'])

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const productsStore = useProductStore()
const userStore = useUserStore()
const wsStore = useWebSocketStore()
const commHub = useCommHubStore()
const globalActivity = useGlobalActivityStore()
function badgeCount(item) {
  if (item.name === 'Hub') return commHub.totalUnread
  if (item.name === 'Projects') {
    return projectStore.projects.reduce((sum, p) => sum + globalActivity.getCount(p.id), 0)
  }
  return 0
}
const badgeTestId = (item) => (item.name === 'Hub' ? 'nav-hub-unread-badge' : 'nav-projects-activity-badge')
const sequenceRunStore = useSequenceRunStore()
const { showToast } = useToast()

const selected = ref([])

const showConnectionDebug = ref(false)
const licenseStatus = ref('Licensed')

const logMenuOpen = ref(false)
const logArchives = ref([])
const logArchivesLoading = ref(false)

async function onLogMenuToggle(open) {
  logMenuOpen.value = open
  if (open) {
    const { apiClient } = await import('@/services/api')
    logArchivesLoading.value = true
    try {
      const response = await apiClient.get('/api/download/logs/archives')
      logArchives.value = response.data || []
    } catch {
      logArchives.value = []
      showToast({ message: 'Failed to load log archives', type: 'error' })
    } finally {
      logArchivesLoading.value = false
    }
  }
}

function downloadCurrentLog() {
  window.open('/api/download/logs/current', '_blank')
  logMenuOpen.value = false
}

function downloadArchive(filename) {
  window.open(`/api/download/logs/archive/${encodeURIComponent(filename)}`, '_blank')
  logMenuOpen.value = false
}

const giljoMode = ref('unknown')
const {
  AccountStatusBadgeComponent,
  accountBadgeState,
  isAccountScheduledForDeletion,
  accountBadgeStateModifier,
  accountStatusTitle,
  accountStatusSubtitle,
  cancellingDeletion,
  onCancelDeletion,
  goUpgrade,
  loadAccountStateUI,
} = useNavDrawerAccount({ giljoMode })

const serverVersion = ref('')

async function checkEdition() {
  try {
    await configService.fetchConfig()
    giljoMode.value = configService.getGiljoMode()
    serverVersion.value = configService.getVersion()
  } catch {
    giljoMode.value = 'unknown'
    serverVersion.value = ''
  }
}

const isCeConfirmed = computed(
  () => isCeModeValue(giljoMode.value) && !configService.isFallback(),
)

const editionFooterLabel = computed(() => {
  switch (giljoMode.value) {
    case 'saas':
      return props.rail ? 'SaaS' : 'SaaS Edition'
    case 'ce':
      return props.rail ? 'CE' : 'Community Edition'
    default:
      return ''
  }
})

const versionLabel = computed(() =>
  serverVersion.value ? `v${serverVersion.value}` : 'Version unavailable',
)

const resetPasswordLoading = ref(false)

async function confirmResetPassword(email) {
  resetPasswordLoading.value = true
  try {
    if (!email) {
      return
    }

    const baseUrl = getApiBaseUrl()

    const resetLoaders = import.meta.glob('@/saas/services/passwordReset.js')
    const [loader] = Object.values(resetLoaders)
    if (!loader) {
      throw new Error('Password reset is unavailable in this edition.')
    }
    const mod = await loader()
    await mod.requestPasswordReset(axios, baseUrl, email)
    showToast({ message: 'Password reset email sent. Check your inbox.', type: 'success' })
  } catch (err) {
    showToast({
      message: parseErrorResponse(err).message || 'Unable to send reset email. Please try again later.',
      type: 'error',
    })
  } finally {
    resetPasswordLoading.value = false
  }
}

const userInitials = computed(() => {
  if (!props.currentUser?.username) return '?'
  return props.currentUser.username.substring(0, 2).toUpperCase()
})

const { connectionIcon, connectionColor, connectionText } = useNavConnectionStatus()

const handleLogout = async () => {
  try {
    await userStore.logout()
  } finally {
    try {
      localStorage.removeItem('user')
    } catch {
      /* noop */
    }
    try {
      wsStore.disconnect()
    } catch {
      /* noop */
    }
    router.push('/login')
  }
}

const jobsIcon = computed(() => resolveJobsNavIcon(route.path, route?.query))

const hasProduct = computed(() => !!productsStore.currentProduct)
const hasProject = computed(() => (projectStore.projects?.length ?? 0) > 0)

const navigationItems = computed(() => {
  const jobsPath = resolveJobsNavPath()

  const items = [
    { name: 'Home', path: '/home', title: 'Home', icon: 'mdi-home' },
    { name: 'Dashboard', path: '/Dashboard', title: 'Dashboard', icon: 'mdi-view-dashboard' },
    {
      name: 'Products',
      path: '/Products',
      title: 'Products',
      icon: 'mdi-package-variant',
      attention: !hasProduct.value,
    },
    {
      name: 'Projects',
      path: '/projects',
      title: 'Projects',
      icon: 'mdi-folder-multiple',
      attention: hasProduct.value && !hasProject.value,
    },
    { name: 'Roadmap', path: '/roadmap', title: 'Roadmap', icon: 'mdi-map-marker-path' },
    { name: 'Jobs', path: jobsPath, title: 'Jobs', customIcon: jobsIcon.value },
    { name: 'Tasks', path: '/tasks', title: 'Tasks', icon: 'mdi-clipboard-check' },
    {
      name: 'Hub',
      path: '/hub',
      title: 'Message Hub',
      icon: 'mdi-forum',
      dataTest: 'nav-hub',
      attention: commHub.yourTurnCount > 0,
    },
    { name: 'Memory', path: '/memory', title: 'Memory', icon: 'mdi-bookshelf', dataTest: 'nav-memory' },
    { name: 'Tools', path: '/tools', title: 'Tools', icon: 'mdi-tools' },
  ]

  if (userStore.isAdmin && isCeConfirmed.value) {
    items.push({ name: 'Admin', path: '/admin/settings', title: 'Admin', icon: 'mdi-shield-crown' })
  }

  return items
})

const updateSelectedFromRoute = () => {
  const items = navigationItems.value
  const currentPath = route.path

  if (isJobsRouteActive(currentPath, route?.query)) {
    selected.value = ['Jobs']
    return
  }

  let best = null
  for (const item of items) {
    if (!item.path) continue
    if (currentPath === item.path || currentPath.startsWith(`${item.path}/`)) {
      if (!best || item.path.length > best.path.length) {
        best = item
      }
    }
  }
  selected.value = best ? [best.name] : []
}

onMounted(async () => {
  updateSelectedFromRoute()
  checkEdition()
  loadAccountStateUI()

  try {
    await configService.fetchConfig()
    const ed = configService.getEdition()
    if (ed === 'community') {
      const data = await setupService.checkEnhancedStatus()
      if ((data.total_users_count || 0) > 1) {
        licenseStatus.value = 'Unlicensed'
      }
    }
  } catch (error) {
    console.warn('[NavigationDrawer] license status check failed:', error)
  }
})

watch(
  () => route.path,
  () => updateSelectedFromRoute(),
)

watch(() => productsStore.effectiveProductId, () => sequenceRunStore.hydrate(), {
  immediate: true,
})
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.navigation-drawer-container {
  overflow: visible;
}

// Force width in temporary mode
.navigation-drawer-container.v-navigation-drawer--temporary {
  width: 180px !important; /* !important: override Vuetify v-navigation-drawer inline width */
}

// ─── EDGE TOGGLE TAB ───
.edge-toggle-tab {
  position: absolute;
  right: -16px;
  top: 20px;
  width: 32px;
  height: 32px;
  background: rgb(var(--v-theme-surface));
  border: 1px solid rgba(var(--v-border-color), 0.15) !important; /* !important: ensure border visibility over adjacent elevated surfaces */
  border-radius: $border-radius-sharp;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 100;
  transition: all $transition-normal ease;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.edge-toggle-tab:hover {
  background: rgba(var(--v-theme-primary), 0.1);
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgb(var(--v-theme-primary)));
}
.edge-toggle-tab:focus {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: 2px;
}
.edge-toggle-tab:active {
  transform: scale(0.95);
}

// ─── TOP SECTION ───
.nav-top {
  padding: 16px 12px 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.nav-logo {
  display: flex;
  justify-content: center;
  width: 100%;
}

.nav-logo--rail {
  padding: 4px 0;
}

.nav-expand-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 36px;
  cursor: pointer;
  color: rgba(var(--v-theme-on-surface), 0.6);
  transition: all $transition-normal ease;
  margin-bottom: -4px;

  &:hover {
    color: rgb(var(--v-theme-primary));
  }
}

.nav-product-subtitle {
  font-size: 0.8rem;
  color: $color-brand-yellow;
  text-decoration: none;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  width: 100%;
  padding: 0 4px;
  transition: color $transition-normal ease;
  display: block;
  font-weight: 500;

  &:hover {
    color: $color-brand-yellow-hover;
  }

  &--inactive {
    font-size: 0.7rem;
    color: var(--text-muted);
    font-weight: 400;

    &:hover {
      color: $color-brand-yellow;
    }
  }
}

// ─── ATTENTION ANIMATIONS ───
@keyframes navAttentionNudge {
  0%,
  100% {
    transform: translateX(0);
    background: transparent;
  }
  50% {
    transform: translateX(2px);
    background: rgba(255, 195, 0, 0.09);
  }
}

@keyframes logoAttention {
  0%,
  100% {
    transform: scale(1);
    filter: drop-shadow(0 0 0 transparent);
  }
  50% {
    transform: scale(1.08);
    filter: drop-shadow(0 0 8px rgba(255, 195, 0, 0.45));
  }
}

.nav-logo-full--attention {
  animation: logoAttention 2.8s ease-in-out 1s infinite;
}

.nav-logo-icon--attention {
  animation: logoAttention 2.8s ease-in-out 1s infinite;
}

.nav-item--attention {
  animation: navAttentionNudge 2.8s ease-in-out 1s infinite;
}

// ─── NAV ITEMS ───
.nav-items {
  flex: 1;
}

// ─── BOTTOM SECTION ───
.nav-bottom {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 0 16px;
  gap: 8px;
}

.nav-orb-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;

  &--stacked {
    flex-direction: column;
    gap: 6px;
  }
}

// ─── ORBS: unified round icons ───
.nav-orb {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all $transition-normal ease;
}

.nav-orb:hover {
  transform: scale(1.08);
}

.nav-orb:active {
  transform: scale(0.95);
}

// Connection: opaque green background, bright green icon
.nav-orb--connection {
  background: rgba($color-accent-success, 0.15);
  color: $color-accent-success;

  &:hover {
    background: rgba($color-accent-success, 0.25);
  }
}

.nav-orb--connection.nav-orb--warning {
  background: rgba($color-brand-yellow, 0.15);
  color: $color-brand-yellow;

  &:hover {
    background: rgba($color-brand-yellow, 0.25);
  }
}

.nav-orb--connection.nav-orb--error {
  background: rgba($color-accent-danger, 0.15);
  color: $color-accent-danger;

  &:hover {
    background: rgba($color-accent-danger, 0.25);
  }
}

.edition-footer {
  padding: 8px 0 0;
  text-align: center;
  border-top: 1px solid rgba(var(--v-border-color), 0.15);
  width: 100%;
  margin-top: 4px;
}

.edition-label {
  color: $color-brand-yellow;
  font-weight: 500;
  letter-spacing: 0.02em;
}

// ─── MOBILE FAB ───
.mobile-menu-fab {
  position: fixed;
  top: 12px;
  left: 12px;
  // Above the product tab app bar (Vuetify layout z-index 1004), below the drawer.
  z-index: 1005;
  // FE-9365a: a rounded square, not a circle. FABs are not exempt from the
  // button-shape standard — see the Button Shape Standard block in main.scss.
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}
</style>
