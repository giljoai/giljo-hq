<template>
  <v-container fluid class="fill-height oauth-container">
    <v-row class="align-center justify-center">
      <v-col cols="12" sm="8" md="5" lg="4">
        <v-card elevation="8" class="oauth-card smooth-border">
          <!-- Header -->
          <v-card-title class="text-center pa-6">
            <div class="d-flex flex-column align-center w-100">
              <v-img
                src="/Giljo_YW.svg"
                :alt="PRODUCT_NAME"
                height="50"
                width="auto"
                max-width="200"
                class="mb-3"
              />
              <h1 class="text-headline-small font-weight-bold">
                {{ isAuthenticated ? 'Authorize Application' : 'Sign In to Continue' }}
              </h1>
              <p class="text-body-medium text-muted-a11y mt-2">
                {{ isAuthenticated
                  ? 'An application is requesting access to your account'
                  : 'Authentication is required to authorize this application'
                }}
              </p>
            </div>
          </v-card-title>

          <v-divider />

          <!-- Error alert -->
          <v-card-text v-if="error" class="pb-0 pt-4 px-6">
            <AppAlert
              type="error"
              variant="tonal"
              closable
              @click:close="error = ''"
            >
              {{ error }}
            </AppAlert>
          </v-card-text>

          <!-- Missing OAuth parameters warning -->
          <v-card-text v-if="missingParams" class="pa-6">
            <AppAlert type="warning" variant="tonal">
              Invalid authorization request. Required OAuth parameters are missing.
            </AppAlert>
            <div class="text-center mt-4">
              <v-btn
                color="primary"
                variant="outlined"
                :to="{ name: 'Home' }"
                aria-label="Return to home page"
              >
                <v-icon start>mdi-home</v-icon>
                Go to Home
              </v-btn>
            </div>
          </v-card-text>

          <!-- Login Form (shown when not authenticated) -->
          <v-card-text v-else-if="!isAuthenticated" class="pa-6">
            <v-form ref="loginForm" @submit.prevent="handleLogin">
              <v-text-field
                v-model="username"
                label="Email or username"
                prepend-inner-icon="mdi-account"
                variant="outlined"
                :rules="[rules.username]"
                :disabled="loading"
                autofocus
                autocomplete="username"
                aria-label="Email or username"
                @keyup.enter="handleLogin"
                @input="error = ''"
              />

              <v-text-field
                v-model="password"
                label="Password"
                prepend-inner-icon="mdi-lock"
                :type="showPassword ? 'text' : 'password'"
                variant="outlined"
                :rules="[rules.password]"
                :disabled="loading"
                autocomplete="current-password"
                class="mt-4"
                aria-label="Password"
                @keyup.enter="handleLogin"
                @input="error = ''"
              >
                <template #append-inner>
                  <v-icon
                    tabindex="-1"
                    @click="showPassword = !showPassword"
                  >
                    {{ showPassword ? 'mdi-eye' : 'mdi-eye-off' }}
                  </v-icon>
                </template>
              </v-text-field>

              <v-btn
                type="submit"
                color="primary"
                size="large"
                block
                :loading="loading"
                :disabled="!username || !password || loading"
                class="mt-4"
                aria-label="Sign in to authorize application"
              >
                <v-icon v-if="!loading" start>mdi-login</v-icon>
                {{ loading ? 'Signing in...' : 'Sign In' }}
              </v-btn>
            </v-form>
          </v-card-text>

          <!-- Consent Form (shown when authenticated) -->
          <!--
            Extension seam (API-0021c): when an override component is provided
            (via the `overrideConsentComponent` prop OR the runtime SaaS glob
            below), it replaces this whole consent body. The override receives
            `client`, `scopes`, and `authorizing` props and emits `allow` /
            `deny` — same contract as DemoConsentScreen.vue. CE never imports
            the SaaS file; the glob resolves to {} when frontend/src/saas/ is
            absent (post-export). Pattern matches Login.vue's
            ForgotPasswordEmail injection.
          -->
          <v-card-text v-else class="pa-6">
            <component
              :is="resolvedOverrideComponent"
              v-if="resolvedOverrideComponent"
              data-testid="consent-override"
              :client="seamClient"
              :scopes="scopeDescriptions"
              :authorizing="authorizing"
              @allow="handleAuthorize"
              @deny="handleDeny"
            />
            <template v-else>
              <!-- Client info -->
              <div class="d-flex align-center mb-4">
                <v-avatar color="primary" size="48" class="mr-4">
                  <v-icon size="24" color="white">mdi-application</v-icon>
                </v-avatar>
                <div>
                  <p class="text-body-large font-weight-medium">{{ clientDisplayName }}</p>
                  <p class="text-body-small text-muted-a11y">wants to access your account</p>
                </div>
              </div>

              <v-divider class="mb-4" />

              <!-- Requested permissions -->
              <p class="text-title-small font-weight-medium mb-2">Requested permissions</p>
              <v-list density="compact" class="mb-4 bg-transparent">
                <v-list-item
                  v-for="permission in scopeDescriptions"
                  :key="permission.scope"
                  class="px-0"
                >
                  <template #prepend>
                    <v-icon color="primary" size="20" class="mr-3">{{ permission.icon }}</v-icon>
                  </template>
                  <v-list-item-title class="text-body-medium">
                    {{ permission.label }}
                  </v-list-item-title>
                  <v-list-item-subtitle class="text-body-small">
                    {{ permission.description }}
                  </v-list-item-subtitle>
                </v-list-item>
              </v-list>

              <v-divider class="mb-4" />

              <!-- User identity -->
              <div class="d-flex align-center mb-4">
                <v-icon size="18" class="mr-2 text-muted-a11y">mdi-account-circle</v-icon>
                <span class="text-body-medium text-muted-a11y">
                  Signed in as <strong>{{ currentUser?.username }}</strong>
                </span>
              </div>

              <!-- Action buttons -->
              <div class="d-flex ga-3">
                <v-btn
                  variant="outlined"
                  size="large"
                  class="flex-grow-1"
                  :disabled="authorizing"
                  aria-label="Deny authorization and return to the application"
                  @click="handleDeny"
                >
                  Deny
                </v-btn>
                <v-btn
                  color="primary"
                  size="large"
                  class="flex-grow-1"
                  :loading="authorizing"
                  :disabled="authorizing"
                  aria-label="Authorize this application to access your account"
                  @click="handleAuthorize"
                >
                  <v-icon v-if="!authorizing" start>mdi-check</v-icon>
                  {{ authorizing ? 'Authorizing...' : 'Authorize' }}
                </v-btn>
              </div>
            </template>
          </v-card-text>

          <v-divider />

          <!-- Footer -->
          <v-card-text class="text-center pa-4">
            <p class="text-body-small text-muted-a11y">
              <v-icon size="small" class="mr-1">mdi-shield-lock</v-icon>
              You will be redirected back to the application after authorization
            </p>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { ref, shallowRef, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import AppAlert from '@/components/ui/AppAlert.vue'
import { apiClient } from '@/services/api'
import configService from '@/services/configService'
import { useGiljoMode } from '@/composables/useGiljoMode'
import { PRODUCT_NAME } from '@/branding'

// API-0021c — Extension seam contract:
//
// Optional `overrideConsentComponent` prop allows a parent (or test) to inject
// a consent body component directly. In production, the SaaS glob below loads
// `@/saas/components/DemoConsentScreen.vue` lazily when GILJO_MODE != 'ce'.
//
// The override receives:
//   - client: { id: string, name: string }   — display data only
//   - scopes: Array<{ scope, label, description, icon }>  — already mapped
//   - authorizing: boolean                                — async lock state
//
// And emits:
//   - 'allow'  → triggers handleAuthorize()
//   - 'deny'   → triggers handleDeny()
//
// CE never imports from frontend/src/saas/. The import.meta.glob pattern is
// CE-export safe: when the saas/ directory is stripped, the glob returns {}
// and the loader silently no-ops. Same pattern as Login.vue's
// ForgotPasswordEmail and DefaultLayout's TrialBanner.
const props = defineProps({
  overrideConsentComponent: {
    type: [Object, Function],
    default: null,
  },
})

const route = useRoute()
const userStore = useUserStore()
const { isNonCeMode } = useGiljoMode()

// Login state
const username = ref('')
const password = ref('')
const showPassword = ref(false)
const loading = ref(false)
const loginForm = ref(null)

// Consent state
const authorizing = ref(false)
const error = ref('')

// Validation rules
const rules = {
  username: (value) => !!value || 'Email or username is required',
  password: (value) => !!value || 'Password is required',
}

// OAuth parameters from URL query.
// `resource` (RFC 8707) is forwarded from claude.com / claude.ai connector
// popups so the backend can persist it onto the auth-code record. Phase 2
// of API-0021d enforces this on the backend; without forwarding here, the
// downstream /token exchange fails 401 invalid_grant.
const oauthParams = computed(() => ({
  client_id: route.query.client_id || '',
  redirect_uri: route.query.redirect_uri || '',
  response_type: route.query.response_type || '',
  code_challenge: route.query.code_challenge || '',
  code_challenge_method: route.query.code_challenge_method || '',
  scope: route.query.scope || '',
  state: route.query.state || '',
  // SEC-9451: absent must stay absent. `|| ''` turned a missing param into an
  // empty string, and the backend accepts `None` but rejects `""` — so a
  // client that sends no `resource` (claude.ai sends none) was 400'd on its
  // own consent POST. `undefined` is dropped by JSON.stringify, so the key
  // never reaches the request body. The forwarding above is unaffected.
  resource: route.query.resource || undefined,
}))

// Check if required OAuth parameters are present
const missingParams = computed(() => {
  const params = oauthParams.value
  return !params.client_id || !params.redirect_uri || !params.response_type
})

// Auth state
const isAuthenticated = computed(() => userStore.isAuthenticated)
const currentUser = computed(() => userStore.currentUser)

// Map client_id to a human-readable display name
const clientDisplayName = computed(() => {
  const clientId = oauthParams.value.client_id
  const knownClients = {
    'giljo-mcp-default': `${PRODUCT_NAME} Client`,
    'claude-desktop': 'Claude Desktop',
  }
  return knownClients[clientId] || clientId
})

// Seam payload for the override component. Single object so future fields
// (e.g. logo URL once DCR lands per API-0021c backend) can be added without
// changing the prop signature.
const seamClient = computed(() => ({
  id: oauthParams.value.client_id,
  name: clientDisplayName.value,
}))

// Holds a SaaS-injected override loaded via import.meta.glob (see onMounted).
// shallowRef avoids Vue making the component definition deeply reactive.
const saasOverrideComponent = shallowRef(null)

// Combined resolution: explicit prop wins over the runtime SaaS glob. The
// prop is what tests use; the glob is what production demo/saas builds use.
const resolvedOverrideComponent = computed(
  () => props.overrideConsentComponent || saasOverrideComponent.value,
)

// Map scope strings to descriptive permission entries.
// Grantable scopes per API-0021b: `mcp:read`, `mcp:write`. Legacy `mcp` /
// `read` / `write` strings are kept as fallbacks for older clients during
// the rollout, but new flows will surface the namespaced form.
const scopeDescriptions = computed(() => {
  const scopeStr = oauthParams.value.scope || 'mcp:read mcp:write'
  const scopes = scopeStr.split(' ').filter(Boolean)
  const descriptions = {
    'mcp:read': {
      scope: 'mcp:read',
      label: 'MCP Read Access',
      description: 'Read your projects, tasks, and agent state via the MCP protocol',
      icon: 'mdi-eye',
    },
    'mcp:write': {
      scope: 'mcp:write',
      label: 'MCP Write Access',
      description: 'Create and modify projects, tasks, and agent state via the MCP protocol',
      icon: 'mdi-pencil',
    },
    mcp: {
      scope: 'mcp',
      label: 'MCP Tool Access',
      description: 'Execute tools and access resources via the MCP protocol',
      icon: 'mdi-connection',
    },
    read: {
      scope: 'read',
      label: 'Read Access',
      description: 'Read data from your account',
      icon: 'mdi-eye',
    },
    write: {
      scope: 'write',
      label: 'Write Access',
      description: 'Modify data in your account',
      icon: 'mdi-pencil',
    },
  }
  return scopes.map(
    (s) => descriptions[s] || { scope: s, label: s, description: `Access: ${s}`, icon: 'mdi-key' },
  )
})

// Handle login submission
async function handleLogin() {
  const { valid } = await loginForm.value.validate()
  if (!valid) return

  loading.value = true
  error.value = ''

  try {
    const loginSuccess = await userStore.login(username.value, password.value)
    if (!loginSuccess) {
      error.value = 'Invalid credentials.'
    }
  } catch (err) {
    if (err.response?.status === 401) {
      error.value = 'Invalid credentials.'
    } else if (err.response?.status === 429) {
      error.value = 'Too many login attempts. Please try again later.'
    } else if (err.code === 'ERR_NETWORK' || !err.response) {
      error.value = 'Network error. Please check your connection and try again.'
    } else {
      error.value = err.response?.data?.detail || 'Login failed. Please try again.'
    }
    password.value = ''
  } finally {
    loading.value = false
  }
}

// Handle authorize (consent granted)
async function handleAuthorize() {
  authorizing.value = true
  error.value = ''

  try {
    const response = await apiClient.post('/api/oauth/authorize', {
      client_id: oauthParams.value.client_id,
      redirect_uri: oauthParams.value.redirect_uri,
      response_type: oauthParams.value.response_type,
      code_challenge: oauthParams.value.code_challenge,
      code_challenge_method: oauthParams.value.code_challenge_method,
      scope: oauthParams.value.scope,
      state: oauthParams.value.state,
      // RFC 8707 — forward through to the backend so it can persist the
      // resource indicator onto the auth-code record. Phase 2 of API-0021d
      // enforces validation; dropping this here breaks claude.com / claude.ai
      // connector flows with 401 invalid_grant on /token exchange.
      resource: oauthParams.value.resource,
    })

    // Backend returns a redirect URL with the authorization code
    const redirectUrl = response.data?.redirect_uri || response.data?.redirect_url
    if (redirectUrl) {
      window.location.href = redirectUrl
    } else {
      error.value = 'Authorization succeeded but no redirect URL was returned.'
      authorizing.value = false
    }
  } catch (err) {
    authorizing.value = false
    if (err.response?.data?.detail) {
      error.value = err.response.data.detail
    } else if (err.code === 'ERR_NETWORK' || !err.response) {
      error.value = 'Network error. Please check your connection and try again.'
    } else {
      error.value = 'Authorization failed. Please try again.'
    }
  }
}

// Handle deny (consent refused)
function handleDeny() {
  const params = oauthParams.value
  const redirectUri = new URL(params.redirect_uri)
  redirectUri.searchParams.set('error', 'access_denied')
  redirectUri.searchParams.set('error_description', 'The user denied the authorization request')
  if (params.state) {
    redirectUri.searchParams.set('state', params.state)
  }
  window.location.href = redirectUri.toString()
}

// Check auth state on mount
onMounted(async () => {
  if (!userStore.currentUser) {
    try {
      await userStore.fetchCurrentUser()
    } catch {
      // Not authenticated -- will show login form
    }
  }

  // Dynamically load the SaaS consent override when not in CE mode.
  // Uses import.meta.glob (Vite-aware) so the file bundles into a chunk for
  // SaaS/private builds and is silently absent in CE builds where the saas/
  // directory has been stripped by the export pipeline. CE-export safety:
  // glob returns {} → loader is undefined → seam stays inert.
  try {
    await configService.fetchConfig()
  } catch {
    // Default to CE on config failure.
  }
  if (isNonCeMode()) {
    const overrideLoaders = import.meta.glob('@/saas/components/DemoConsentScreen.vue')
    const [loader] = Object.values(overrideLoaders)
    if (loader) {
      try {
        const mod = await loader()
        saasOverrideComponent.value = mod.default
      } catch (error) {
        console.warn('[OAuthAuthorize] DemoConsentScreen failed to load:', error)
      }
    }
  }
})
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
.oauth-container {
  background: linear-gradient(135deg, rgb(30, 49, 71) 0%, rgb(18, 29, 42) 100%);
  min-height: 100vh;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 9999;
  overflow-y: auto;
}

.oauth-card {
  border-radius: $border-radius-rounded;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

/* Dark theme adjustments */
:deep(.v-theme--dark) .oauth-container {
  background: linear-gradient(135deg, rgb(18, 29, 42) 0%, rgb(10, 15, 22) 100%);
}

/* Remove Vuetify field overlay tint so inputs match the card background */
:deep(.v-field__overlay) {
  opacity: 0 !important;
}
</style>
