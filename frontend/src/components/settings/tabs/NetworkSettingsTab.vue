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

        <p class="text-body-medium text-muted-a11y mb-0" data-test="https-guide-link">
          <v-icon size="small" class="mr-1">mdi-book-open-variant</v-icon>
          Want HTTPS? Put a reverse proxy such as Caddy in front. See the
          <router-link
            :to="{ name: 'UserGuide', hash: '#https-and-browser-configuration' }"
            class="guide-link"
          >user guide</router-link>.
        </p>

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
import { ref, watch } from 'vue'

const props = defineProps({
  serverHostDisplay: {
    type: String,
    default: '',
  },
  serverPort: {
    type: [Number, String],
    default: null,
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

function handleRefresh() {
  emit('refresh')
  emit('reload-domains')
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
</style>
