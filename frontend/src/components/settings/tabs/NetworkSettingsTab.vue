<template>
  <div>
    <div class="tab-header mb-4">
      <h2 class="text-title-large">Network Configuration</h2>
    </div>
    <v-card variant="flat" class="smooth-border network-card">
    <v-card-text>
      <div v-if="loading" class="d-flex justify-center py-8">
        <v-progress-circular indeterminate color="primary" />
      </div>

      <template v-else>
        <h3 class="text-title-large mb-1">Server Configuration</h3>
        <p class="text-body-medium mb-4">Network settings are configured during installation. To modify the external host or ports, update config.yaml and restart the server. Authentication is always enabled for all connections (local and remote). Use OS firewall to control network access.</p>

        <div class="server-info mb-2" data-test="server-info">
          <div class="server-info-row">
            <span class="server-info-label">Host IP</span>
            <span class="server-info-value" data-test="server-host">{{ serverHostDisplay }}</span>
          </div>
          <div class="server-info-row">
            <span class="server-info-label">Port</span>
            <span class="server-info-value" data-test="server-port">{{ serverPort }}</span>
          </div>
        </div>

        <v-divider class="my-6" />

        <div data-test="https-status-section">
          <div class="d-flex align-center justify-space-between mb-1">
            <h3 class="text-title-large">HTTPS Encryption</h3>
            <v-switch
              :model-value="sslStatus.ssl_enabled"
              :loading="sslToggling"
              :disabled="sslToggling || (!sslStatus.ssl_enabled && !sslStatus.has_certificate)"
              :label="sslStatus.ssl_enabled ? 'Enabled' : 'Disabled'"
              color="success"
              hide-details
              density="compact"
              data-test="ssl-toggle"
              @update:model-value="toggleSsl"
            />
          </div>

          <p
            v-if="!sslStatus.ssl_enabled && !sslStatus.has_certificate"
            class="text-body-small text-muted-a11y mb-3"
            data-test="ssl-needs-cert-hint"
          >
            Provide a certificate below to enable HTTPS.
          </p>

          <v-alert
            v-if="isHttpContext && !httpCueDismissed"
            type="warning"
            variant="tonal"
            density="compact"
            class="mb-4"
            closable
            data-test="http-context-cue"
            @click:close="httpCueDismissed = true"
          >
            <strong>Running over HTTP.</strong> Traffic on your network is unencrypted, and OS-level
            desktop notifications fall back to an in-app toast. On a trusted home/LAN this is fine —
            to encrypt, provide a certificate below and enable HTTPS.
          </v-alert>

          <v-alert
            :type="sslStatus.ssl_enabled ? 'success' : 'info'"
            variant="tonal"
            class="mb-4"
            data-test="https-status-alert"
          >
            <div class="d-flex align-center">
              <v-icon start>{{ sslStatus.ssl_enabled ? 'mdi-lock' : 'mdi-lock-open-outline' }}</v-icon>
              <div class="cert-status-line">
                <strong>HTTPS:</strong> {{ sslStatus.ssl_enabled ? 'Enabled' : 'Disabled' }}<span
                  v-if="sslStatus.has_certificate && !sslStatus.ssl_enabled"
                  class="text-body-small ml-1"
                >(certificate provided)</span>
                <span
                  v-if="sslStatus.has_certificate"
                  class="text-body-small ml-4 cert-status"
                  data-test="cert-status"
                  :title="sslStatus.cert_path || ''"
                >
                  <v-icon size="x-small" class="mr-1">{{ sslStatus.cert_expired ? 'mdi-alert-circle' : 'mdi-certificate' }}</v-icon><span
                    v-if="sslStatus.cert_not_after"
                    :class="{ 'cert-expired': sslStatus.cert_expired }"
                  >{{ sslStatus.cert_expired ? 'Certificate EXPIRED on' : 'Certificate valid until' }} {{ sslStatus.cert_not_after }}<span v-if="sslStatus.cert_sans && sslStatus.cert_sans.length"> &middot; covers {{ sslStatus.cert_sans.join(', ') }}</span></span><span v-else>Certificate provided</span>
                </span>
              </div>
            </div>
          </v-alert>

          <v-alert
            v-if="sslRestartRequired"
            type="warning"
            variant="tonal"
            class="mb-4"
            data-test="ssl-restart-alert"
          >
            <div class="d-flex align-center">
              <v-icon start>mdi-restart</v-icon>
              <div>
                <strong>Server restart required</strong> for HTTPS changes to take effect.
              </div>
            </div>
          </v-alert>

          <v-alert
            v-if="showMcpReattachWarning"
            type="warning"
            variant="tonal"
            class="mb-4"
            closable
            @click:close="showMcpReattachWarning = false"
          >
            <strong>Action required:</strong> Changing the protocol — in either direction
            (HTTP&rarr;HTTPS or HTTPS&rarr;HTTP) — changes the MCP server URL, so it invalidates
            every existing MCP tool connection. You must remove and re-add your AI coding agents,
            and re-authenticate:
            <ol class="mt-2 ml-4 text-body-medium">
              <li>Remove existing connections: <code>claude mcp remove giljo_mcp</code>, <code>codex mcp remove giljo_mcp</code>, <code>opencode mcp remove giljo_mcp</code></li>
              <li>Delete old API keys from User Settings and regenerate them</li>
              <li>Re-authenticate: API-key agents use the new key; OAuth agents must re-consent on the new URL</li>
              <li>Use the Configurator to generate new connection commands</li>
            </ol>
          </v-alert>

          <v-alert
            v-if="sslError"
            type="error"
            variant="tonal"
            class="mb-4"
            closable
            data-test="ssl-error-alert"
            @click:close="sslError = ''"
          >
            {{ sslError }}
          </v-alert>

          <v-divider class="my-6" />

          <h3 class="text-title-large mb-1">Provide a certificate (bring your own)</h3>
          <p class="text-body-medium mb-3" data-test="cert-provision-section">
            GiljoAI does not create certificates. Supply a certificate trusted by your browsers and
            AI coding agents — a real CA, your organisation's internal CA, or a local CA. Then enable
            HTTPS above.
          </p>

          <v-expansion-panels variant="accordion" class="mb-4" data-test="cert-provision-panels">
            <v-expansion-panel eager data-test="cert-upload-panel">
              <v-expansion-panel-title>
                <v-icon start size="small">mdi-upload</v-icon>
                Option A — Upload PEM files
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <v-file-input
                  v-model="uploadCertFile"
                  label="Certificate (PEM, full chain if applicable)"
                  variant="outlined"
                  density="compact"
                  accept=".pem,.crt,.cer"
                  prepend-icon="mdi-certificate"
                  class="mb-2"
                  data-test="cert-upload-cert"
                />
                <v-file-input
                  v-model="uploadKeyFile"
                  label="Private key (PEM)"
                  variant="outlined"
                  density="compact"
                  accept=".pem,.key"
                  prepend-icon="mdi-key"
                  class="mb-2"
                  data-test="cert-upload-key"
                />
                <v-btn
                  color="primary"
                  variant="flat"
                  :loading="certProvisioning"
                  prepend-icon="mdi-upload"
                  data-test="cert-upload-btn"
                  @click="uploadCert"
                >
                  Upload certificate
                </v-btn>
              </v-expansion-panel-text>
            </v-expansion-panel>

            <v-expansion-panel eager data-test="cert-ref-panel">
              <v-expansion-panel-title>
                <v-icon start size="small">mdi-file-link</v-icon>
                Option B — Reference by path on this server
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <v-text-field
                  v-model="refCertPath"
                  label="Certificate path"
                  variant="outlined"
                  density="compact"
                  placeholder="/etc/giljo/certs/server.pem"
                  class="mb-2"
                  data-test="cert-ref-cert"
                />
                <v-text-field
                  v-model="refKeyPath"
                  label="Private key path"
                  variant="outlined"
                  density="compact"
                  placeholder="/etc/giljo/certs/server.key"
                  class="mb-2"
                  data-test="cert-ref-key"
                />
                <v-btn
                  color="primary"
                  variant="outlined"
                  :loading="certProvisioning"
                  prepend-icon="mdi-file-link"
                  data-test="cert-ref-btn"
                  @click="referenceCert"
                >
                  Use these paths
                </v-btn>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>

          <v-alert
            v-if="certProvisionError"
            type="error"
            variant="tonal"
            density="compact"
            class="mb-4"
            closable
            data-test="cert-provision-error"
            @click:close="certProvisionError = ''"
          >
            {{ certProvisionError }}
          </v-alert>
          <v-alert
            v-if="certProvisionSuccess"
            type="success"
            variant="tonal"
            density="compact"
            class="mb-4"
            closable
            data-test="cert-provision-success"
            @click:close="certProvisionSuccess = ''"
          >
            {{ certProvisionSuccess }}
          </v-alert>

          <p class="text-body-medium text-muted-a11y mb-0" data-test="https-guide-link">
            <v-icon size="small" class="mr-1">mdi-book-open-variant</v-icon>
            Need a certificate, or need to trust it on other machines?
            <router-link
              :to="{ name: 'UserGuide', hash: '#https-and-browser-configuration' }"
              class="guide-link"
            >See the Self-Hosting &amp; Network Setup guide</router-link>.
          </p>
        </div>

        <v-divider class="my-6" />

        <div data-test="cookie-whitelist-section">
          <h3 class="text-title-large mb-3">Cookie Domain Whitelist</h3>

          <p class="text-body-medium mb-4">
            Configure which domain names are allowed for cross-port authentication cookies. This enables
            secure authentication when accessing the dashboard from different ports or subdomains on the
            same machine. IP addresses are automatically allowed. Only add domain names here (e.g., app.example.com, localhost).
          </p>

          <v-progress-linear
            v-if="cookieLoading"
            data-test="cookie-loading-indicator"
            indeterminate
            color="primary"
            class="mb-4"
          />

          <div v-if="cookieDomains.length > 0" class="mb-4">
            <v-list density="compact" class="mb-3">
              <v-list-item v-for="domain in cookieDomains" :key="domain" :title="domain">
                <template #append>
                  <v-btn
                    icon="mdi-delete"
                    size="small"
                    variant="text"
                    color="error"
                    data-test="cookie-delete-domain-btn"
                    :disabled="cookieLoading"
                    :aria-label="`Delete domain ${domain}`"
                    @click="removeCookieDomain(domain)"
                  />
                </template>
              </v-list-item>
            </v-list>
          </div>

          <v-alert v-else type="info" variant="outlined" class="mb-4" data-test="cookie-empty-state">
            No domain names configured. IP-based access only.
          </v-alert>

          <v-text-field
            v-model="newCookieDomain"
            data-test="cookie-new-domain-input"
            label="Add Domain Name"
            variant="outlined"
            placeholder="app.example.com"
            hint="Enter a domain name (no IP addresses)"
            persistent-hint
            :rules="[validateCookieDomain]"
            :error-messages="cookieDomainError"
            :disabled="cookieLoading"
            class="mb-2"
            @keyup.enter="addCookieDomain"
          >
            <template #append>
              <v-btn
                icon="mdi-plus"
                color="primary"
                variant="text"
                data-test="cookie-add-domain-btn"
                :disabled="!newCookieDomain || !!cookieDomainError || cookieLoading"
                aria-label="Add domain"
                @click="addCookieDomain"
              />
            </template>
          </v-text-field>

          <v-alert
            v-if="cookieFeedback"
            :type="cookieFeedback.type"
            variant="tonal"
            class="mb-4"
            closable
            data-test="cookie-feedback-alert"
            @click:close="emit('clear-cookie-feedback')"
          >
            {{ cookieFeedback.message }}
          </v-alert>
        </div>
      </template>
    </v-card-text>

    <v-card-actions>
      <v-spacer />
      <v-btn variant="text" data-test="reload-button" @click="handleRefresh">
        <v-icon start>mdi-refresh</v-icon>
        Reload
      </v-btn>
    </v-card-actions>
  </v-card>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { getApiBaseURL } from '@/config/api'

const props = defineProps({
  serverHostDisplay: {
    type: String,
    default: 'localhost',
  },
  serverPort: {
    type: [Number, String],
    default: 7272,
  },
  sslEnabled: {
    type: Boolean,
    default: false,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  cookieDomains: {
    type: Array,
    default: () => [],
  },
  cookieLoading: {
    type: Boolean,
    default: false,
  },
  cookieFeedback: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['refresh', 'add-domain', 'remove-domain', 'reload-domains', 'clear-cookie-feedback'])

const sslStatus = ref({
  ssl_enabled: false,
  has_certificate: false,
  cert_path: null,
  key_path: null,
  cert_not_after: null,
  cert_sans: [],
  cert_expired: false,
})
const sslToggling = ref(false)
const sslRestartRequired = ref(false)
const sslError = ref('')
const showMcpReattachWarning = ref(false)

const isHttpContext = ref(typeof window !== 'undefined' && !window.isSecureContext)
const httpCueDismissed = ref(false)

const uploadCertFile = ref(null)
const uploadKeyFile = ref(null)
const refCertPath = ref('')
const refKeyPath = ref('')
const certProvisioning = ref(false)
const certProvisionError = ref('')
const certProvisionSuccess = ref('')

function handleRefresh() {
  emit('refresh')
  emit('reload-domains')
  loadSslStatus()
}

const newCookieDomain = ref('')
const cookieDomainError = ref('')

function validateCookieDomain(value) {
  if (!value) {
    cookieDomainError.value = ''
    return true
  }
  const trimmed = value.trim()
  const ipPattern = /^(\d{1,3}\.){3}\d{1,3}$/
  if (ipPattern.test(trimmed)) {
    cookieDomainError.value = 'IP addresses are not allowed. Use domain names only.'
    return false
  }
  const domainPattern =
    /^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/
  if (!domainPattern.test(trimmed)) {
    cookieDomainError.value = 'Invalid domain format. Example: app.example.com'
    return false
  }
  cookieDomainError.value = ''
  return true
}

watch(newCookieDomain, (value) => {
  validateCookieDomain(value)
})

function addCookieDomain() {
  const trimmed = newCookieDomain.value.trim()
  if (!trimmed) return
  if (!validateCookieDomain(trimmed)) return
  if (props.cookieDomains.includes(trimmed)) {
    cookieDomainError.value = `Domain "${trimmed}" is already in the whitelist.`
    return
  }
  emit('add-domain', trimmed)
  newCookieDomain.value = ''
  cookieDomainError.value = ''
}

function removeCookieDomain(domain) {
  emit('remove-domain', domain)
}

async function loadSslStatus() {
  try {
    const csrfToken = document.cookie.match(/csrf_token=([^;]+)/)?.[1]
    const response = await fetch(`${getApiBaseURL()}/api/v1/config/ssl`, {
      credentials: 'include',
      headers: {
        ...(csrfToken && { 'X-CSRF-Token': csrfToken }),
      },
    })
    if (response.ok) {
      sslStatus.value = await response.json()
    }
  } catch (error) {
    console.error('[NETWORK] Failed to load SSL status:', error)
    sslStatus.value.ssl_enabled = props.sslEnabled
  }
}

async function toggleSsl(enabled) {
  sslToggling.value = true
  sslError.value = ''
  sslRestartRequired.value = false

  try {
    const csrfToken = document.cookie.match(/csrf_token=([^;]+)/)?.[1]
    const response = await fetch(`${getApiBaseURL()}/api/v1/config/ssl`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(csrfToken && { 'X-CSRF-Token': csrfToken }),
      },
      body: JSON.stringify({ enabled }),
    })

    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Failed to toggle SSL')
    }

    const result = await response.json()
    sslStatus.value = result
    sslRestartRequired.value = result.restart_required
    showMcpReattachWarning.value = true
  } catch (error) {
    sslError.value = error.message || 'Failed to toggle SSL'
    console.error('[NETWORK] SSL toggle failed:', error)
  } finally {
    sslToggling.value = false
  }
}

function _firstFile(model) {
  if (!model) return null
  return Array.isArray(model) ? model[0] : model
}

async function uploadCert() {
  const certFile = _firstFile(uploadCertFile.value)
  const keyFile = _firstFile(uploadKeyFile.value)
  if (!certFile || !keyFile) {
    certProvisionError.value = 'Select both a certificate (PEM) and a private key (PEM) file.'
    return
  }
  certProvisioning.value = true
  certProvisionError.value = ''
  certProvisionSuccess.value = ''
  try {
    const csrfToken = document.cookie.match(/csrf_token=([^;]+)/)?.[1]
    const form = new FormData()
    form.append('cert_file', certFile)
    form.append('key_file', keyFile)
    const response = await fetch(`${getApiBaseURL()}/api/v1/config/ssl/cert/upload`, {
      method: 'POST',
      credentials: 'include',
      headers: { ...(csrfToken && { 'X-CSRF-Token': csrfToken }) },
      body: form,
    })
    if (!response.ok) {
      const err = await response.json().catch(() => ({}))
      throw new Error(err.detail || `Upload failed (${response.status})`)
    }
    const result = await response.json()
    sslStatus.value = { ...sslStatus.value, has_certificate: result.has_certificate, cert_path: result.cert_path, key_path: result.key_path }
    certProvisionSuccess.value = 'Certificate uploaded. Enable HTTPS above to apply (a server restart is required).'
    uploadCertFile.value = null
    uploadKeyFile.value = null
  } catch (error) {
    certProvisionError.value = error.message || 'Certificate upload failed'
  } finally {
    certProvisioning.value = false
  }
}

async function referenceCert() {
  if (!refCertPath.value || !refKeyPath.value) {
    certProvisionError.value = 'Enter both the certificate path and the key path on this server.'
    return
  }
  certProvisioning.value = true
  certProvisionError.value = ''
  certProvisionSuccess.value = ''
  try {
    const csrfToken = document.cookie.match(/csrf_token=([^;]+)/)?.[1]
    const response = await fetch(`${getApiBaseURL()}/api/v1/config/ssl/cert/reference`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(csrfToken && { 'X-CSRF-Token': csrfToken }),
      },
      body: JSON.stringify({ cert_path: refCertPath.value, key_path: refKeyPath.value }),
    })
    if (!response.ok) {
      const err = await response.json().catch(() => ({}))
      throw new Error(err.detail || `Reference failed (${response.status})`)
    }
    const result = await response.json()
    sslStatus.value = { ...sslStatus.value, has_certificate: result.has_certificate, cert_path: result.cert_path, key_path: result.key_path }
    certProvisionSuccess.value = 'Certificate path referenced. Enable HTTPS above to apply (a server restart is required).'
  } catch (error) {
    certProvisionError.value = error.message || 'Certificate reference failed'
  } finally {
    certProvisioning.value = false
  }
}

onMounted(() => {
  loadSslStatus()
})
</script>

<style lang="scss" scoped>
@use '../../../styles/settings-tab-card' as settingsCard;
.network-card {
  @include settingsCard.settings-tab-card-surface;
}

/* Read-only server info as label:value rows (not editable-looking fields) */
.server-info-row {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.35rem 0;
}
.server-info-label {
  flex: 0 0 5.5rem;
  color: var(--text-secondary, rgba(255, 255, 255, 0.6));
  font-size: 0.875rem;
  font-weight: 600;
}
.server-info-value {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.95rem;
}
.guide-link {
  color: var(--agent-yellow-primary, #e0b800);
  text-decoration: none;
}
.guide-link:hover {
  text-decoration: underline;
}
.cert-status-line {
  word-break: break-word;
}
.cert-expired {
  color: rgb(var(--v-theme-error));
  font-weight: 600;
}
</style>
