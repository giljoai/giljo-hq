<template>
  <div class="connect-tool-card" :data-testid="`connect-card-${toolId}`">
    <div class="server-line">
      <span class="server-line-label">SERVER</span>
      <span class="server-line-url" data-testid="server-url-field">{{ serverUrl }}</span>
      <v-icon
        size="14"
        class="server-line-icon"
        :data-testid="isCe ? 'server-url-pencil' : 'server-url-lock'"
        :aria-label="isCe ? 'Editable server URL' : 'Managed server URL'"
        @click="isCe ? (editingServer = !editingServer) : null"
      >
        {{ isCe ? 'mdi-pencil-outline' : 'mdi-lock-outline' }}
      </v-icon>
      <span class="server-line-hint">{{ isCe ? 'editable' : 'managed' }}</span>
    </div>

    <v-expand-transition>
      <div v-if="isCe && editingServer" class="server-edit-fields">
        <v-text-field
          v-model="serverHostname"
          label="Hostname / IP"
          variant="outlined"
          density="compact"
          hide-details
          data-testid="server-edit-hostname"
          class="server-field"
        />
        <v-text-field
          v-model="serverPort"
          label="Port"
          variant="outlined"
          density="compact"
          hide-details
          data-testid="server-edit-port"
          class="server-field server-field--port"
        />
        <v-btn icon="mdi-check" size="x-small" variant="text" @click="editingServer = false" />
      </div>
    </v-expand-transition>

    <p v-if="method === 'key' && baseMethod === 'key'" class="connect-subline" data-testid="apikey-only-note">
      {{ toolLabel }} uses an API key. Browser sign-in is not supported. Two moves:
    </p>
    <p v-else-if="method === 'manual'" class="connect-subline">
      Copy this server config into your client&rsquo;s MCP settings.
    </p>
    <p v-else-if="method === 'key'" class="connect-subline">
      Generate a key, then paste one command.
    </p>
    <p v-else class="connect-subline">
      Paste one command. Your browser opens for a one-click sign-in.
    </p>

    <div v-if="method === 'manual'" class="command-card" data-testid="web-endpoint-block">
      <div class="command-card-head">
        <span class="command-label">Connector URL</span>
        <button class="copy-pill" data-testid="web-endpoint-copy-btn" @click="copyText(mcpEndpoint)">
          <v-icon size="11">mdi-content-copy</v-icon>COPY
        </button>
      </div>
      <pre class="command-code config-code">{{ mcpEndpoint }}</pre>
      <p class="connect-subline">
        Connecting a web app or IDE instead? Paste this URL into its MCP connector settings
        (claude.ai, ChatGPT, and most IDEs), then sign in when the browser opens. No key needed.
      </p>
    </div>

    <SetupStep2KeyFlow
      v-if="showKeyStep"
      :checking-key="checkingKey"
      :generating-key="generatingKey"
      :generated-key="generatedKey"
      :existing-key-prefix="existingKeyPrefix"
      :key-error="keyError"
      :has-key="hasKey"
      :needs-cert-trust="needsCertTrust"
      :active-normalized-id="normalizedId"
      :tool-label="toolLabel"
      :platform="platform"
      :cert-command="certCommand"
      :env-var-text="envVarText"
      :config-command="configCommand"
      :is-generic="method === 'manual'"
      :color-muted="COLOR_MUTED"
      :color-success="COLOR_SUCCESS"
      @generate-key="handleGenerateKey"
      @clear-key-error="keyError = ''"
      @set-platform="(p) => (platform = p)"
      @copy-text="({ text }) => copyText(text)"
    />

    <p v-if="showCertTrustLink" class="connect-subline" data-testid="node-tls-note">
      Node-based clients such as OpenCode, Claude Code, and Codex reject a private or
      self-signed certificate until it is in your trust store.
    </p>
    <div v-if="showCertTrustLink" class="fallback-row">
      <span
        class="fallback-link"
        role="button"
        tabindex="0"
        data-testid="cert-trust-link"
        @click="showCertTrust = true"
        @keydown.enter.prevent="showCertTrust = true"
      >
        Tool rejecting the connection? Trust the certificate.
      </span>
    </div>

    <div v-if="method === 'oauth'" class="command-card" data-testid="oauth-section">
      <div class="command-card-head">
        <span class="command-step">1.</span>
        <span class="command-label" data-testid="oauth-command-label">Paste in your {{ toolLabel }} terminal</span>
        <button class="copy-pill" data-testid="oauth-copy-btn" @click="copyText(oauthCommand)">
          <v-icon size="11">mdi-content-copy</v-icon>COPY
        </button>
      </div>
      <pre class="command-code config-code">{{ oauthCommand }}</pre>

      <div v-if="needsCertTrust" class="cert-note" data-testid="oauth-cert-note">
        <v-icon size="13" :color="COLOR_MUTED">mdi-shield-lock-outline</v-icon>
        <span>
          <strong>HTTPS certificate trust (one-time):</strong>
          If your browser warned you about this server&rsquo;s certificate, paste the command below so the CLI tool trusts it too.
        </span>
        <div class="command-card mt-2">
          <div class="command-card-head">
            <span class="command-label">Paste in your terminal</span>
            <button class="copy-pill" data-testid="oauth-cert-copy-btn" @click="copyText(certCommand)">
              <v-icon size="11">mdi-content-copy</v-icon>COPY
            </button>
          </div>
          <pre class="command-code config-code">{{ certCommand }}</pre>
        </div>
      </div>
    </div>

    <div :class="['status-hero', connected ? 'status-hero--connected' : 'status-hero--waiting']" data-testid="status-hero">
      <template v-if="!connected">
        <span class="hero-dot hero-dot--waiting" data-testid="hero-dot" />
        <div class="hero-body">
          <span class="hero-title">Waiting for {{ toolLabel }} to connect&hellip;</span>
          <span class="hero-sub">The moment your tool connects, this flips green. Nothing to click.</span>
        </div>
      </template>
      <template v-else>
        <span class="hero-check" data-testid="hero-check"><v-icon size="16" :color="COLOR_SUCCESS">mdi-check-bold</v-icon></span>
        <div class="hero-body">
          <span class="hero-title hero-title--connected">{{ toolLabel }} connected.</span>
          <span class="hero-sub">{{ connectedNext }}</span>
        </div>
        <button v-if="advanceLabel" class="hero-advance" data-testid="hero-advance" @click="$emit('advance')">
          {{ advanceLabel }}
        </button>
      </template>
    </div>

    <div class="fallback-row">
      <span
        v-if="showFallback"
        class="fallback-link"
        role="button"
        tabindex="0"
        data-testid="fallback-toggle"
        :aria-pressed="keyMode"
        @click="$emit('toggle-key-mode')"
        @keydown.enter.prevent="$emit('toggle-key-mode')"
      >
        {{ keyMode ? 'Use browser sign-in instead' : 'Use an API key instead' }}
      </span>
      <span
        v-if="showAlreadyConfigured"
        class="already-link"
        role="button"
        tabindex="0"
        data-testid="already-configured"
        @click="$emit('mark-configured')"
        @keydown.enter.prevent="$emit('mark-configured')"
      >
        I already configured this
      </span>
    </div>

    <CertTrustModal
      v-model="showCertTrust"
      @continue="recordCertTrustDismissal"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { TEXT_MUTED_BLUE as COLOR_MUTED, COLOR_SUCCESS_SETUP as COLOR_SUCCESS } from '@/config/colorTokens'
import api from '@/services/api'
import configService from '@/services/configService'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'
import {
  normalizeToolId,
  detectPlatform,
  buildServerUrl,
  isBackendHttps,
  generateConfigForTool,
  generateCodexEnvVar,
  getCertTrustCommand,
  makeKeyName,
  getAuthCapabilities,
} from '@/composables/useMcpConfig'
import { toolName } from '@/config/setupTools'
import SetupStep2KeyFlow from './SetupStep2KeyFlow.vue'
import CertTrustModal from './CertTrustModal.vue'
import { recordCertTrustDismissal } from '@/utils/certTrustPreference'

const props = defineProps({
  toolId: { type: String, required: true },
  connected: { type: Boolean, default: false },
  keyMode: { type: Boolean, default: false },
  connectedNext: { type: String, default: '' },
  advanceLabel: { type: String, default: '' },
  showAlreadyConfigured: { type: Boolean, default: true },
})

defineEmits(['advance', 'toggle-key-mode', 'mark-configured'])

const { copy: clipboardCopy } = useClipboard()
const { showToast } = useToast()

const toolLabel = computed(() => toolName(props.toolId))
const normalizedId = computed(() => normalizeToolId(props.toolId))
const caps = computed(() => getAuthCapabilities(props.toolId))
const supportsOauth = computed(() => caps.value?.supports_oauth === true)

const isCe = ref(false)
const backendConfig = ref(null)
const serverHostname = ref(window.location.hostname)
const serverPort = ref(window.location.port || '7272')
const editingServer = ref(false)

const serverUrl = computed(() => {
  if (backendConfig.value && !editingServer.value) {
    return buildServerUrl(backendConfig.value)
  }
  const browserProtocol = window.location.protocol === 'https:' ? 'https' : 'http'
  const protocol = backendConfig.value?.protocol || browserProtocol
  const trimmedPort = String(serverPort.value || '').trim()
  return buildServerUrl({
    host: serverHostname.value,
    port: trimmedPort === '' ? null : trimmedPort,
    protocol,
  })
})

const baseMethod = computed(() => {
  if (props.toolId === 'generic') return 'manual'
  if (isCe.value) return 'key'
  return supportsOauth.value ? 'oauth' : 'key'
})
const method = computed(() =>
  baseMethod.value === 'oauth' && props.keyMode ? 'key' : baseMethod.value,
)
const showFallback = computed(() => baseMethod.value === 'oauth')
const showKeyStep = computed(() => method.value === 'key' || method.value === 'manual')

const platform = ref(detectPlatform())
const checkingKey = ref(false)
const existingKeyPrefix = ref(null)
const generatedKey = ref(null)
const generatingKey = ref(false)
const keyError = ref('')
const hasKey = computed(() => !!generatedKey.value)
const currentApiKey = computed(() => generatedKey.value || '')

const configCommand = computed(() =>
  generateConfigForTool(props.toolId, serverUrl.value, currentApiKey.value),
)
const oauthCommand = computed(() =>
  generateConfigForTool(props.toolId, serverUrl.value, '', { authMethod: 'oauth' }),
)
const mcpEndpoint = computed(() => `${serverUrl.value}/mcp`)
const envVarText = computed(() => generateCodexEnvVar(currentApiKey.value, platform.value))
const certCommand = computed(() => getCertTrustCommand(platform.value))
const needsCertTrust = computed(() => isBackendHttps(backendConfig.value))

const showCertTrust = ref(false)
const showCertTrustLink = computed(() => isCe.value && serverUrl.value.startsWith('https:'))

async function copyText(text) {
  const success = await clipboardCopy(text)
  showToast(
    success
      ? { message: 'Copied to clipboard', type: 'success' }
      : { message: 'Copy failed. Select the text and press Ctrl+C', type: 'warning' },
  )
}

async function checkExistingKey() {
  if (existingKeyPrefix.value || generatedKey.value) return
  checkingKey.value = true
  try {
    const resp = await api.apiKeys.getActive()
    const keys = resp.data
    if (keys && keys.length > 0) {
      existingKeyPrefix.value = keys[0].key_prefix
    }
  } catch (e) {
    console.warn('[ConnectToolCard] Failed to check active keys:', e)
  } finally {
    checkingKey.value = false
  }
}

async function handleGenerateKey() {
  generatingKey.value = true
  keyError.value = ''
  try {
    const keyName = makeKeyName(props.toolId)
    const resp = await api.apiKeys.create(keyName)
    generatedKey.value = resp.data.api_key
    existingKeyPrefix.value = null
    try {
      window.dispatchEvent(new CustomEvent('api-key-created', { detail: { name: keyName } }))
    } catch { /* no-op */ }
  } catch (e) {
    keyError.value = e?.response?.data?.message || e?.message || 'Failed to generate API key'
  } finally {
    generatingKey.value = false
  }
}

async function loadBackendConfig() {
  try {
    const cfg = await configService.fetchConfig()
    if (!cfg?.api) return
    backendConfig.value = cfg.api
    // eslint-disable-next-line giljo-internal/no-scattered-mode-checks
    isCe.value = cfg.giljo_mode === 'ce'
    if (cfg.api.host) serverHostname.value = cfg.api.host
    serverPort.value = cfg.api.port != null ? String(cfg.api.port) : ''
  } catch (e) {
    console.warn('[ConnectToolCard] Failed to fetch backend config:', e)
  }
}

watch(() => props.toolId, () => {
  generatedKey.value = null
  existingKeyPrefix.value = null
  keyError.value = ''
  checkExistingKey()
})

onMounted(() => {
  checkExistingKey()
  loadBackendConfig()
})
</script>

<style scoped lang="scss">
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;

.connect-tool-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* Server mono line */
.server-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.server-line-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  letter-spacing: 0.1em;
  color: var(--text-muted);
}

.server-line-url {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  color: $lightest-blue;
  background: rgba(255, 255, 255, 0.04);
  padding: 5px 11px;
  border-radius: $border-radius-sharp;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
}

.server-line-icon {
  color: var(--text-muted);
}

.server-line--editable .server-line-icon,
.server-line-icon[data-testid='server-url-pencil'] {
  cursor: pointer;
}

.server-line-hint {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.56rem;
  color: var(--text-muted);
}

.server-edit-fields {
  display: flex;
  align-items: center;
  gap: 8px;
}

.server-field {
  max-width: 220px;
}

.server-field--port {
  max-width: 96px;
}

.connect-subline {
  font-size: 0.84rem;
  color: var(--text-secondary);
  margin: 0;
}

/* Command card (numbered) */
.command-card {
  background: $elevation-elevated;
  border-radius: $border-radius-md;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.10);
}

.command-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.command-step {
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 700;
  font-size: 0.94rem;
  color: $color-brand-yellow;
}

.command-label {
  flex: 1;
  font-size: 0.84rem;
  color: $color-text-primary;
}

.copy-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem;
  color: $lightest-blue;
  background: transparent;
  border: none;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
  padding: 4px 10px;
  border-radius: $border-radius-pill;
  cursor: pointer;
}

.command-code {
  background: $color-background-primary;
  border-radius: $border-radius-default;
  padding: 11px 14px;
  margin: 0;
  font-family: 'Roboto Mono', 'Courier New', monospace;
  font-size: 0.75rem;
  line-height: 1.5;
  color: $lightest-blue;
  white-space: pre-wrap;
  word-break: break-all;
}

.cert-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 0.76rem;
  color: var(--text-secondary);
  margin-top: 10px;
}

/* Status hero */
.status-hero {
  display: flex;
  align-items: center;
  gap: 14px;
  border-radius: $border-radius-md;
  padding: 18px;
  background: $elevation-elevated;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.10);
  transition: box-shadow 0.3s, background 0.3s;
}

.status-hero--connected {
  background: rgba($color-status-success, 0.07);
  box-shadow: inset 0 0 0 1px rgba($color-status-success, 0.4);
}

.hero-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* FE-9569: unified onto the authoritative Waiting token (design-system-
   sample-v2.html "Status & Brand Colors" -- Waiting #ffd700, its own
   distinct status, not the disconnected/error red this used to borrow). */
.hero-dot--waiting {
  background: $color-status-waiting;
  animation: hero-wait 1.6s ease infinite;
}

@keyframes hero-wait {
  0%, 100% { opacity: 0.35; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.1); }
}

.hero-check {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  background: rgba($color-status-success, 0.18);
  animation: hero-pop 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
}

@keyframes hero-pop {
  0% { transform: scale(0.6); opacity: 0; }
  60% { transform: scale(1.15); }
  100% { transform: scale(1); opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .hero-dot--waiting,
  .hero-check {
    animation: none;
  }
}

.hero-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.hero-title {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  font-size: 0.94rem;
  color: $color-text-primary;
}

.hero-title--connected {
  color: $color-status-success;
}

.hero-sub {
  font-size: 0.76rem;
  color: var(--text-muted);
}

.hero-advance {
  background: $color-brand-yellow;
  color: $color-on-yellow-ink;
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  font-size: 0.82rem;
  padding: 10px 20px;
  border: none;
  border-radius: $border-radius-default;
  cursor: pointer;
  flex-shrink: 0;
}

/* Fallback links */
.fallback-row {
  display: flex;
  align-items: center;
  gap: 16px;
}

.fallback-link {
  font-size: 0.76rem;
  color: var(--text-muted);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.fallback-link:hover,
.fallback-link:focus-visible {
  color: $color-brand-yellow;
}

.already-link {
  font-size: 0.76rem;
  color: var(--text-muted);
  cursor: pointer;
}

.already-link:hover,
.already-link:focus-visible {
  color: $color-text-hover;
}
</style>
