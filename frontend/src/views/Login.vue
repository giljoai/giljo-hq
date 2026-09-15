<template>
  <v-container fluid class="fill-height login-container">
    <v-row class="align-center justify-center">
      <v-col cols="12" sm="8" md="5" lg="4">
        <v-card elevation="8" class="login-card smooth-border">
          <v-card-title class="text-center pa-6">
            <div class="d-flex flex-column align-center w-100">
              <v-img
                src="/Giljo_YW.svg"
                :alt="productName"
                height="50"
                width="auto"
                max-width="200"
                class="mb-3"
              />
              <h1 class="text-headline-small font-weight-bold">{{ productName }} Login</h1>
              <span class="edition-badge mt-2 text-body-small">
                {{ editionLabel }}
              </span>
            </div>
          </v-card-title>

          <v-divider />

          <v-card-text class="pa-6">
            <AppAlert
              v-if="hostnameMismatch"
              type="warning"
              variant="tonal"
              class="mb-4"
            >
              You're connected via <strong>{{ currentHostname }}</strong>, but the server is at
              <strong>{{ correctHost }}</strong>.
              API requests will be blocked by your browser.
              <br />
              <a :href="correctUrl" class="font-weight-bold text-warning">
                Open correct address &rarr;
              </a>
            </AppAlert>

            <AppAlert
              v-if="error"
              type="error"
              variant="tonal"
              class="mb-4"
              closable
              @click:close="error = ''"
            >
              {{ error }}
            </AppAlert>

            <AppAlert
              v-if="successMessage"
              type="success"
              variant="tonal"
              class="mb-4"
              closable
              @click:close="successMessage = ''"
            >
              {{ successMessage }}
            </AppAlert>

            <v-form ref="loginForm" @submit.prevent="handleLogin">
              <v-text-field
                v-model="username"
                label="Email or username"
                placeholder="Enter email or username"
                prepend-inner-icon="mdi-account"
                variant="outlined"
                :rules="[rules.username]"
                :disabled="loading"
                autofocus
                autocomplete="username"
                data-testid="email-input"
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
                data-testid="password-input"
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

              <div class="d-flex justify-center">
                <v-checkbox
                  v-model="rememberMe"
                  label="Remember me"
                  color="primary"
                  density="compact"
                  :disabled="loading"
                  class="mt-2"
                  hide-details
                />
              </div>

              <div class="d-flex justify-center mt-4">
                <v-btn
                  type="submit"
                  color="primary"
                  size="large"
                  :loading="loading"
                  :disabled="!username || !password || loading"
                  data-testid="login-button"
                >
                  <v-icon v-if="!loading" start>mdi-login</v-icon>
                  {{ loading ? 'Logging in...' : 'Sign In' }}
                </v-btn>
              </div>

              <component :is="socialLoginButtonsComponent" v-if="socialLoginButtonsComponent" />

              <div v-if="isNonCe" class="text-center mt-3">
                <span class="text-body-small text-muted-a11y">Don't have an account?</span>
                <router-link to="/register" class="text-body-small font-weight-bold ml-1">Register</router-link>
              </div>

              <div class="text-center mt-4">
                <v-btn
                  variant="text"
                  color="primary"
                  :disabled="loading"
                  aria-label="Open forgot password dialog"
                  @click="handleForgotPasswordClick"
                >
                  <v-icon start>mdi-lock-question</v-icon>
                  Forgot Password?
                </v-btn>
              </div>
            </v-form>
          </v-card-text>

          <ForgotPasswordPin
            v-model:show="showForgotPassword"
            @success="handlePasswordResetSuccess"
          />

          <component
            :is="forgotPasswordEmailComponent"
            v-if="forgotPasswordEmailComponent"
            v-model:show="showForgotPasswordEmail"
            @success="handlePasswordResetSuccess"
          />

          <v-divider />

          <v-card-text class="text-center pa-4">
            <a
              href="https://www.giljo.ai"
              target="_blank"
              rel="noopener noreferrer"
              class="text-body-small text-muted-a11y text-decoration-none"
            >
              www.giljo.ai
            </a>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
// eslint-allow giljo-internal/no-manual-api-url-composition
import { ref, computed, onMounted, shallowRef } from 'vue'
import AppAlert from '@/components/ui/AppAlert.vue'
import ForgotPasswordPin from '@/components/ForgotPasswordPin.vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import api, { apiClient } from '@/services/api'
import { getRuntimeConfig } from '@/config/api'
import { PRODUCT_NAME } from '@/branding'

const productName = PRODUCT_NAME
import configService from '@/services/configService'
import { isCeModeValue, isNonCeModeValue } from '@/composables/useGiljoMode'

const forgotPasswordEmailComponent = shallowRef(null)

const socialLoginButtonsComponent = shallowRef(null)

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const giljoMode = ref('ce')
const isNonCe = computed(() => isNonCeModeValue(giljoMode.value))
const editionLabel = computed(() => {
  switch (giljoMode.value) {
    case 'saas': return 'SaaS Edition'
    default: return 'Community Edition'
  }
})

const hostnameMismatch = ref(false)

async function fetchEditionOrgSetupStatus() {
  if (isCeModeValue(giljoMode.value)) return null
  const orgSetupLoaders = import.meta.glob('@/saas/services/orgSetup.js')
  const [loader] = Object.values(orgSetupLoaders)
  if (!loader) return null
  const mod = await loader()
  return mod.fetchOrgSetupStatus(apiClient)
}
const currentHostname = ref('')
const correctHost = ref('')
const correctUrl = ref('')

const username = ref('')
const password = ref('')
const rememberMe = ref(false)
const showPassword = ref(false)
const showForgotPassword = ref(false)
const showForgotPasswordEmail = ref(false)
const loading = ref(false)
const error = ref('')
const successMessage = ref('')
const loginForm = ref(null)

const rules = {
  username: (value) => !!value || 'Email or username is required',
  password: (value) => !!value || 'Password is required',
}

async function handleLogin() {
  const { valid } = await loginForm.value.validate()
  if (!valid) {
    return
  }

  loading.value = true
  error.value = ''

  try {
    await userStore.login(username.value, password.value)

    try {
      const firstLoginResponse = await api.auth.checkFirstLogin(username.value)
      const firstLoginData = firstLoginResponse.data

      if (firstLoginData.must_change_password || firstLoginData.must_set_pin) {
        router.push('/first-login')
        return
      }
    } catch (firstLoginErr) {
      console.warn('[Login] First login check failed:', firstLoginErr)
    }

    if (userStore.currentUser?.password_change_required) {
      router.push('/first-login')
      return
    }

    if (isNonCeModeValue(giljoMode.value)) {
      try {
        const orgStatus = await fetchEditionOrgSetupStatus()
        if (orgStatus?.data?.needs_setup) {
          router.push('/org-setup')
          return
        }
      } catch {
        // Silently continue to dashboard if org-setup check fails
        // (endpoint may not exist, network issue, etc.)
      }
    }

    localStorage.setItem('setup_completed', 'true')

    if (rememberMe.value) {
      localStorage.setItem('remember_me', 'true')
      localStorage.setItem('remembered_username', username.value)
    } else {
      localStorage.removeItem('remember_me')
      localStorage.removeItem('remembered_username')
    }

    successMessage.value = 'Login successful! Redirecting...'

    await new Promise((resolve) => setTimeout(resolve, 500))

    const redirect = route.query.redirect || '/'
    router.push(redirect)
  } catch (err) {
    if (err.response?.status === 401) {
      const detail = err.response?.data?.detail || ''
      if (detail.toLowerCase().includes('inactive')) {
        error.value = 'Account is inactive. Please contact your administrator.'
      } else if (
        detail.toLowerCase().includes('must_change_password') ||
        detail.toLowerCase().includes('change password')
      ) {
        router.push('/welcome')
        return
      } else {
        error.value = 'Invalid credentials'
      }
    } else if (err.response?.status === 403) {
      const detail = err.response?.data?.detail || ''
      if (
        detail.toLowerCase().includes('must_change_password') ||
        detail.toLowerCase().includes('change password')
      ) {
        router.push('/welcome')
        return
      }
      error.value = 'Access forbidden. Please contact your administrator.'
    } else if (err.response?.status === 429) {
      error.value = 'Too many sign-in attempts. Please wait a minute and try again.'
    } else if (err.response?.data?.detail) {
      error.value = err.response.data.detail
    } else if (err.code === 'ERR_NETWORK' || !err.response) {
      error.value = 'Network error - please check your connection and try again'
    } else if (err.message) {
      error.value = `Login failed: ${err.message}`
    } else {
      error.value = 'Login failed. Please try again.'
    }

    password.value = ''
  } finally {
    loading.value = false
  }
}

function handleForgotPasswordClick() {
  if (isCeModeValue(giljoMode.value)) {
    showForgotPassword.value = true
  } else {
    showForgotPasswordEmail.value = true
  }
}

function handlePasswordResetSuccess(message) {
  successMessage.value = message
  showForgotPassword.value = false
}

onMounted(async () => {
  const checkMismatch = () => {
    const cfg = getRuntimeConfig()
    if (!cfg?.api?.host) return false
    const pageHost = window.location.hostname
    const serverHost = cfg.api.host
    const isLocalPage = pageHost === 'localhost' || pageHost === '127.0.0.1'
    const isRemoteServer = serverHost !== 'localhost' && serverHost !== '127.0.0.1'
    if (isLocalPage && isRemoteServer) {
      currentHostname.value = pageHost
      correctHost.value = serverHost
      const proto = cfg.api.protocol || 'https'
      const port = window.location.port || cfg.api.port || 7272
      correctUrl.value = `${proto}://${serverHost}:${port}${window.location.pathname}`
      hostnameMismatch.value = true
    }
    return true
  }
  if (!checkMismatch()) {
    let attempts = 0
    const interval = setInterval(() => {
      if (checkMismatch() || ++attempts > 10) clearInterval(interval)
    }, 500)
  }

  try {
    await configService.fetchConfig()
    giljoMode.value = configService.getGiljoMode()
  } catch {
    // Default to CE on config failure
  }

  if (isNonCeModeValue(giljoMode.value)) {
    const forgotEmailLoaders = import.meta.glob('@/saas/components/ForgotPasswordEmail.vue')
    const [loader] = Object.values(forgotEmailLoaders)
    if (loader) {
      try {
        const mod = await loader()
        forgotPasswordEmailComponent.value = mod.default
      } catch (error) {
        console.warn('[Login] ForgotPasswordEmail failed to load:', error)
      }
    }

    const socialLoginLoaders = import.meta.glob('@/saas/components/auth/SocialLoginButtons.vue')
    const [socialLoginLoader] = Object.values(socialLoginLoaders)
    if (socialLoginLoader) {
      try {
        const mod = await socialLoginLoader()
        socialLoginButtonsComponent.value = mod.default
      } catch (error) {
        console.warn('[Login] SocialLoginButtons failed to load:', error)
      }
    }
  }

  if (route.query.passwordChanged === 'true') {
    successMessage.value = 'Password changed successfully! Please log in with your new credentials.'
  }

  if (route.query.forgot) {
    handleForgotPasswordClick()
  }

  const rememberedUsername = localStorage.getItem('remembered_username')
  const rememberMeFlag = localStorage.getItem('remember_me')

  if (rememberedUsername && rememberMeFlag === 'true') {
    username.value = rememberedUsername
    rememberMe.value = true
  }

})
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
.login-container {
  background: linear-gradient(135deg, rgb(30, 49, 71) 0%, rgb(18, 29, 42) 100%);
  min-height: 100vh;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1;
  overflow-y: auto;
}

.login-card {
  border-radius: $border-radius-rounded;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

/* Dark theme adjustments */
:deep(.v-theme--dark) .login-container {
  background: linear-gradient(135deg, rgb(18, 29, 42) 0%, rgb(10, 15, 22) 100%);
}

/* Tinted edition badge */
.edition-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: $border-radius-default;
  background: rgba(136, 149, 168, 0.15);
  color: var(--text-muted);
  font-weight: 500;
}

/* Remove Vuetify field overlay tint so inputs match the card background */
:deep(.v-field__overlay) {
  opacity: 0 !important;
}

/* Neutralize browser autofill background */
:deep(input:-webkit-autofill),
:deep(input:-webkit-autofill:hover),
:deep(input:-webkit-autofill:focus) {
  -webkit-box-shadow: 0 0 0 1000px rgb(var(--v-theme-surface)) inset !important;
  -webkit-text-fill-color: rgb(var(--v-theme-on-surface)) !important;
}
</style>
