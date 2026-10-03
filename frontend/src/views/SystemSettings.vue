<template>
  <v-container>
    <h1 class="text-headline-large mb-2">Admin Settings</h1>
    <p class="text-body-large mb-4 settings-subtitle">
      Configure server and system-wide settings (Admin only)
    </p>

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

    <div class="pill-tabs-content">
      <v-window v-model="activeTab" class="global-tabs-window main-window-tabs">
        <v-window-item value="identity">
          <IdentityTab />
        </v-window-item>

        <v-window-item v-if="isCeMode" value="network">
          <NetworkSettingsTab
            :server-host-display="serverHostDisplay"
            :server-port="serverPort"
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

        <v-window-item v-if="isCeMode" value="database">
          <DatabaseConnection
            ref="databaseConnectionRef"
            :readonly="true"
            :show-title="true"
            :show-info-banner="true"
            :show-test-button="true"
            test-button-text="Test Connection"
            @connection-error="handleDatabaseError"
          >
            <template #actions>
              <v-btn variant="text" data-test="db-reload-btn" @click="reloadDatabaseSettings">
                <v-icon start>mdi-refresh</v-icon>
                Reload connection details
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
import { parseErrorResponse, fetchResponseError } from '@/utils/errorMessages'
import configService from '@/services/configService'
import { isCeModeValue } from '@/composables/useGiljoMode'

import DatabaseConnection from '@/components/DatabaseConnection.vue'
import IdentityTab from '@/components/settings/tabs/IdentityTab.vue'
import NetworkSettingsTab from '@/components/settings/tabs/NetworkSettingsTab.vue'

const { showToast } = useToast()
const giljoMode = ref('ce')
const isCeMode = computed(() => isCeModeValue(giljoMode.value))

const activeTab = ref('identity')

const PRODUCT_ADMIN_TABS = ['identity']

const loading = ref({
  network: false,
  security: false,
})

const serverHostDisplay = ref('')
const serverPort = ref(null)

const cookieDomains = ref([])
const securityFeedback = ref(null)

async function loadNetworkSettings() {
  loading.value.network = true
  try {
    const response = await fetch(`${getApiBaseURL()}/api/v1/config/network-info`, {
      credentials: 'include',
    })
    if (!response.ok) throw await fetchResponseError(response)
    const info = await response.json()
    serverHostDisplay.value = info.host_display
    serverPort.value = info.port
  } catch (error) {
    showToast({ message: `Could not load the network settings: ${parseErrorResponse(error).message}`, type: 'error' })
  } finally {
    loading.value.network = false
  }
}

const databaseConnectionRef = ref(null)

async function reloadDatabaseSettings() {
  try {
    await databaseConnectionRef.value?.loadSettings()
  } catch (error) {
    console.error('Failed to load database settings:', error)
    showToast({
      message: 'Failed to load database settings. Check your connection and refresh the page.',
      type: 'error',
    })
  }
}

function handleDatabaseError(error) {
  console.error('Database connection failed:', error)
}

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
      message: parseErrorResponse(error).message || 'Failed to add domain. Please try again.',
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
      message: parseErrorResponse(error).message || 'Failed to remove domain. Please try again.',
    }
  }
}

function clearSecurityFeedback() {
  securityFeedback.value = null
}

onMounted(async () => {
  await configService.fetchConfig()
  giljoMode.value = configService.getGiljoMode()

  if (!isCeMode.value && !PRODUCT_ADMIN_TABS.includes(activeTab.value)) {
    activeTab.value = 'identity'
  }

  if (isCeMode.value) {
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
