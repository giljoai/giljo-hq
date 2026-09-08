<template>
  <v-container>
    <!-- Page Header -->
    <h1 class="text-headline-large mb-2">Admin Settings</h1>
    <p class="text-body-large mb-4 settings-subtitle">
      Configure server and system-wide settings (Admin only)
    </p>

    <!-- Settings Pills -->
    <!-- Order: Identity, then server-plumbing tabs (CE only). The orchestrator
         prompt moved to Account -> Danger Zone (IMP-5042) -- it is tenant-scoped
         self-management, not server admin. -->
    <div class="pill-toggle-row">
      <button
        class="pill-toggle smooth-border"
        :class="{ 'pill-toggle--active': activeTab === 'identity' }"
        data-test="identity-tab"
        @click="activeTab = 'identity'"
      >
        <v-icon size="16" class="pill-toggle-icon">mdi-account-group</v-icon>
        Identity
      </button>
      <button
        v-if="isCeMode"
        class="pill-toggle smooth-border"
        :class="{ 'pill-toggle--active': activeTab === 'network' }"
        data-test="network-tab"
        @click="activeTab = 'network'"
      >
        <v-icon size="16" class="pill-toggle-icon">mdi-network-outline</v-icon>
        Network
      </button>
      <button
        v-if="isCeMode"
        class="pill-toggle smooth-border"
        :class="{ 'pill-toggle--active': activeTab === 'database' }"
        data-test="database-tab"
        @click="activeTab = 'database'"
      >
        <v-icon size="16" class="pill-toggle-icon">mdi-database</v-icon>
        Database
      </button>
    </div>

    <!-- Tab Content -->
    <div class="pill-tabs-content">
      <v-window v-model="activeTab" class="global-tabs-window main-window-tabs">
        <!-- Identity (Workspace + Members) - Handover 0434 -->
        <v-window-item value="identity">
          <IdentityTab />
        </v-window-item>

        <!-- Network Settings -->
        <v-window-item v-if="isCeMode" value="network">
          <NetworkSettingsTab
            :server-host-display="serverHostDisplay"
            :server-port="serverPort"
            :ssl-enabled="sslEnabled"
            :loading="loading.network"
            :cookie-domains="cookieDomains"
            :cookie-loading="loading.security"
            :cookie-feedback="securityFeedback"
            @refresh="loadNetworkSettings"
            @add-domain="addCookieDomain"
            @remove-domain="removeCookieDomain"
            @reload-domains="loadCookieDomains"
            @clear-cookie-feedback="clearSecurityFeedback"
          />
        </v-window-item>

        <!-- Database Settings -->
        <v-window-item v-if="isCeMode" value="database">
          <DatabaseConnection
            :readonly="true"
            :show-title="true"
            title="PostgreSQL Database Configuration"
            :show-info-banner="true"
            info-banner-text="Database settings are configured during installation"
            :show-test-button="true"
            test-button-text="Test Connection"
            @connection-success="handleDatabaseSuccess"
            @connection-error="handleDatabaseError"
          >
            <template #actions>
              <v-btn variant="text" @click="loadDatabaseSettings({ notify: true })">
                <v-icon start>mdi-refresh</v-icon>
                Reload from Config
              </v-btn>
            </template>
          </DatabaseConnection>
        </v-window-item>

      </v-window>
    </div>
  </v-container>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getApiBaseURL } from '@/config/api'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'
import configService from '@/services/configService'
import { isCeModeValue } from '@/composables/useGiljoMode'

// Components
import DatabaseConnection from '@/components/DatabaseConnection.vue'
import IdentityTab from '@/components/settings/tabs/IdentityTab.vue'
import NetworkSettingsTab from '@/components/settings/tabs/NetworkSettingsTab.vue'

const { showToast } = useToast()
const giljoMode = ref('ce')
const isCeMode = computed(() => isCeModeValue(giljoMode.value))

// State
const activeTab = ref('identity')

// Valid tab values when the user is restricted to product-admin tabs.
// The orchestrator prompt moved to Account -> Danger Zone (IMP-5042), so
// Identity is the only product-admin tab; the rest are CE-only server config.
const PRODUCT_ADMIN_TABS = ['identity']

// Loading states
const loading = ref({
  network: false,
  security: false,
})

// Network settings state — read-only, derived from what the server actually
// responds on (FE-6239: real interface IP(s), not the config external_host).
const serverHostDisplay = ref('localhost')
const serverPort = ref(parseInt(window.location.port) || 7272)
const sslEnabled = ref(false)

// Cookie Domain Whitelist state
const cookieDomains = ref([])
const securityFeedback = ref(null)

// Network Settings Methods
async function loadNetworkSettings() {
  loading.value.network = true
  try {
    // The host IP(s) + port the server actually responds on (FE-6239).
    const response = await fetch(`${getApiBaseURL()}/api/v1/config/network-info`, {
      credentials: 'include',
    })
    if (!response.ok) {
      throw new Error(`network-info endpoint failed: ${response.statusText}`)
    }
    const info = await response.json()
    serverHostDisplay.value = info.host_display || 'localhost'
    serverPort.value = info.port || parseInt(window.location.port) || 7272

    // SSL/HTTPS status (prop fallback; the tab also fetches /config/ssl itself).
    const cfgResp = await fetch(`${getApiBaseURL()}/api/v1/config`, {
      credentials: 'include',
    })
    if (cfgResp.ok) {
      const config = await cfgResp.json()
      sslEnabled.value = Boolean(config.features?.ssl_enabled)
    }
  } catch (error) {
    console.error('[SYSTEM SETTINGS] Failed to load network settings:', error)
    // Fall back to the address this client reached the server on.
    serverHostDisplay.value = window.location.hostname || 'localhost'
    serverPort.value = parseInt(window.location.port) || 7272
    sslEnabled.value = false
  } finally {
    loading.value.network = false
  }
}

// Database Methods
/**
 * FE-9553: `notify` defaults to FALSE, and the default is the point.
 *
 * This function is reachable from a click (the retry button) AND from
 * onMounted, and a toast is only honest in the first case -- on a page load
 * nobody asked for this, so an error toast reads as though the operator caused
 * it. Following HubView's loadDeletedThreads({ notify = false }) precedent
 * rather than inventing a second convention.
 *
 * Silent by default so a new call site cannot add a spurious toast by
 * forgetting; a caller that genuinely IS a click opts in.
 */
async function loadDatabaseSettings({ notify = false } = {}) {
  try {
    // Fetch database config from API
    const response = await fetch(`${getApiBaseURL()}/api/v1/config/database`, {
      credentials: 'include',
    })
    await response.json()
  } catch (error) {
    console.error('Failed to load database settings:', error)
    if (notify) {
      showToast({
        message: 'Failed to load database settings. Check your connection and refresh the page.',
        type: 'error',
      })
    }
  }
}

function handleDatabaseSuccess(_result) {
  // Database connection successful
}

function handleDatabaseError(error) {
  console.error('Database connection failed:', error)
}

// Cookie Domain Whitelist Methods
async function loadCookieDomains() {
  loading.value.security = true
  try {
    const response = await api.settings.getCookieDomains()
    cookieDomains.value = response.data.domains || []
  } catch (error) {
    console.error('[SECURITY] Failed to load cookie domains:', error)
    securityFeedback.value = {
      type: 'error',
      message: 'Failed to load cookie domains. Please try again.',
    }
  } finally {
    loading.value.security = false
  }
}

async function addCookieDomain(domain) {
  // Check for duplicates
  if (cookieDomains.value.includes(domain)) {
    securityFeedback.value = {
      type: 'warning',
      message: `Domain "${domain}" is already in the whitelist.`,
    }
    return
  }

  try {
    await api.settings.addCookieDomain(domain)
    cookieDomains.value.push(domain)
    securityFeedback.value = {
      type: 'success',
      message: `Domain "${domain}" added successfully.`,
    }
  } catch (error) {
    console.error('[SECURITY] Failed to add cookie domain:', error)
    securityFeedback.value = {
      type: 'error',
      message: error.response?.data?.detail || 'Failed to add domain. Please try again.',
    }
  }
}

async function removeCookieDomain(domain) {
  try {
    await api.settings.removeCookieDomain(domain)
    cookieDomains.value = cookieDomains.value.filter((d) => d !== domain)
    securityFeedback.value = {
      type: 'success',
      message: `Domain "${domain}" removed successfully.`,
    }
  } catch (error) {
    console.error('[SECURITY] Failed to remove cookie domain:', error)
    securityFeedback.value = {
      type: 'error',
      message: error.response?.data?.detail || 'Failed to remove domain. Please try again.',
    }
  }
}

function clearSecurityFeedback() {
  securityFeedback.value = null
}

// Lifecycle
onMounted(async () => {
  // Resolve mode from config service so isCeMode is accurate before gating tabs
  await configService.fetchConfig()
  giljoMode.value = configService.getGiljoMode()

  // If the active tab is server-admin-only but we're not in CE mode,
  // fall back to the default product-admin tab
  if (!isCeMode.value && !PRODUCT_ADMIN_TABS.includes(activeTab.value)) {
    activeTab.value = 'identity'
  }

  // Only load server-admin config in CE mode -- other modes have no server tabs
  if (isCeMode.value) {
    await loadDatabaseSettings()
    await loadNetworkSettings()
    await loadCookieDomains()
  }
})
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
.settings-subtitle {
  color: var(--text-muted);
}

/* Pill toggle row */
.pill-toggle-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.pill-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: $border-radius-pill;
  padding: 8px 18px;
  font-size: 0.78rem;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition:
    background $transition-normal,
    color $transition-normal,
    box-shadow $transition-normal;
  background: transparent;
  color: var(--text-muted);
  border: none;
  --smooth-border-color: #{$color-pill-border};
}

.pill-toggle:hover {
  color: $color-text-hover;
}

.pill-toggle--active,
.pill-toggle--active:hover {
  background: rgba($color-brand-yellow, 0.12);
  color: $color-brand-yellow;
  box-shadow: none;
}

.pill-toggle-icon {
  flex-shrink: 0;
}

.pill-tabs-content {
  padding: 16px 0;
}
</style>
