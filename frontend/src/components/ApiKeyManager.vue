<template>
  <div>
    <div class="tab-header mb-4 d-flex align-center">
      <h2 class="text-title-large">API Keys</h2>
      <v-tooltip location="right" max-width="300">
        <template #activator="{ props }">
          <v-icon v-bind="props" size="18" color="medium-emphasis" class="ml-2">mdi-help-circle-outline</v-icon>
        </template>
        Keys are automatically generated when you copy an MCP connection command from the Connect tab.
      </v-tooltip>
    </div>
    <p class="text-body-medium text-muted-a11y mb-4">View and revoke API keys used by AI coding agent integrations</p>

    <v-card class="apikey-card smooth-border">

    <v-chip
      v-if="apiKeys.length > 0"
      class="ml-4 mt-2"
      color="success"
      size="small"
      variant="tonal"
    >
      {{ activeKeyCount }} active {{ activeKeyCount === 1 ? 'key' : 'keys' }}
    </v-chip>

    <v-card-text>
      <v-alert v-if="!loading && apiKeys.length === 0" type="info" variant="tonal" class="mb-4">
        No API keys yet. Copy an MCP connection command from the
        <strong>Connect</strong> tab to automatically generate one.
      </v-alert>

      <v-data-table
        v-if="apiKeys.length > 0"
        :items="apiKeys"
        :headers="headers"
        :loading="loading"
        class="elevation-0"
      >
        <template #item.name="{ item }">
          <div class="d-flex align-center">
            <v-icon size="small" class="mr-2">mdi-label</v-icon>
            <span class="font-weight-medium">{{ item.name }}</span>
          </div>
        </template>

        <template #item.key_prefix="{ item }">
          <code class="text-body-small">{{ item.key_prefix }}...</code>
        </template>

        <template #item.created_at="{ item }">
          <span class="text-body-small">{{ formatDateTime(item.created_at) }}</span>
        </template>

        <template #item.last_used="{ item }">
          <span class="text-body-small">{{ humanizeTimestamp(item.last_used) }}</span>
        </template>

        <template #item.expires_at="{ item }">
          <v-chip v-if="isExpired(item.expires_at)" color="error" size="small" variant="flat">
            Expired
          </v-chip>
          <span v-else-if="item.expires_at" :class="expiryClass(item.expires_at)" class="text-body-small">
            {{ humanizeTimestamp(item.expires_at) }}
          </span>
          <span v-else class="text-body-small text-muted-a11y">No expiry</span>
        </template>

        <template #item.actions="{ item }">
          <v-tooltip text="Revoke this API key">
            <template #activator="{ props }">
              <v-btn
                icon="mdi-delete"
                size="small"
                variant="text"
                color="error"
                v-bind="props"
                @click="confirmRevoke(item)"
              />
            </template>
          </v-tooltip>
        </template>
      </v-data-table>
    </v-card-text>

    <BaseDialog
      v-model="showRevokeDialog"
      type="danger"
      title="Revoke API Key?"
      confirm-text="DELETE"
      confirm-label="Revoke Key"
      :loading="revoking"
      @confirm="revokeKey"
      @cancel="cancelRevoke"
    >
      <p class="text-body-large mb-2">You are about to revoke the API key:</p>
      <v-card variant="flat" class="mb-4 pa-3 smooth-border">
        <div class="d-flex align-center">
          <v-icon class="mr-2">mdi-label</v-icon>
          <strong>{{ keyToRevoke?.name }}</strong>
        </div>
        <div class="d-flex align-center mt-2">
          <v-icon class="mr-2" size="small">mdi-key</v-icon>
          <code class="text-body-small">{{ keyToRevoke?.key_prefix }}...</code>
        </div>
      </v-card>

      <v-alert type="info" variant="tonal" density="compact">
        This action cannot be undone. Any applications using this key will immediately lose
        access to the API.
      </v-alert>
    </BaseDialog>
  </v-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { formatDistanceToNow } from 'date-fns'
import api from '@/services/api'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { useFormatDate } from '@/composables/useFormatDate'
import { useToast } from '@/composables/useToast'

const { formatDateTime } = useFormatDate()
const { showToast } = useToast()

const apiKeys = ref([])
const loading = ref(false)
const showRevokeDialog = ref(false)
const revoking = ref(false)
const keyToRevoke = ref(null)

const headers = [
  { title: 'Name', key: 'name', sortable: true },
  { title: 'Key Prefix', key: 'key_prefix', sortable: false },
  { title: 'Created', key: 'created_at', sortable: true },
  { title: 'Last Used', key: 'last_used', sortable: true },
  { title: 'Expires', key: 'expires_at', sortable: true },
  { title: 'Actions', key: 'actions', sortable: false, align: 'end' },
]

function humanizeTimestamp(timestamp) {
  if (!timestamp) return 'Never'
  try {
    return formatDistanceToNow(new Date(timestamp), { addSuffix: true })
  } catch {
    return 'Unknown'
  }
}

function isExpired(expiresAt) {
  if (!expiresAt) return false
  return new Date(expiresAt) < new Date()
}

function daysUntilExpiry(expiresAt) {
  if (!expiresAt) return Infinity
  const diff = new Date(expiresAt) - new Date()
  return Math.ceil(diff / (1000 * 60 * 60 * 24))
}

function expiryClass(expiresAt) {
  const days = daysUntilExpiry(expiresAt)
  if (days < 7) return 'text-error'
  if (days < 30) return 'text-warning'
  return 'text-success'
}

const activeKeyCount = computed(() => apiKeys.value.filter((k) => k.is_active).length)

async function loadKeys({ notify = false } = {}) {
  loading.value = true
  try {
    const response = await api.apiKeys.list()
    apiKeys.value = response.data
  } catch (err) {
    console.error('[API Keys] Failed to load:', err)
    if (notify && err.response?.status !== 401) {
      showToast({ message: 'Unable to load API keys. Try refreshing the page.', type: 'error' })
    }
  } finally {
    loading.value = false
  }
}

async function refreshKeys() {
  await loadKeys({ notify: true })
}

function confirmRevoke(key) {
  keyToRevoke.value = key
  showRevokeDialog.value = true
}

function cancelRevoke() {
  showRevokeDialog.value = false
  keyToRevoke.value = null
}

async function revokeKey() {
  if (!keyToRevoke.value) return

  revoking.value = true
  try {
    await api.apiKeys.delete(keyToRevoke.value.id)

    const revokedId = keyToRevoke.value.id
    apiKeys.value = apiKeys.value.filter((k) => k.id !== revokedId)
    await loadKeys({ notify: true })

    try {
      window.dispatchEvent(new Event('api-key-revoked'))
    } catch { /* no-op */ }

    showRevokeDialog.value = false
    keyToRevoke.value = null
  } catch (err) {
    console.error('[API Keys] Failed to revoke:', err)
    showToast({ message: 'Failed to revoke API key. Please try again.', type: 'error' })
  } finally {
    revoking.value = false
  }
}


onMounted(() => {
  loadKeys()
  window.addEventListener('api-key-created', refreshKeys)
})

onUnmounted(() => {
  window.removeEventListener('api-key-created', refreshKeys)
})
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;

/* 0873: smooth-border card panel */
.apikey-card {
  border: none !important;
  border-radius: $border-radius-rounded !important;
  overflow: hidden;

  :deep(.v-table) {
    background: transparent;
  }
}

.v-data-table {
  border-radius: $border-radius-default;
}

code {
  background-color: rgba(var(--v-theme-surface-variant), 0.5);
  padding: 2px 6px;
  border-radius: $border-radius-sharp;
  font-family: 'Courier New', monospace;
}

.v-code {
  font-family: 'Courier New', monospace;
  font-size: 0.875rem;
  line-height: 1.5;
}

/* Accessibility: Focus indicators */
.v-btn:focus-visible {
  outline: 2px solid rgba(var(--v-theme-primary), 0.5);
  outline-offset: 2px;
}
</style>
