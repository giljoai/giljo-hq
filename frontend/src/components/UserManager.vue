<template>
  <v-container fluid>
    <!-- Header with search and add button -->
    <v-row class="mb-4">
      <v-col cols="12" md="8">
        <v-text-field
          v-model="search"
          prepend-inner-icon="mdi-magnify"
          label="Search users"
          variant="outlined"
          density="comfortable"
          clearable
          hide-details
        />
      </v-col>
      <v-col v-if="canAddUsers" cols="12" md="4" class="d-flex justify-end">
        <v-btn
          color="primary"
          :disabled="loading"
          prepend-icon="mdi-account-plus"
          @click="openCreateDialog"
        >
          Add User
        </v-btn>
      </v-col>
    </v-row>

    <!-- User table -->
    <v-data-table
      :headers="headers"
      :items="filteredUsers"
      :loading="loading"
      :search="search"
      class="elevation-0"
    >
      <!-- Username column with icon -->
      <template #item.username="{ item }">
        <div class="d-flex align-center">
          <v-icon size="small" class="mr-2">mdi-account</v-icon>
          <span class="font-weight-medium">{{ item.username }}</span>
        </div>
      </template>

      <!-- Email column -->
      <template #item.email="{ item }">
        <div class="d-flex align-center">
          <v-icon size="small" class="mr-2 text-muted-a11y">mdi-email</v-icon>
          <span class="text-body-small">{{ item.email || 'No email' }}</span>
        </div>
      </template>

      <!-- Role badge column -->
      <template #item.role="{ item }">
        <v-chip :color="getRoleColor(item.role)" size="small" label>
          <v-icon start size="small">{{ getRoleIcon(item.role) }}</v-icon>
          {{ getRoleTitle(item.role) }}
        </v-chip>
      </template>

      <!-- Status badge column -->
      <template #item.is_active="{ item }">
        <v-chip :color="item.is_active ? 'success' : 'default'" size="small" label>
          <v-icon start size="small">
            {{ item.is_active ? 'mdi-check-circle' : 'mdi-cancel' }}
          </v-icon>
          {{ item.is_active ? 'Active' : 'Inactive' }}
        </v-chip>
      </template>

      <!-- Created date column -->
      <template #item.created_at="{ item }">
        <div class="d-flex align-center">
          <v-icon size="small" class="mr-2 text-muted-a11y">mdi-calendar-plus</v-icon>
          <span class="text-body-small">{{ formatDate(item.created_at) }}</span>
        </div>
      </template>

      <!-- Last login column -->
      <template #item.last_login="{ item }">
        <span class="text-body-small">{{ formatRelativeTime(item.last_login) }}</span>
      </template>

      <!-- Actions column -->
      <template #item.actions="{ item }">
        <v-menu>
          <template #activator="{ props }">
            <v-btn icon="mdi-dots-vertical" size="small" variant="text" v-bind="props" />
          </template>
          <v-list density="compact">
            <v-list-item @click="openEditDialog(item)">
              <template #prepend>
                <v-icon>mdi-pencil</v-icon>
              </template>
              <v-list-item-title>Edit User</v-list-item-title>
            </v-list-item>
            <!-- CE-only: local credential management (self-hosted) -->
            <v-list-item v-if="showPasswordPinAction" @click="openPasswordDialog(item)">
              <template #prepend>
                <v-icon>mdi-key-variant</v-icon>
              </template>
              <v-list-item-title>Change Password &amp; PIN</v-list-item-title>
            </v-list-item>
            <!-- SaaS-only: injected from saas bundle via import.meta.glob -->
            <v-list-item
              v-if="saasResetAction"
              :disabled="sendingReset"
              @click="triggerSaasResetAction(item)"
            >
              <template #prepend>
                <v-icon>{{ saasResetAction.icon }}</v-icon>
              </template>
              <v-list-item-title>{{ saasResetAction.label }}</v-list-item-title>
            </v-list-item>
            <v-divider />
            <!-- Deactivate is disabled for the current user (self-service via Settings). -->
            <v-tooltip v-if="item.id === currentUser?.id" location="start" max-width="260">
              <template #activator="{ props: tooltipProps }">
                <div v-bind="tooltipProps" data-test="deactivate-self-tooltip-anchor">
                  <v-list-item disabled>
                    <template #prepend>
                      <v-icon>{{
                        item.is_active ? 'mdi-account-off' : 'mdi-account-check'
                      }}</v-icon>
                    </template>
                    <v-list-item-title>
                      {{ item.is_active ? 'Deactivate' : 'Activate' }}
                    </v-list-item-title>
                  </v-list-item>
                </div>
              </template>
              <span> To delete your own account, use Settings → Account → Danger Zone. </span>
            </v-tooltip>
            <v-list-item v-else @click="toggleUserStatus(item)">
              <template #prepend>
                <v-icon>{{ item.is_active ? 'mdi-account-off' : 'mdi-account-check' }}</v-icon>
              </template>
              <v-list-item-title>
                {{ item.is_active ? 'Deactivate' : 'Activate' }}
              </v-list-item-title>
            </v-list-item>
          </v-list>
        </v-menu>
      </template>
    </v-data-table>

    <!-- Create/Edit User Dialog -->
    <v-dialog v-model="showUserDialog" max-width="600" persistent scrollable>
      <v-card v-draggable class="smooth-border">
        <div class="dlg-header">
          <v-icon class="dlg-icon">{{ isEditMode ? 'mdi-pencil' : 'mdi-account-plus' }}</v-icon>
          <span class="dlg-title">{{ isEditMode ? 'Edit User' : 'Create New User' }}</span>
          <v-btn icon variant="text" class="dlg-close" @click="closeUserDialog">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </div>

        <v-card-text>
          <v-form ref="formRef" @submit.prevent="saveUser">
            <v-text-field
              v-model="userForm.username"
              label="Username"
              variant="outlined"
              :rules="[rules.username]"
              required
              autocomplete="off"
              class="mb-3"
            />

            <v-text-field
              v-model="userForm.email"
              label="Email"
              variant="outlined"
              type="email"
              :rules="[rules.email]"
              autocomplete="off"
              class="mb-3"
            />

            <v-text-field
              v-if="!isEditMode"
              v-model="userForm.password"
              label="Password"
              variant="outlined"
              type="password"
              :rules="[rules.password, rules.minLength]"
              hint="Min 8 characters"
              persistent-hint
              required
              autocomplete="new-password"
              class="mb-3"
            />

            <v-select
              v-model="userForm.role"
              label="Role"
              variant="outlined"
              :items="roleOptions"
              item-value="value"
              item-title="title"
              :rules="[rules.role]"
              required
              class="mb-3"
            />

            <v-switch
              v-if="isEditMode"
              v-model="userForm.is_active"
              label="Active"
              color="success"
              :disabled="userForm.id === currentUser?.id"
            />
          </v-form>
        </v-card-text>

        <div class="dlg-footer">
          <v-spacer />
          <v-btn variant="text" :disabled="saving" @click="closeUserDialog"> Cancel </v-btn>
          <v-btn color="primary" variant="flat" :loading="saving" @click="saveUser">
            {{ isEditMode ? 'Update' : 'Create' }}
          </v-btn>
        </div>
      </v-card>
    </v-dialog>

    <!-- Change Password & PIN Dialog -->
    <v-dialog v-model="showPasswordDialog" max-width="500" persistent>
      <v-card v-draggable class="smooth-border">
        <div class="dlg-header">
          <v-icon class="dlg-icon">mdi-key-variant</v-icon>
          <span class="dlg-title">Change Password &amp; PIN</span>
          <v-btn icon variant="text" class="dlg-close" @click="closePasswordDialog">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </div>

        <v-card-text>
          <v-alert type="info" variant="tonal" density="compact" class="mb-4">
            Managing credentials for: <strong>{{ passwordUser?.username }}</strong>
          </v-alert>

          <!-- Password Section -->
          <div class="text-title-small mb-2">Password</div>
          <v-text-field
            v-model="newPassword"
            label="New Password"
            variant="outlined"
            type="password"
            :rules="[rules.minLength]"
            density="compact"
            class="mb-1"
          />
          <v-text-field
            v-model="confirmPassword"
            label="Confirm Password"
            variant="outlined"
            type="password"
            :rules="newPassword ? [(v) => v === newPassword || 'Passwords do not match'] : []"
            density="compact"
            class="mb-2"
          />
          <v-btn
            color="primary"
            variant="flat"
            size="small"
            :loading="changingPassword"
            :disabled="!newPassword || newPassword.length < 8 || newPassword !== confirmPassword"
            @click="changePassword"
          >
            Save Password
          </v-btn>

          <v-divider class="my-4" />

          <!-- PIN Section -->
          <div class="text-title-small mb-2">Recovery PIN</div>
          <v-text-field
            v-model="newPin"
            label="New PIN (4 digits)"
            variant="outlined"
            type="text"
            inputmode="numeric"
            pattern="[0-9]{4}"
            maxlength="4"
            :rules="[(v) => !v || /^\d{4}$/.test(v) || 'PIN must be exactly 4 digits']"
            density="compact"
            class="mb-1"
            @keypress="onlyNumbers"
          />
          <v-text-field
            v-model="confirmPin"
            label="Confirm PIN"
            variant="outlined"
            type="text"
            inputmode="numeric"
            pattern="[0-9]{4}"
            maxlength="4"
            :rules="newPin ? [(v) => v === newPin || 'PINs do not match'] : []"
            density="compact"
            class="mb-2"
            @keypress="onlyNumbers"
          />
          <v-btn
            color="primary"
            variant="flat"
            size="small"
            :loading="changingPin"
            :disabled="!newPin || !/^\d{4}$/.test(newPin) || newPin !== confirmPin"
            @click="changePin"
          >
            Save PIN
          </v-btn>
        </v-card-text>

        <div class="dlg-footer">
          <v-spacer />
          <v-btn variant="text" @click="closePasswordDialog"> Close </v-btn>
        </div>
      </v-card>
    </v-dialog>

    <!-- Status Toggle Confirmation Dialog -->
    <v-dialog v-model="showStatusDialog" max-width="500">
      <v-card v-draggable class="smooth-border">
        <div :class="['dlg-header', statusUser?.is_active ? 'dlg-header--warning' : '']">
          <v-icon class="dlg-icon">
            {{ statusUser?.is_active ? 'mdi-account-off' : 'mdi-account-check' }}
          </v-icon>
          <span class="dlg-title"
            >{{ statusUser?.is_active ? 'Deactivate' : 'Activate' }} User?</span
          >
          <v-btn icon variant="text" class="dlg-close" @click="closeStatusDialog">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </div>

        <v-card-text class="pt-6">
          <p class="text-body-large mb-2">
            You are about to {{ statusUser?.is_active ? 'deactivate' : 'activate' }}:
          </p>
          <v-card variant="flat" class="mb-4 pa-3 smooth-border">
            <div class="d-flex align-center">
              <v-icon class="mr-2">mdi-account</v-icon>
              <strong>{{ statusUser?.username }}</strong>
            </div>
            <div class="d-flex align-center mt-2">
              <v-icon class="mr-2" size="small">{{ getRoleIcon(statusUser?.role) }}</v-icon>
              <span class="text-body-small">{{ getRoleTitle(statusUser?.role) }}</span>
            </div>
          </v-card>

          <v-alert v-if="statusUser?.is_active" type="warning" variant="tonal" density="compact">
            This user will no longer be able to log in to the system.
          </v-alert>
        </v-card-text>

        <div class="dlg-footer">
          <v-spacer />
          <v-btn variant="text" :disabled="togglingStatus" @click="closeStatusDialog">
            Cancel
          </v-btn>
          <v-btn
            :color="statusUser?.is_active ? 'warning' : 'success'"
            variant="flat"
            :loading="togglingStatus"
            @click="confirmToggleStatus"
          >
            {{ statusUser?.is_active ? 'Deactivate' : 'Activate' }}
          </v-btn>
        </div>
      </v-card>
    </v-dialog>

    <!-- CE Single-User Limit Dialog -->
    <v-dialog v-model="showCeLimitDialog" max-width="480">
      <v-card class="smooth-border">
        <div class="dlg-header dlg-header--primary">
          <v-icon class="mr-2">mdi-account-lock</v-icon>
          Single-User License
          <v-spacer />
          <v-btn
            icon
            size="small"
            variant="text"
            class="dlg-close"
            @click="showCeLimitDialog = false"
          >
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </div>
        <v-card-text class="pt-5 pb-4">
          <p class="mb-3">
            GiljoAI Community Edition is licensed for <strong>single-user</strong> use.
          </p>
          <p class="mb-0" style="color: var(--text-muted)">
            To add additional users, upgrade to a Commercial License. Contact
            <strong>sales@giljo.ai</strong> for details.
          </p>
        </v-card-text>
        <div class="dlg-footer">
          <v-spacer />
          <v-btn variant="text" @click="showCeLimitDialog = false">Close</v-btn>
        </div>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { formatDistanceToNow } from 'date-fns'
import api from '@/services/api'
import configService from '@/services/configService'
import setupService from '@/services/setupService'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { useFormatDate } from '@/composables/useFormatDate'

const { formatDate } = useFormatDate()

// Store
const userStore = useUserStore()
const currentUser = computed(() => userStore.currentUser)
const { showToast } = useToast()

// State
const users = ref([])
const loading = ref(false)
const search = ref('')

// Template refs
const formRef = ref(null)

// Edition
const isCommunityEdition = computed(() => configService.getEdition() === 'community')
const showCeLimitDialog = ref(false)

// Capability flags — ADR-002: mode via setupService.checkEnhancedStatus().
// isCe drives all gating; no scattered mode checks elsewhere in this file.
const isCe = ref(false)
const showPasswordPinAction = computed(() => isCe.value) // CE-only kebab item
const saasResetAction = ref(null) // SaaS-only: populated by import.meta.glob

async function loadCapabilities() {
  try {
    const status = await setupService.checkEnhancedStatus()
    isCe.value = (status?.mode ?? 'ce') === 'ce'
    if (!isCe.value) {
      // ADR-004: import.meta.glob keeps SaaS code out of CE bundle.
      // saas/ is stripped on CE export — loader absent = graceful no-op.
      const loaders = import.meta.glob('@/saas/components/UserPasswordResetAction.js')
      const [loader] = Object.values(loaders)
      if (loader) {
        try {
          const mod = await loader()
          saasResetAction.value = mod.default ?? null
        } catch (err) {
          console.warn('[UserManager] UserPasswordResetAction failed to load:', err)
        }
      }
    }
  } catch (err) {
    console.warn('[UserManager] loadCapabilities error, defaulting to CE:', err)
    isCe.value = true
  }
}

// sendPasswordReset: axiosPost(targetUser) => Promise<{data:{email,...}}>
// Toast copy (DoD exact):
//   other user → "Reset link emailed to <email> — they'll set a new password from that link."
//   self        → "Reset link emailed to you — you'll be logged out after you reset."
const sendingReset = ref(false)

async function sendPasswordReset(targetUser, axiosPost) {
  if (sendingReset.value) return
  sendingReset.value = true
  try {
    const response = await axiosPost(targetUser)
    const email = response?.data?.email ?? targetUser.email
    const isSelf = targetUser.id === currentUser.value?.id
    if (isSelf) {
      showToast({
        message: "Reset link emailed to you — you'll be logged out after you reset.",
        type: 'success',
      })
    } else {
      showToast({
        message: `Reset link emailed to ${email} — they'll set a new password from that link.`,
        type: 'success',
      })
    }
  } catch (err) {
    const detail = err?.response?.data?.detail ?? 'Failed to send reset link. Please try again.'
    showToast({ message: detail, type: 'error' })
  } finally {
    sendingReset.value = false
  }
}

function triggerSaasResetAction(targetUser) {
  if (!saasResetAction.value) return
  sendPasswordReset(targetUser, saasResetAction.value.handler)
}

// Multi-user add hidden across all editions until SaaS Team tier ships.
const canAddUsers = computed(() => false)

// Dialog state
const showUserDialog = ref(false)
const showPasswordDialog = ref(false)
const showStatusDialog = ref(false)
const isEditMode = ref(false)
const saving = ref(false)
const changingPassword = ref(false)
const changingPin = ref(false)
const togglingStatus = ref(false)
const userForm = ref({
  id: null,
  username: '',
  email: '',
  password: '',
  role: 'developer',
  is_active: true,
})

const passwordUser = ref(null)
const newPassword = ref('')
const confirmPassword = ref('')
const newPin = ref('')
const confirmPin = ref('')
const statusUser = ref(null)
// Table configuration
const headers = [
  { title: 'Username', key: 'username', sortable: true },
  { title: 'Email', key: 'email', sortable: true },
  { title: 'Role', key: 'role', sortable: true },
  { title: 'Status', key: 'is_active', sortable: true },
  { title: 'Created', key: 'created_at', sortable: true },
  { title: 'Last Login', key: 'last_login', sortable: true },
  { title: 'Actions', key: 'actions', sortable: false, align: 'end' },
]

// Role configuration
const roleOptions = [
  { value: 'admin', title: 'Administrator', color: 'error', icon: 'mdi-shield-crown' },
  { value: 'developer', title: 'Developer', color: 'primary', icon: 'mdi-code-tags' },
  { value: 'viewer', title: 'Viewer', color: 'info', icon: 'mdi-eye' },
]

// Form validation rules
const rules = {
  username: (value) => !!value || 'Username is required',
  password: (value) => !!value || 'Password is required',
  role: (value) => !!value || 'Role is required',
  minLength: (value) => !value || value.length >= 8 || 'Password must be at least 8 characters',
  email: (value) =>
    !value ||
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ||
    'Enter a valid email (e.g. user@company.com)',
}

const filteredUsers = computed(() => {
  if (!search.value) return users.value
  const searchLower = search.value.toLowerCase()
  return users.value.filter(
    (user) =>
      user.username.toLowerCase().includes(searchLower) ||
      (user.email && user.email.toLowerCase().includes(searchLower)),
  )
})

function getRoleColor(role) {
  const roleConfig = roleOptions.find((r) => r.value === role)
  return roleConfig?.color || 'default'
}

function getRoleIcon(role) {
  const roleConfig = roleOptions.find((r) => r.value === role)
  return roleConfig?.icon || 'mdi-account'
}

function getRoleTitle(role) {
  const roleConfig = roleOptions.find((r) => r.value === role)
  return roleConfig?.title || role
}

function formatRelativeTime(timestamp) {
  if (!timestamp) return 'Never'
  try {
    return formatDistanceToNow(new Date(timestamp), { addSuffix: true })
  } catch {
    return 'Unknown'
  }
}

async function loadUsers() {
  loading.value = true
  try {
    const response = await api.auth.listUsers()
    users.value = response.data
  } catch (err) {
    console.error('[UserManager] Failed to load users:', err)
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  if (isCommunityEdition.value && users.value.length >= 1) {
    showCeLimitDialog.value = true
    return
  }
  isEditMode.value = false
  userForm.value = {
    id: null,
    username: '',
    email: '',
    password: '',
    role: 'developer',
    is_active: true,
  }
  showUserDialog.value = true
}

function openEditDialog(user) {
  isEditMode.value = true
  userForm.value = {
    id: user.id,
    username: user.username,
    email: user.email || '',
    password: '',
    role: user.role,
    is_active: user.is_active,
  }
  showUserDialog.value = true
}

function closeUserDialog() {
  showUserDialog.value = false
  userForm.value = {
    id: null,
    username: '',
    email: '',
    password: '',
    role: 'developer',
    is_active: true,
  }
}

async function saveUser() {
  saving.value = true
  try {
    if (isEditMode.value) {
      // Update existing user
      await api.auth.updateUser(userForm.value.id, {
        username: userForm.value.username,
        email: userForm.value.email || null,
        role: userForm.value.role,
        is_active: userForm.value.is_active,
      })
    } else {
      // Create new user
      await api.auth.register({
        username: userForm.value.username,
        email: userForm.value.email || null,
        password: userForm.value.password,
        role: userForm.value.role,
      })
    }

    // Reload users list
    await loadUsers()
    closeUserDialog()
  } catch (err) {
    console.error('[UserManager] Failed to save user:', err)
    // Extract error message from response
    const errorMessage = err.response?.data?.detail || err.message || 'Failed to save user'
    // Show user-friendly message
    if (errorMessage.toLowerCase().includes('already exists')) {
      showToast({
        message: 'Username or email already exists. Please use different values.',
        type: 'warning',
      })
    } else {
      showToast({ message: errorMessage, type: 'error' })
    }
  } finally {
    saving.value = false
  }
}

function onlyNumbers(event) {
  const charCode = event.which ? event.which : event.keyCode
  if (charCode < 48 || charCode > 57) {
    event.preventDefault()
  }
}

function openPasswordDialog(user) {
  passwordUser.value = user
  newPassword.value = ''
  confirmPassword.value = ''
  newPin.value = ''
  confirmPin.value = ''
  showPasswordDialog.value = true
}

function closePasswordDialog() {
  showPasswordDialog.value = false
  passwordUser.value = null
  newPassword.value = ''
  confirmPassword.value = ''
  newPin.value = ''
  confirmPin.value = ''
}

async function changePassword() {
  if (!passwordUser.value || !newPassword.value || newPassword.value !== confirmPassword.value)
    return

  changingPassword.value = true
  try {
    await api.auth.updateUser(passwordUser.value.id, {
      password: newPassword.value,
    })
    newPassword.value = ''
    confirmPassword.value = ''
    showToast({ message: 'Password updated successfully', type: 'success' })
  } catch (err) {
    console.error('[UserManager] Failed to change password:', err)
    showToast({ message: 'Failed to update password', type: 'error' })
  } finally {
    changingPassword.value = false
  }
}

async function changePin() {
  if (!passwordUser.value || !newPin.value || newPin.value !== confirmPin.value) return

  changingPin.value = true
  try {
    await api.auth.updateUser(passwordUser.value.id, {
      recovery_pin: newPin.value,
    })
    newPin.value = ''
    confirmPin.value = ''
    showToast({ message: 'Recovery PIN updated successfully', type: 'success' })
  } catch (err) {
    console.error('[UserManager] Failed to change PIN:', err)
    showToast({ message: 'Failed to update PIN', type: 'error' })
  } finally {
    changingPin.value = false
  }
}

function toggleUserStatus(user) {
  statusUser.value = user
  showStatusDialog.value = true
}

function closeStatusDialog() {
  showStatusDialog.value = false
  statusUser.value = null
}

async function confirmToggleStatus() {
  if (!statusUser.value) return

  togglingStatus.value = true
  try {
    await api.auth.updateUser(statusUser.value.id, {
      is_active: !statusUser.value.is_active,
    })
    await loadUsers()
    closeStatusDialog()
  } catch (err) {
    console.error('[UserManager] Failed to toggle user status:', err)
  } finally {
    togglingStatus.value = false
  }
}

// Lifecycle
onMounted(() => {
  loadUsers()
  loadCapabilities()
})
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
.v-data-table {
  border-radius: $border-radius-default;
}

/* Accessibility: Focus indicators */
.v-btn:focus-visible {
  outline: 2px solid rgba(var(--v-theme-primary), 0.5);
  outline-offset: 2px;
}
</style>
