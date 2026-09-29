<template>
  <v-container fluid class="fill-height oauth-container">
    <v-row class="align-center justify-center">
      <v-col cols="12" sm="8" md="5" lg="4">
        <v-card elevation="8" class="oauth-card smooth-border">
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

              <div class="d-flex align-center mb-4">
                <v-icon size="18" class="mr-2 text-muted-a11y">mdi-account-circle</v-icon>
                <span class="text-body-medium text-muted-a11y">
                  Signed in as <strong>{{ currentUser?.username }}</strong>
                </span>
              </div>

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
import { parseErrorResponse } from '@/utils/errorMessages'
import configService from '@/services/configService'
import { useGiljoMode } from '@/composables/useGiljoMode'
import { PRODUCT_NAME } from '@/branding'

const props = defineProps({
  overrideConsentComponent: {
    type: [Object, Function],
    default: null,
  },
})

const route = useRoute()
const userStore = useUserStore()
const { isNonCeMode } = useGiljoMode()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const loading = ref(false)
const loginForm = ref(null)

const authorizing = ref(false)
const error = ref('')

const rules = {
  username: (value) => !!value || 'Email or username is required',
  password: (value) => !!value || 'Password is required',
}

const oauthParams = computed(() => ({
  client_id: route.query.client_id || '',
  redirect_uri: route.query.redirect_uri || '',
  response_type: route.query.response_type || '',
  code_challenge: route.query.code_challenge || '',
  code_challenge_method: route.query.code_challenge_method || '',
  scope: route.query.scope || '',
  state: route.query.state || '',
  resource: route.query.resource || undefined,
}))

const missingParams = computed(() => {
  const params = oauthParams.value
  return !params.client_id || !params.redirect_uri || !params.response_type
})

const isAuthenticated = computed(() => userStore.isAuthenticated)
const currentUser = computed(() => userStore.currentUser)

const clientDisplayName = computed(() => {
  const clientId = oauthParams.value.client_id
  const knownClients = {
    'giljo-mcp-default': `${PRODUCT_NAME} Client`,
    'claude-desktop': 'Claude Desktop',
  }
  return knownClients[clientId] || clientId
})

const seamClient = computed(() => ({
  id: oauthParams.value.client_id,
  name: clientDisplayName.value,
}))

const saasOverrideComponent = shallowRef(null)

const resolvedOverrideComponent = computed(
  () => props.overrideConsentComponent || saasOverrideComponent.value,
)

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

async function handleLogin() {
  const { valid } = await loginForm.value.validate()
  if (!valid) return

  loading.value = true
  error.value = ''

  try {
    await userStore.login(username.value, password.value)
  } catch (err) {
    if (err.response?.status === 401) {
      error.value = 'Invalid credentials.'
    } else if (err.response?.status === 429) {
      error.value = 'Too many sign-in attempts. Please wait a minute and try again.'
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
      resource: oauthParams.value.resource,
    })

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

function isHttpUrl(value) {
  try {
    return ['http:', 'https:'].includes(new URL(value).protocol)
  } catch {
    return false
  }
}

async function handleDeny() {
  error.value = ''

  try {
    const response = await apiClient.post('/api/oauth/authorize/deny', {
      client_id: oauthParams.value.client_id,
      redirect_uri: oauthParams.value.redirect_uri,
      response_type: oauthParams.value.response_type,
      code_challenge: oauthParams.value.code_challenge,
      code_challenge_method: oauthParams.value.code_challenge_method,
      scope: oauthParams.value.scope,
      state: oauthParams.value.state,
      resource: oauthParams.value.resource,
    })
    const redirectUrl = response.data?.redirect_uri
    if (isHttpUrl(redirectUrl)) {
      window.location.href = redirectUrl
      return
    }
    error.value = 'Access was denied, but the application could not be notified. You can close this window.'
  } catch (err) {
    if (err.code === 'ERR_NETWORK' || !err.response) {
      error.value = 'Network error. Please check your connection and try again.'
    } else {
      error.value = parseErrorResponse(err).message
    }
  }
}

onMounted(async () => {
  if (!userStore.currentUser) {
    try {
      await userStore.fetchCurrentUser()
    } catch {
      // Not authenticated -- will show login form
    }
  }

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
