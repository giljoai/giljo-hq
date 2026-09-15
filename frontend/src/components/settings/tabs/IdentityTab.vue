<template>
  <div>
    <div class="tab-header mb-4">
      <h2 class="text-title-large">Identity</h2>
      <p class="text-body-medium text-muted-a11y mt-1">Workspace and user management</p>
    </div>
    <v-card variant="flat" class="smooth-border identity-card" data-test="workspace-card">
    <v-card-text>
      <div v-if="loading" class="d-flex justify-center py-8">
        <v-progress-circular indeterminate color="primary" />
      </div>

      <v-alert v-else-if="error" type="error" class="mb-4" data-test="error-alert">
        {{ error }}
      </v-alert>

      <template v-else-if="currentOrg">
        <h3 class="text-title-large mb-3">Workspace Details</h3>

        <v-text-field
          v-model="orgForm.name"
          label="Workspace Name"
          variant="outlined"
          :disabled="!isAdmin || saving"
          placeholder="Enter workspace name"
          hint="The name of your workspace"
          persistent-hint
          data-test="org-name-field"
          class="mb-4"
        />

        <v-text-field
          :model-value="currentOrg.slug"
          label="Slug (URL-friendly)"
          variant="outlined"
          disabled
          placeholder="url-slug"
          hint="Cannot be changed after creation"
          persistent-hint
          data-test="org-slug-field"
        />

        <v-divider class="my-6" />

        <h3 class="text-title-large mb-3" data-test="users-card">Users</h3>

        <UserManager />
      </template>

      <v-alert v-else type="warning" data-test="no-org-alert">
        No organization found. Please contact your administrator.
      </v-alert>
    </v-card-text>

    <v-card-actions v-if="isAdmin && currentOrg && !loading">
      <v-spacer />
      <v-btn variant="text" data-test="reset-btn" @click="resetForm">
        Reset
      </v-btn>
      <v-btn
        color="primary"
        :loading="saving"
        :disabled="!isFormDirty"
        data-test="save-org-btn"
        @click="saveOrgDetails"
      >
        <v-icon start>mdi-content-save</v-icon>
        Save Changes
      </v-btn>
    </v-card-actions>
  </v-card>
  </div>

</template>

<script setup>

import { ref, computed, onMounted, watch } from 'vue'
import { useOrgStore } from '@/stores/orgStore'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import UserManager from '@/components/UserManager.vue'

const orgStore = useOrgStore()
const userStore = useUserStore()
const { showToast } = useToast()

const orgForm = ref({ name: '' })
const saving = ref(false)

const loading = computed(() => orgStore.loading)
const error = computed(() => orgStore.error)
const currentOrg = computed(() => orgStore.currentOrg)
const isAdmin = computed(() => orgStore.isAdmin)

const isFormDirty = computed(() => {
  return orgForm.value.name !== (currentOrg.value?.name || '')
})

function showNotification(message, type = 'success') {
  showToast({ message, type })
}

onMounted(async () => {
  const orgId = userStore.currentUser?.org_id
  if (orgId) {
    await orgStore.fetchOrganization(orgId)
    if (currentOrg.value) {
      orgForm.value.name = currentOrg.value.name
    }
  }
})

watch(currentOrg, (newOrg) => {
  if (newOrg) {
    orgForm.value.name = newOrg.name
  }
})

async function saveOrgDetails() {
  if (!currentOrg.value || !isFormDirty.value) return

  saving.value = true

  const result = await orgStore.updateOrganization(currentOrg.value.id, {
    name: orgForm.value.name,
  })

  saving.value = false

  if (result.success) {
    showNotification('Workspace updated successfully')
  } else {
    showNotification(result.error || 'Failed to update workspace', 'error')
  }
}

function resetForm() {
  if (currentOrg.value) {
    orgForm.value.name = currentOrg.value.name
  }
}
</script>

<style lang="scss" scoped>
@use '../../../styles/settings-tab-card' as settingsCard;
.identity-card {
  @include settingsCard.settings-tab-card-surface;
}
</style>
