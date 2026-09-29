<template>
  <v-menu :close-on-content-click="true" location="right" offset="8">
    <template #activator="{ props: menuProps }">
      <div
        v-bind="menuProps"
        class="nav-orb nav-orb--avatar"
        role="button"
        tabindex="0"
        aria-label="User menu"
      >
        <span v-if="currentUser" class="nav-orb-initials">{{ userInitials }}</span>
        <v-icon v-else size="18">mdi-account</v-icon>
        <component :is="accountStatusBadgeComponent" v-if="accountStatusBadgeComponent" />
      </div>
    </template>

    <v-list density="compact" min-width="220">
      <template v-if="accountBadgeState && accountBadgeState !== 'none'">
        <v-list-item
          data-test="account-status-section"
          :class="[
            'account-status-section',
            `account-status-section--${accountBadgeStateModifier}`,
          ]"
        >
          <v-list-item-title class="account-status-section__title">
            {{ accountStatusTitle }}
          </v-list-item-title>
          <v-list-item-subtitle class="account-status-section__subtitle">
            {{ accountStatusSubtitle }}
          </v-list-item-subtitle>
          <div class="account-status-section__actions mt-2">
            <v-btn
              v-if="isAccountScheduledForDeletion"
              size="small"
              color="warning"
              variant="flat"
              :loading="cancellingDeletion"
              data-test="dropdown-cancel-deletion"
              @click.stop="$emit('cancel-deletion')"
            >
              Cancel deletion
            </v-btn>
            <v-btn
              v-else
              size="small"
              color="primary"
              variant="flat"
              data-test="dropdown-upgrade-plan"
              @click="$emit('upgrade')"
            >
              Upgrade plan
            </v-btn>
          </div>
        </v-list-item>
        <v-divider />
      </template>

      <v-list-item
        v-if="currentUser"
        :to="{ path: '/account/profile' }"
        prepend-icon="mdi-account"
        class="cursor-pointer"
      >
        <v-list-item-title class="font-weight-medium">
          {{ currentUser.username }}
        </v-list-item-title>
        <v-list-item-subtitle v-if="orgName" class="text-body-small mt-1">
          {{ orgName }}
        </v-list-item-subtitle>
        <v-list-item-subtitle
          v-if="currentUser.role && isCeEdition"
          class="d-flex align-center mt-2 gap-2"
          data-test="user-role-badges"
        >
          <v-chip
            :color="getRoleColor(currentUser.role)"
            size="small"
            variant="flat"
            class="text-body-small"
          >
            {{ currentUser.role }}
          </v-chip>
          <RoleBadge v-if="orgRole" :role="orgRole" size="small" />
        </v-list-item-subtitle>
      </v-list-item>

      <v-divider v-if="currentUser" />

      <v-list-item :to="{ path: '/account/profile' }">
        <template #prepend>
          <v-icon>mdi-account</v-icon>
        </template>
        <v-list-item-title>Account / Profile</v-list-item-title>
      </v-list-item>

      <v-list-item
        v-if="isAdmin && isCeEdition"
        :to="{ name: 'SystemSettings' }"
      >
        <template #prepend>
          <v-icon color="error">mdi-cog</v-icon>
        </template>
        <v-list-item-title>Admin Settings</v-list-item-title>
      </v-list-item>

      <v-divider />

      <v-list-item :to="{ name: 'UserGuide' }">
        <template #prepend>
          <v-icon>mdi-book-open-variant</v-icon>
        </template>
        <v-list-item-title>User Guide</v-list-item-title>
      </v-list-item>

      <v-list-item v-if="isNonCeEdition" @click="showResetPasswordConfirm = true">
        <template #prepend>
          <v-icon>mdi-lock-reset</v-icon>
        </template>
        <v-list-item-title>Reset Password</v-list-item-title>
      </v-list-item>

      <v-list-item
        prepend-icon="mdi-information-outline"
        title="About"
        @click="aboutDialog = true"
      />

      <v-divider />

      <v-list-item
        v-if="currentUser"
        prepend-icon="mdi-logout"
        title="Logout"
        @click="$emit('logout')"
      />
    </v-list>
  </v-menu>

  <v-dialog v-model="aboutDialog" max-width="380">
    <v-card class="smooth-border">
      <v-btn
        icon="mdi-close"
        size="x-small"
        variant="text"
        style="position: absolute; right: 8px; top: 8px"
        @click="aboutDialog = false"
      />
      <v-card-text class="pa-5 text-body-medium">
        <div class="font-weight-bold mb-3">{{ productName }}</div>
        {{ versionLabel }}<br />
        {{ aboutEditionLabel }}<br />
        License: {{ aboutLicenseLabel }}<br /><br />

        {{ aboutLongDescription }}<br /><br />

        <a href="https://www.giljo.ai" target="_blank" class="about-link">giljo.ai</a>
        &nbsp;&middot;&nbsp;
        <a
          href="https://github.com/giljoai/giljo-hq/blob/master/LICENSE"
          target="_blank"
          class="about-link"
          >View License</a
        >
        <template v-if="isCeEdition && licenseStatus === 'Unlicensed'">
          &nbsp;&middot;&nbsp;
          <a href="mailto:sales@giljo.ai" class="about-link">Get a License</a>
        </template>
      </v-card-text>
    </v-card>
  </v-dialog>

  <BaseDialog
    v-model="showResetPasswordConfirm"
    type="warning"
    title="Reset Password?"
    icon="mdi-lock-reset"
    confirm-label="Send Reset Email"
    :loading="resetPasswordLoading"
    @confirm="$emit('confirm-reset-password', currentUser?.email)"
    @cancel="showResetPasswordConfirm = false"
  >
    <p class="text-body-large mb-2">
      Send a password reset email to
      <strong>{{ currentUser?.email || 'your account' }}</strong
      >?
    </p>
    <p class="text-body-medium text-muted-a11y">
      You'll receive a link to choose a new password. Your current password will keep working
      until you complete the reset.
    </p>
  </BaseDialog>

</template>

<script setup>
import { ref, computed } from 'vue'
import RoleBadge from '@/components/common/RoleBadge.vue'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { getLicenseCopy } from '@/i18n/licenseCopy'
import { isCeModeValue, isNonCeModeValue, isSaasModeValue } from '@/composables/useGiljoMode'
import { PRODUCT_NAME } from '@/branding'

const props = defineProps({
  currentUser: {
    type: Object,
    default: null,
  },
  userInitials: {
    type: String,
    default: '?',
  },
  giljoMode: {
    type: String,
    default: 'ce',
  },
  isAdmin: {
    type: Boolean,
    default: false,
  },
  orgName: {
    type: String,
    default: null,
  },
  orgRole: {
    type: String,
    default: null,
  },
  accountStatusBadgeComponent: {
    type: Object,
    default: null,
  },
  accountBadgeState: {
    type: String,
    default: 'none',
  },
  isAccountScheduledForDeletion: {
    type: Boolean,
    default: false,
  },
  accountBadgeStateModifier: {
    type: String,
    default: 'none',
  },
  accountStatusTitle: {
    type: String,
    default: '',
  },
  accountStatusSubtitle: {
    type: String,
    default: '',
  },
  cancellingDeletion: {
    type: Boolean,
    default: false,
  },
  versionLabel: {
    type: String,
    default: '',
  },
  licenseStatus: {
    type: String,
    default: 'Licensed',
  },
  serverVersion: {
    type: String,
    default: '',
  },
  resetPasswordLoading: {
    type: Boolean,
    default: false,
  },
})

defineEmits([
  'logout',
  'cancel-deletion',
  'upgrade',
  'confirm-reset-password',
])

const aboutDialog = ref(false)
const productName = PRODUCT_NAME
const showResetPasswordConfirm = ref(false)

const isCeEdition = computed(() => isCeModeValue(props.giljoMode))
const isNonCeEdition = computed(() => isNonCeModeValue(props.giljoMode))

const aboutEditionLabel = computed(() => getLicenseCopy(props.giljoMode).editionLabel)
const aboutLongDescription = computed(() => getLicenseCopy(props.giljoMode).longDescription)
const aboutLicenseLabel = computed(() => {
  if (isSaasModeValue(props.giljoMode)) return 'Subscribed'
  return props.licenseStatus
})

function getRoleColor(role) {
  if (!role) return 'grey'
  const r = role.toLowerCase()
  if (r === 'admin') return 'error'
  if (r === 'developer' || r === 'dev') return 'primary'
  if (r === 'viewer') return 'success'
  return 'grey'
}
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

/* ─── ORBS: unified round icons ─── */
.nav-orb {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all $transition-normal ease;
  // positioning context for the absolute-anchored AccountStatusBadge.
  position: relative;
}

.nav-orb:hover {
  transform: scale(1.08);
}

.nav-orb:active {
  transform: scale(0.95);
}

// Avatar: brand yellow background, dark initials
.nav-orb--avatar {
  background: rgba($color-brand-yellow, 0.15);
  color: $color-brand-yellow;

  &:hover {
    background: rgba($color-brand-yellow, 0.25);
  }
}

.nav-orb-initials {
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}

// account status section at top of the avatar dropdown.
.account-status-section {
  flex-direction: column;
  align-items: flex-start;
  padding: 12px 16px;

  &--danger {
    background: rgba(var(--v-theme-error), 0.08);
  }

  &--expired {
    background: rgba(255, 152, 0, 0.1);
  }

  &--ending-soon {
    background: rgba($color-brand-yellow, 0.1);
  }

  &__title {
    font-weight: 600;
    font-size: 0.85rem;
    line-height: 1.2;
    white-space: normal;
  }

  &__subtitle {
    color: var(--text-secondary);
    font-size: 0.75rem;
    line-height: 1.35;
    margin-top: 2px;
    white-space: normal;
    opacity: 1;
  }

  &__actions {
    display: flex;
    width: 100%;
  }
}

.about-link {
  color: $color-brand-yellow;
}
</style>
