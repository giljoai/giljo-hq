<template>
  <v-container fluid class="fill-height first-login-container">
    <v-row class="align-center justify-center">
      <v-col cols="12" sm="10" md="8" lg="6">
        <v-card elevation="8" class="first-login-card smooth-border">
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
              <h1 class="text-headline-small font-weight-bold">Complete Account Setup</h1>
              <p class="text-body-medium text-muted-a11y mt-2">
                {{ isCeEdition ? 'Set your new password and recovery PIN' : 'Set your new password' }}
              </p>
            </div>
          </v-card-title>

          <v-divider />

          <v-card-text class="pa-6">
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

            <AppAlert type="info" variant="tonal" class="mb-4">
              <template v-if="isCeEdition">
                <strong>Security Setup Required:</strong> Please create a new password and 4-digit
                recovery PIN. Your recovery PIN can be used to reset your password if you forget it.
              </template>
              <template v-else>
                <strong>Security Setup Required:</strong> Please create a new password. If you
                forget it, you can reset it via email.
              </template>
            </AppAlert>

            <v-form ref="firstLoginForm" @submit.prevent="handleSubmit">
              <v-text-field
                v-model="currentPassword"
                label="Current Password"
                prepend-inner-icon="mdi-lock-outline"
                :type="showCurrentPassword ? 'text' : 'password'"
                variant="outlined"
                :rules="[(v) => !!v || 'Current password is required']"
                :disabled="loading"
                autocomplete="current-password"
                class="mb-4"
                aria-label="Enter your current password"
                aria-required="true"
                hint="Enter the temporary password you used to log in"
                persistent-hint
                @input="error = ''"
              >
                <template #append-inner>
                  <v-icon
                    tabindex="-1"
                    @click="showCurrentPassword = !showCurrentPassword"
                  >
                    {{ showCurrentPassword ? 'mdi-eye' : 'mdi-eye-off' }}
                  </v-icon>
                </template>
              </v-text-field>

              <v-text-field
                v-model="newPassword"
                label="New Password"
                prepend-inner-icon="mdi-lock"
                :type="showNewPassword ? 'text' : 'password'"
                variant="outlined"
                :rules="passwordRules"
                :disabled="loading"
                autocomplete="new-password"
                class="mb-4"
                aria-label="Enter your new password"
                aria-required="true"
                @input="error = ''"
              >
                <template #append-inner>
                  <v-icon
                    tabindex="-1"
                    @click="showNewPassword = !showNewPassword"
                  >
                    {{ showNewPassword ? 'mdi-eye' : 'mdi-eye-off' }}
                  </v-icon>
                </template>
              </v-text-field>

              <v-text-field
                v-model="confirmPassword"
                label="Confirm New Password"
                prepend-inner-icon="mdi-lock-check"
                :type="showConfirmPassword ? 'text' : 'password'"
                variant="outlined"
                :rules="confirmPasswordRules"
                :disabled="loading"
                autocomplete="new-password"
                class="mb-4"
                aria-label="Confirm your new password"
                aria-required="true"
                @input="error = ''"
              >
                <template #append-inner>
                  <v-icon
                    tabindex="-1"
                    @click="showConfirmPassword = !showConfirmPassword"
                  >
                    {{ showConfirmPassword ? 'mdi-eye' : 'mdi-eye-off' }}
                  </v-icon>
                </template>
              </v-text-field>

              <v-progress-linear
                :model-value="passwordStrength"
                :color="passwordStrengthColor"
                height="8"
                rounded
                class="mb-2"
                aria-label="Password strength indicator"
              />
              <p class="text-body-small mb-4" :class="passwordStrengthColor + '--text'">
                Password Strength: {{ passwordStrengthText }}
              </p>

              <v-list density="compact" class="requirement-list mb-4">
                <v-list-item v-for="req in passwordRequirements" :key="req.text" class="px-0 py-1">
                  <template #prepend>
                    <v-icon
                      :color="req.met ? 'success' : 'error'"
                      size="small"
                      :aria-label="req.met ? 'Requirement met' : 'Requirement not met'"
                    >
                      {{ req.met ? 'mdi-check-circle' : 'mdi-close-circle' }}
                    </v-icon>
                  </template>
                  <v-list-item-title class="text-body-small">{{ req.text }}</v-list-item-title>
                </v-list-item>
              </v-list>

              <template v-if="isCeEdition">
              <v-divider class="my-4" />

              <h3 class="text-body-large font-weight-bold mb-2">
                <v-icon class="mr-2">mdi-shield-key</v-icon>
                Recovery PIN Setup
              </h3>
              <p class="text-body-small text-muted-a11y mb-4">
                Create a 4-digit PIN for password recovery. This PIN can be used if you forget your
                password.
              </p>

              <v-text-field
                v-model="recoveryPin"
                label="Recovery PIN (4 digits)"
                prepend-inner-icon="mdi-numeric"
                variant="outlined"
                type="text"
                inputmode="numeric"
                maxlength="4"
                :rules="pinRules"
                :disabled="loading"
                autocomplete="off"
                class="mb-4"
                aria-label="Enter your 4-digit recovery PIN"
                aria-required="true"
                hint="Enter 4 digits (example: 1234)"
                persistent-hint
                @keypress="onlyNumbers"
              />

              <v-text-field
                v-model="confirmPin"
                label="Confirm Recovery PIN"
                prepend-inner-icon="mdi-numeric-positive-1"
                variant="outlined"
                type="text"
                inputmode="numeric"
                maxlength="4"
                :rules="confirmPinRules"
                :disabled="loading"
                autocomplete="off"
                class="mb-4"
                aria-label="Confirm your 4-digit recovery PIN"
                aria-required="true"
                @keypress="onlyNumbers"
              />

              <AppAlert type="warning" variant="tonal" density="compact" class="mb-4">
                <strong>Important:</strong> Keep your recovery PIN secure. Do not use obvious PINs
                like 0000 or 1234.
              </AppAlert>
              </template>

              <v-btn
                type="submit"
                color="primary"
                size="large"
                block
                :loading="loading"
                :disabled="!isFormValid || loading"
                class="mt-4"
                aria-label="Complete setup and continue to dashboard"
              >
                <v-icon v-if="!loading" start>mdi-check-circle</v-icon>
                {{ loading ? 'Setting up...' : 'Complete Setup' }}
              </v-btn>
            </v-form>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import AppAlert from '@/components/ui/AppAlert.vue'
import api, { apiClient } from '@/services/api'
import configService from '@/services/configService'
import { PIN_RULES as pinRules, onlyNumbers, usePasswordForm } from '@/composables/usePasswordForm'
import { PRODUCT_NAME } from '@/branding'

const productName = PRODUCT_NAME

const router = useRouter()

const isCeEdition = computed(() => configService.getGiljoMode() === 'ce')

async function fetchEditionOrgSetupStatus() {
  if (isCeEdition.value) return null
  const orgSetupLoaders = import.meta.glob('@/saas/services/orgSetup.js')
  const [loader] = Object.values(orgSetupLoaders)
  if (!loader) return null
  const mod = await loader()
  return mod.fetchOrgSetupStatus(apiClient)
}

const currentPassword = ref('')
const {
  newPassword,
  confirmPassword,
  showNewPassword,
  showConfirmPassword,
  passwordRules,
  confirmPasswordRules,
  passwordRequirements,
} = usePasswordForm()
const recoveryPin = ref('')
const confirmPin = ref('')
const showCurrentPassword = ref(false)
const loading = ref(false)
const error = ref('')
const firstLoginForm = ref(null)

const confirmPinRules = [
  (v) => !!v || 'PIN confirmation is required',
  (v) => /^\d{4}$/.test(v) || 'PIN must be exactly 4 digits',
  (v) => v === recoveryPin.value || 'PINs do not match',
]

const passwordStrength = computed(() => {
  const metRequirements = passwordRequirements.value.filter((req) => req.met).length
  return (metRequirements / passwordRequirements.value.length) * 100
})

const passwordStrengthColor = computed(() => {
  if (passwordStrength.value < 40) return 'error'
  if (passwordStrength.value < 70) return 'warning'
  return 'success'
})

const passwordStrengthText = computed(() => {
  if (passwordStrength.value < 40) return 'Weak'
  if (passwordStrength.value < 70) return 'Good'
  return 'Strong'
})

const isFormValid = computed(() => {
  const passwordValid =
    currentPassword.value &&
    newPassword.value &&
    confirmPassword.value &&
    newPassword.value === confirmPassword.value &&
    passwordRequirements.value.every((req) => req.met)

  if (!isCeEdition.value) {
    return passwordValid
  }

  return (
    passwordValid &&
    recoveryPin.value &&
    confirmPin.value &&
    recoveryPin.value === confirmPin.value &&
    /^\d{4}$/.test(recoveryPin.value) &&
    /^\d{4}$/.test(confirmPin.value)
  )
})

async function handleSubmit() {
  const { valid } = await firstLoginForm.value.validate()
  if (!valid) {
    return
  }

  loading.value = true
  error.value = ''

  try {
    const payload = {
      current_password: currentPassword.value,
      new_password: newPassword.value,
      confirm_password: confirmPassword.value,
    }
    if (isCeEdition.value) {
      payload.recovery_pin = recoveryPin.value
      payload.confirm_pin = confirmPin.value
    }
    await api.auth.completeFirstLogin(payload)

    if (!isCeEdition.value) {
      try {
        const orgStatus = await fetchEditionOrgSetupStatus()
        if (orgStatus?.data?.needs_setup) {
          router.push('/org-setup')
          return
        }
      } catch {
        // Silently continue to dashboard if org-setup check fails
      }
    }

    router.push('/')
  } catch (err) {
    console.error('[FirstLogin] Failed to complete setup:', err?.response?.status ?? err?.code)

    if (err.response?.data?.detail) {
      error.value = err.response.data.detail
    } else if (err.message) {
      error.value = `Setup failed: ${err.message}`
    } else {
      error.value = 'Failed to complete setup. Please try again.'
    }
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
.first-login-container {
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

.first-login-card {
  border-radius: $border-radius-rounded;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.requirement-list {
  background: rgba(255, 255, 255, 0.05);
  border-radius: $border-radius-default;
  padding: 12px;
}

/* Dark theme adjustments */
:deep(.v-theme--dark) .first-login-container {
  background: linear-gradient(135deg, rgb(18, 29, 42) 0%, rgb(10, 15, 22) 100%);
}

/* Remove Vuetify field overlay tint so inputs match the card background */
:deep(.v-field__overlay) {
  opacity: 0 !important;
}
</style>
