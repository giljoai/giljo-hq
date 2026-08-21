<template>
  <!-- API key flow — Card 1 (Generate) + Card 2 (Command). Shown for key + manual
       methods, or when a sign-in tool's fallback is toggled on. -->
  <div class="key-flow" data-testid="key-flow-section">
    <!-- Card 1 — Generate key -->
    <div class="numbered-card">
      <span class="numbered-card-step">1.</span>
      <div class="numbered-card-body">
        <!-- Checking for existing key -->
        <div v-if="checkingKey" class="api-key-status" data-testid="key-status-checking">
          <v-progress-circular size="16" width="2" indeterminate :color="colorMuted" />
          <span class="status-text">Checking for existing key...</span>
        </div>

        <!-- Generating key -->
        <div v-else-if="generatingKey" class="api-key-status" data-testid="key-status-generating">
          <v-progress-circular size="16" width="2" indeterminate :color="colorMuted" />
          <span class="status-text">Generating API key...</span>
        </div>

        <!-- Fresh key generated (embedded in the command below — never shown raw) -->
        <div v-else-if="generatedKey" class="api-key-status" data-testid="key-status-generated">
          <v-icon size="16" :color="colorSuccess">mdi-check-circle</v-icon>
          <span class="status-text status-text--key">Key generated</span>
          <span class="key-inline-note">already inside the command below</span>
        </div>

        <!-- Existing key found (prefix only, no plaintext) -->
        <div v-else-if="existingKeyPrefix" class="api-key-existing" data-testid="key-status-existing">
          <div class="api-key-status">
            <v-icon size="16" :color="colorSuccess">mdi-check-circle</v-icon>
            <span class="status-text">Key exists ({{ existingKeyPrefix }}...)</span>
          </div>
          <v-btn
            size="small"
            color="primary"
            variant="flat"
            prepend-icon="mdi-key-plus"
            data-testid="generate-new-key-btn"
            :loading="generatingKey"
            @click="$emit('generate-key')"
          >
            Generate New Config
          </v-btn>
        </div>

        <!-- No key at all -->
        <div v-else class="api-key-status api-key-status--empty" data-testid="key-status-empty">
          <span class="status-text">Create the API key this tool will use</span>
          <v-btn
            size="small"
            color="primary"
            variant="flat"
            prepend-icon="mdi-key-plus"
            data-testid="generate-key-btn"
            :loading="generatingKey"
            @click="$emit('generate-key')"
          >
            Generate API Key
          </v-btn>
        </div>

        <v-alert v-if="keyError" type="error" variant="tonal" density="compact" class="mt-2" data-testid="key-error-alert" closable @click:close="$emit('clear-key-error')">
          {{ keyError }}
        </v-alert>
      </div>
    </div>

    <!-- Card 2 — Configuration command (only when key is available) -->
    <div v-if="hasKey" class="key-flow-config">

      <!-- HTTPS cert trust (Node.js tools) -->
      <template v-if="needsCertTrust">
        <div class="platform-pill-row">
          <button :class="['platform-pill', 'smooth-border', { 'platform-pill--active': platform === 'windows' }]" data-testid="platform-windows-btn" @click="$emit('set-platform', 'windows')">PowerShell</button>
          <button :class="['platform-pill', 'smooth-border', { 'platform-pill--active': platform === 'unix' }]" data-testid="platform-unix-btn" @click="$emit('set-platform', 'unix')">Linux / macOS</button>
          <v-tooltip location="top" max-width="300">
            <template #activator="{ props: tipProps }">
              <v-btn v-bind="tipProps" icon variant="text" size="x-small" class="platform-help-icon">
                <v-icon size="16">mdi-help-circle-outline</v-icon>
              </v-btn>
            </template>
            HTTPS with a private or self-signed certificate: Node.js-based AI coding agents need to trust the certificate this server uses (one-time setup, requires Node.js 22+).
          </v-tooltip>
        </div>
        <div class="config-block smooth-border" data-testid="cert-trust-block">
          <div class="config-block-header">
            <span class="config-block-label">CERTIFICATE TRUST (ONE-TIME) Paste in terminal</span>
            <v-btn
              icon="mdi-content-copy"
              size="x-small"
              variant="text"
              aria-label="Copy certificate command"
              data-testid="cert-copy-btn"
              @click="$emit('copy-text', { text: certCommand, field: 'cert' })"
            />
          </div>
          <pre class="config-code">{{ certCommand }}</pre>
        </div>
      </template>

      <!-- Platform toggle for Codex env var (if not already shown for HTTPS) -->
      <div v-if="!needsCertTrust && activeNormalizedId === 'codex'" class="platform-pill-row">
        <button :class="['platform-pill', 'smooth-border', { 'platform-pill--active': platform === 'windows' }]" @click="$emit('set-platform', 'windows')">PowerShell</button>
        <button :class="['platform-pill', 'smooth-border', { 'platform-pill--active': platform === 'unix' }]" @click="$emit('set-platform', 'unix')">Linux / macOS</button>
      </div>

      <!-- Codex: Environment Variable -->
      <div v-if="activeNormalizedId === 'codex'" class="config-block smooth-border" data-testid="codex-env-block">
        <div class="config-block-header">
          <span class="config-block-label">Environment Variable</span>
          <v-btn
            icon="mdi-content-copy"
            size="x-small"
            variant="text"
            aria-label="Copy environment variable"
            @click="$emit('copy-text', { text: envVarText, field: 'env' })"
          />
        </div>
        <pre class="config-code">{{ envVarText }}</pre>
      </div>

      <!-- Main config command (bearer for CLI tools, JSON server config for generic) -->
      <div class="config-block smooth-border" data-testid="config-command-block">
        <div class="config-block-header">
          <!-- FE-9383: name the client on the snippet itself — each CLI has its own
               flag syntax, so an unlabeled command invites pasting it into the wrong tool. -->
          <span class="config-block-label" data-testid="config-block-label">{{ isGeneric ? `${toolLabel} server config (key included)` : `Paste in your ${toolLabel} terminal (key included)` }}</span>
          <v-btn
            icon="mdi-content-copy"
            size="x-small"
            variant="text"
            aria-label="Copy configuration command"
            data-testid="config-copy-btn"
            @click="$emit('copy-text', { text: configCommand, field: 'config' })"
          />
        </div>
        <pre class="config-code">{{ configCommand }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  checkingKey:       { type: Boolean, required: true },
  generatingKey:     { type: Boolean, required: true },
  generatedKey:      { type: String,  default: null },
  existingKeyPrefix: { type: String,  default: null },
  keyError:          { type: String,  default: '' },
  hasKey:            { type: Boolean, required: true },
  needsCertTrust:    { type: Boolean, required: true },
  activeNormalizedId: { type: String, required: true },
  // Display name of the client this snippet targets (FE-9383). Defaulted so an
  // existing mount that has not been updated degrades to the previous wording
  // rather than rendering "undefined".
  toolLabel:         { type: String,  default: 'your tool' },
  platform:          { type: String,  required: true },
  certCommand:       { type: String,  default: '' },
  envVarText:        { type: String,  default: '' },
  configCommand:     { type: String,  required: true },
  isGeneric:         { type: Boolean, default: false },
  colorMuted:        { type: String,  required: true },
  colorSuccess:      { type: String,  required: true },
})

defineEmits(['generate-key', 'clear-key-error', 'set-platform', 'copy-text'])
</script>

<style scoped lang="scss">
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;

/* Numbered cards (Card 1 Generate / Card 2 Command) — the restyled key flow. */
.key-flow {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.numbered-card {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  background: $elevation-elevated;
  border-radius: $border-radius-md;
  padding: 16px 18px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.10);
}

.numbered-card-step {
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 700;
  font-size: 0.94rem;
  color: $color-brand-yellow;
  line-height: 1.5;
}

.numbered-card-body {
  flex: 1;
  min-width: 0;
}

.key-flow-config {
  display: flex;
  flex-direction: column;
}

/* API Key */
.api-key-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.api-key-status--empty {
  justify-content: space-between;
}

.api-key-existing {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.status-text {
  font-size: 0.875rem;
  color: $color-text-primary;
}

.status-text--key {
  color: $color-status-success;
  font-weight: 600;
}

.key-inline-note {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  color: var(--text-muted);
}

/* Platform pill toggles (matches UserSettings pill-toggle pattern) */
.platform-pill-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.platform-pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 14px;
  font-size: 0.75rem;
  font-weight: 500;
  border: none;
  border-radius: 16px;
  background: transparent;
  color: $lightest-blue;
  cursor: pointer;
  transition: color 200ms ease-out, background 200ms ease-out;
  --smooth-border-color: #{$med-blue};
}

.platform-pill:hover {
  color: $color-text-primary;
}

.platform-pill--active,
.platform-pill--active:hover {
  background: rgba($color-brand-yellow, 0.12);
  color: $color-brand-yellow;
  box-shadow: none;
}

.platform-help-icon {
  color: $lightest-blue;
  cursor: help;
}

/* Config blocks */
.config-block {
  position: relative;
  background: $color-background-primary;
  border-radius: $border-radius-default;
  padding: 0;
  margin-bottom: 12px;
  overflow: hidden;
}

.config-block-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: rgba($med-blue, 0.3);
}

.config-block-label {
  font-size: 0.6875rem;
  font-weight: 600;
  color: $lightest-blue;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.config-code {
  padding: 12px;
  margin: 0;
  font-family: "Roboto Mono", "Courier New", monospace;
  font-size: 0.8125rem;
  line-height: 1.5;
  color: $color-text-primary;
  white-space: pre-wrap;
  word-break: break-all;
}

</style>
