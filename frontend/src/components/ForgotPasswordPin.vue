<template>
  <v-dialog
    v-model="internalShow"
    max-width="600"
    persistent
    scrollable
    attach
    @keydown.esc="handleClose"
  >
    <v-card v-draggable class="smooth-border">
      <div class="dlg-header">
        <v-icon class="dlg-icon" color="primary">mdi-lock-reset</v-icon>
        <span class="dlg-title">{{ stage === 'pin' ? 'Forgot Password?' : 'Reset Password' }}</span>
        <v-btn icon variant="text" size="small" class="dlg-close" :disabled="loading" aria-label="Close dialog" @click="handleClose">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </div>

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

        <AppAlert v-if="success" type="success" variant="tonal" class="mb-4">
          {{ success }}
        </AppAlert>

        <AppAlert v-if="lockoutMessage" type="warning" variant="tonal" class="mb-4">
          <strong>Account Locked:</strong> {{ lockoutMessage }}
        </AppAlert>

        <div v-if="stage === 'pin'">
          <p class="text-body-medium mb-4">
            Enter your username and 4-digit recovery PIN to reset your password.
          </p>

          <AppAlert
            v-if="attemptsRemaining !== null && attemptsRemaining < 5"
            type="warning"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            <strong>Warning:</strong> {{ attemptsRemaining }} attempt{{
              attemptsRemaining !== 1 ? 's' : ''
            }}
            remaining before lockout.
          </AppAlert>

          <v-form ref="pinForm" @submit.prevent="handleVerifyPin">
            <v-text-field
              v-model="username"
              label="Email or username"
              prepend-inner-icon="mdi-account"
              variant="outlined"
              :rules="[rules.username]"
              :disabled="loading"
              autofocus
              autocomplete="username"
              class="mb-4"
              aria-label="Enter your email or username"
              aria-required="true"
              @input="error = ''"
            />

            <v-text-field
              v-model="pin"
              label="Recovery PIN (4 digits)"
              prepend-inner-icon="mdi-numeric"
              variant="outlined"
              type="text"
              inputmode="numeric"
              pattern="[0-9]{4}"
              maxlength="4"
              :rules="pinRules"
              :disabled="loading"
              autocomplete="off"
              class="mb-4"
              aria-label="Enter your 4-digit recovery PIN"
              aria-required="true"
              hint="Enter the 4-digit PIN you set during account setup"
              persistent-hint
              @input="handlePinInput"
              @keypress="onlyNumbers"
            />

            <AppAlert type="info" variant="tonal" density="compact" class="mb-4">
              If you have forgotten both your password and PIN, please contact your administrator.
            </AppAlert>

            <v-btn
              type="submit"
              color="primary"
              size="large"
              block
              :loading="loading"
              :disabled="!username || !pin || pin.length !== 4 || loading"
              aria-label="Verify PIN and proceed to password reset"
            >
              <v-icon v-if="!loading" start>mdi-shield-check</v-icon>
              {{ loading ? 'Verifying...' : 'Verify PIN' }}
            </v-btn>
          </v-form>
        </div>

        <div v-if="stage === 'reset'">
          <AppAlert type="success" variant="tonal" class="mb-4">
            <strong>PIN Verified!</strong> Please enter your new password below.
          </AppAlert>

          <v-form ref="resetPasswordForm" @submit.prevent="handleResetPassword">
            <v-text-field
              v-model="newPassword"
              label="New Password"
              prepend-inner-icon="mdi-lock"
              :type="showPassword ? 'text' : 'password'"
              variant="outlined"
              :rules="passwordRules"
              :disabled="loading"
              autocomplete="new-password"
              autofocus
              class="mb-4"
              aria-label="Enter your new password"
              aria-required="true"
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

            <v-btn
              type="submit"
              color="primary"
              size="large"
              block
              :loading="loading"
              :disabled="!isPasswordValid || loading"
              aria-label="Reset password and return to login"
            >
              <v-icon v-if="!loading" start>mdi-lock-reset</v-icon>
              {{ loading ? 'Resetting...' : 'Reset Password' }}
            </v-btn>
          </v-form>
        </div>
      </v-card-text>

      <v-divider />

      <div class="dlg-footer">
        <v-spacer />
        <v-btn variant="text" :disabled="loading" @click="handleClose"> Cancel </v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import AppAlert from '@/components/ui/AppAlert.vue'
import api from '@/services/api'
import { PIN_RULES as pinRules, onlyNumbers, usePasswordForm } from '@/composables/usePasswordForm'

const props = defineProps({
  show: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:show', 'success'])

const internalShow = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const stage = ref('pin')
const username = ref('')
const pin = ref('')
const {
  newPassword,
  confirmPassword,
  showNewPassword: showPassword,
  showConfirmPassword,
  passwordRules,
  confirmPasswordRules,
  passwordRequirements,
} = usePasswordForm()
const loading = ref(false)
const error = ref('')
const success = ref('')
const lockoutMessage = ref('')
const attemptsRemaining = ref(null)
const pinForm = ref(null)
const resetPasswordForm = ref(null)
const rules = {
  username: (value) => !!value || 'Email or username is required',
}

const isPasswordValid = computed(() => {
  return (
    newPassword.value &&
    confirmPassword.value &&
    newPassword.value === confirmPassword.value &&
    passwordRequirements.value.every((req) => req.met)
  )
})

function handlePinInput(value) {
  pin.value = value.replace(/\D/g, '').slice(0, 4)
}

function resetFormState() {
  stage.value = 'pin'
  username.value = ''
  pin.value = ''
  newPassword.value = ''
  confirmPassword.value = ''
  showPassword.value = false
  showConfirmPassword.value = false
  error.value = ''
  success.value = ''
  lockoutMessage.value = ''
  attemptsRemaining.value = null
}

function handleClose() {
  if (!loading.value) {
    resetFormState()
    emit('update:show', false)
  }
}

async function handleVerifyPin() {
  const { valid } = await pinForm.value.validate()
  if (!valid) {
    return
  }

  loading.value = true
  error.value = ''
  lockoutMessage.value = ''

  try {
    const response = await api.auth.verifyPin({
      username: username.value,
      recovery_pin: pin.value,
    })

    if (response.data.valid) {
      stage.value = 'reset'
      error.value = ''
    } else {
      error.value = response.data.message || 'Invalid username or PIN.'
    }
  } catch (err) {
    console.error('[ForgotPassword] PIN verification failed:', err?.response?.status ?? err?.code)

    if (err.response?.data?.detail) {
      error.value = err.response.data.detail
    } else {
      error.value = 'Failed to verify PIN. Please try again.'
    }
  } finally {
    loading.value = false
  }
}

async function handleResetPassword() {
  const { valid } = await resetPasswordForm.value.validate()
  if (!valid) {
    return
  }

  loading.value = true
  error.value = ''

  try {
    await api.auth.verifyPinAndResetPassword({
      username: username.value,
      recovery_pin: pin.value,
      new_password: newPassword.value,
      confirm_password: confirmPassword.value,
    })

    success.value = 'Password reset successfully! You can now log in with your new password.'

    await new Promise((resolve) => setTimeout(resolve, 2000))

    resetFormState()
    emit('update:show', false)
    emit('success', 'Password reset successfully! Please log in with your new credentials.')
  } catch (err) {
    console.error('[ForgotPassword] Password reset failed:', err?.response?.status ?? err?.code)

    if (err.response?.status === 429) {
      lockoutMessage.value =
        err.response.data?.detail || 'Too many attempts. Please try again in 15 minutes.'
      attemptsRemaining.value = 0
      stage.value = 'pin'
    } else if (err.response?.data?.detail) {
      error.value = err.response.data.detail
    } else {
      error.value = 'Failed to reset password. Please try again.'
    }
  } finally {
    loading.value = false
  }
}

watch(
  () => props.show,
  (newValue) => {
    if (!newValue) {
      resetFormState()
    }
  },
)
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
.requirement-list {
  background: rgba(255, 255, 255, 0.05);
  border-radius: $border-radius-default;
  padding: 12px;
}

/* Remove Vuetify field overlay tint so inputs match the card background */
:deep(.v-field__overlay) {
  opacity: 0 !important;
}
</style>
