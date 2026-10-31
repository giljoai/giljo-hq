<template>
  <div data-testid="connected-apps">
    <div class="tab-header mb-4 d-flex align-center">
      <h2 class="text-title-large">Connected apps</h2>
      <v-tooltip location="right" max-width="320">
        <template #activator="{ props }">
          <v-icon v-bind="props" size="18" color="medium-emphasis" class="ml-2">mdi-help-circle-outline</v-icon>
        </template>
        Apps you signed in to over OAuth (for example Claude or ChatGPT). Giljo HQ keeps the last 10 addresses each
        app was seen from, and deletes anything older than 90 days. Only you can see this list.
      </v-tooltip>
    </div>
    <p class="text-body-medium text-muted-a11y mb-4">
      Every app currently signed in to your account. Log one out and its next request is refused. API keys are
      listed below.
    </p>

    <v-card class="connected-apps-card smooth-border">
      <v-card-text>
        <v-alert
          v-if="!loading && apps.length === 0"
          type="info"
          variant="tonal"
          data-testid="connected-apps-empty"
        >
          No apps are signed in to your account over OAuth.
        </v-alert>

        <div v-for="app in apps" :key="app.id" class="connected-app-row" data-testid="connected-app-row">
          <div class="connected-app-main">
            <div class="d-flex align-center">
              <v-icon size="small" class="mr-2">mdi-application-outline</v-icon>
              <span class="font-weight-medium" data-testid="connected-app-name">{{ appTitle(app) }}</span>
              <span
                v-if="appSubtitle(app)"
                class="text-body-small text-muted-a11y ml-2"
                data-testid="connected-app-subtitle"
              >
                ({{ appSubtitle(app) }})
              </span>
            </div>
            <div class="text-body-small text-muted-a11y mt-1">
              Connected {{ formatDateTime(app.connected_at) }}
              <span class="mx-1">&middot;</span>
              Last used {{ humanizeTimestamp(app.last_used_at) }}
              <span class="mx-1">&middot;</span>
              <span data-testid="connected-app-ip">{{ app.last_ip || 'No address recorded yet' }}</span>
            </div>
            <div v-if="app.last_product_name" class="text-body-small text-muted-a11y mt-1" data-testid="connected-app-product">
              Last worked on {{ app.last_product_name }}
            </div>
            <div v-if="app.recent_ips.length > 1" class="text-body-small text-muted-a11y mt-1">
              Also seen from {{ app.recent_ips.filter((ip) => ip !== app.last_ip).join(', ') }}
            </div>
          </div>
          <v-btn
            variant="text"
            color="error"
            size="small"
            data-testid="connected-app-logout"
            @click="confirmLogOut(app)"
          >
            Log out
          </v-btn>
        </div>

        <div v-if="apps.length > 1" class="mt-4">
          <v-btn variant="outlined" color="error" size="small" data-testid="connected-apps-logout-all" @click="confirmLogOutAll">
            Log out all apps
          </v-btn>
        </div>
      </v-card-text>
    </v-card>

    <BaseDialog
      v-model="showDialog"
      type="danger"
      :title="target ? `Log out ${appTitle(target)}?` : 'Log out all apps?'"
      :confirm-label="target ? 'Log out app' : 'Log out all apps'"
      :loading="working"
      @confirm="doLogOut"
      @cancel="cancelLogOut"
    >
      <p class="text-body-large" data-testid="connected-apps-confirm-text">
        {{ target ? 'This app will be refused on its next request.' : 'Every app signed in to your account will be refused on its next request.' }}
        It can sign in again, and you will be asked to approve it.
      </p>
    </BaseDialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { formatDistanceToNow } from 'date-fns'
import api from '@/services/api'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { useFormatDate } from '@/composables/useFormatDate'
import { useToast } from '@/composables/useToast'

const { formatDateTime } = useFormatDate()
const { showToast } = useToast()

const apps = ref([])
const loading = ref(false)
const showDialog = ref(false)
const working = ref(false)
const target = ref(null)

const SHARED_CLIENT_ID = 'giljo-mcp-default'

function reportedName(app) {
  if (!app.mcp_client_name) return ''
  return app.mcp_client_version ? `${app.mcp_client_name} ${app.mcp_client_version}` : app.mcp_client_name
}

function appTitle(app) {
  if (app.client_id === SHARED_CLIENT_ID) {
    return reportedName(app) || app.last_user_agent || app.client_name
  }
  return app.client_name
}

function appSubtitle(app) {
  const title = appTitle(app)
  const secondary = app.client_id === SHARED_CLIENT_ID ? app.client_name : reportedName(app)
  return secondary && secondary !== title ? secondary : ''
}

function humanizeTimestamp(timestamp) {
  if (!timestamp) return 'never'
  try {
    return formatDistanceToNow(new Date(timestamp), { addSuffix: true })
  } catch {
    return 'unknown'
  }
}

async function loadApps({ notify = false } = {}) {
  loading.value = true
  try {
    const response = await api.connectedApps.list()
    apps.value = response.data
  } catch (err) {
    console.error('[Connected apps] Failed to load:', err)
    if (notify && err.response?.status !== 401) {
      showToast({ message: 'Unable to load connected apps. Try refreshing the page.', type: 'error' })
    }
  } finally {
    loading.value = false
  }
}

function confirmLogOut(app) {
  target.value = app
  showDialog.value = true
}

function confirmLogOutAll() {
  target.value = null
  showDialog.value = true
}

function cancelLogOut() {
  showDialog.value = false
  target.value = null
}

async function doLogOut() {
  working.value = true
  try {
    if (target.value) {
      await api.connectedApps.logOut(target.value.id)
    } else {
      await api.connectedApps.logOutAll()
    }
    showDialog.value = false
    target.value = null
    await loadApps({ notify: true })
  } catch (err) {
    console.error('[Connected apps] Failed to log out:', err)
    showToast({ message: 'Failed to log the app out. Please try again.', type: 'error' })
  } finally {
    working.value = false
  }
}

onMounted(() => loadApps())
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;

.connected-apps-card {
  border: none !important;
  border-radius: $border-radius-rounded !important;
  overflow: hidden;
}

.connected-app-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 0;

  & + & {
    border-top: 1px solid rgba(var(--v-theme-on-surface), 0.08);
  }
}

.connected-app-main {
  min-width: 0;
  overflow-wrap: anywhere;
}

.v-btn:focus-visible {
  outline: 2px solid rgba(var(--v-theme-primary), 0.5);
  outline-offset: 2px;
}
</style>
