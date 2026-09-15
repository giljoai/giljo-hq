<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <h1 class="text-headline-large mb-4">Organization Settings</h1>
      </v-col>
    </v-row>

    <v-row v-if="loading">
      <v-col cols="12" class="text-center">
        <v-progress-circular indeterminate />
      </v-col>
    </v-row>

    <template v-else-if="currentOrg">
      <v-row>
        <v-col cols="12" md="6">
          <div class="tab-header mb-4">
            <h2 class="text-title-large">Organization Details</h2>
          </div>
          <v-card variant="flat" class="smooth-border org-card">
            <v-card-text>
              <v-text-field
                v-model="orgForm.name"
                label="Organization Name"
                :disabled="!isAdmin"
                data-test="org-name"
              />
              <v-text-field
                v-model="currentOrg.slug"
                label="Slug (URL-friendly)"
                disabled
                hint="Cannot be changed after creation"
                data-test="org-slug"
              />
              <v-btn
                v-if="isAdmin"
                color="primary"
                :loading="saving"
                data-test="save-org-btn"
                @click="saveOrgDetails"
              >
                Save Changes
              </v-btn>
            </v-card-text>
          </v-card>
        </v-col>

        <v-col cols="12" md="6">
          <div class="tab-header mb-4 d-flex align-center">
            <h2 class="text-title-large">Members</h2>
            <v-spacer />
            <v-btn
              v-if="canManageMembers"
              color="primary"
              size="small"
              data-test="invite-btn"
              @click="showInviteDialog = true"
            >
              <v-icon start>mdi-account-plus</v-icon>
              Invite
            </v-btn>
          </div>
          <v-card variant="flat" class="smooth-border org-card">
            <v-card-text>
              <MemberList
                :members="members"
                :can-manage="canManageMembers"
                :is-owner="isOwner"
                @change-role="handleRoleChange"
                @remove="handleRemoveMember"
                @transfer="handleTransferOwnership"
              />
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <v-row v-if="isOwner">
        <v-col cols="12">
          <div class="tab-header mb-4">
            <h2 class="text-title-large text-error">Danger Zone</h2>
          </div>
          <v-card variant="flat" class="smooth-border org-card" style="--smooth-border-color: rgba(224, 120, 114, 0.3)">
            <v-card-text>
              <v-btn
                color="error"
                variant="outlined"
                data-test="delete-org-btn"
                @click="showDeleteDialog = true"
              >
                Delete Organization
              </v-btn>
              <p class="text-body-small mt-2">
                This will permanently delete the organization and all its data.
              </p>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
    </template>

    <v-alert v-else type="error" data-test="org-not-found">
      Organization not found or you don't have access.
    </v-alert>

    <InviteMemberDialog
      v-if="currentOrg"
      v-model="showInviteDialog"
      :org-id="currentOrg.id"
      @invited="handleMemberInvited"
    />

    <v-dialog v-model="showDeleteDialog" max-width="400">
      <v-card v-draggable class="smooth-border">
        <div class="dlg-header dlg-header--danger">
          <v-icon class="dlg-icon">mdi-delete</v-icon>
          <span class="dlg-title">Delete Organization?</span>
          <v-btn icon variant="text" class="dlg-close" @click="showDeleteDialog = false">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </div>
        <v-card-text>
          Are you sure you want to delete <strong>{{ currentOrg?.name }}</strong
          >? This action cannot be undone.
        </v-card-text>
        <div class="dlg-footer">
          <v-spacer />
          <v-btn variant="text" data-test="delete-cancel" @click="showDeleteDialog = false">Cancel</v-btn>
          <v-btn color="error" variant="flat" data-test="delete-confirm" @click="deleteOrg">Delete</v-btn>
        </div>
      </v-card>
    </v-dialog>

  </v-container>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useOrgStore } from '@/stores/orgStore'
import { useToast } from '@/composables/useToast'
import MemberList from '@/components/org/MemberList.vue'
import InviteMemberDialog from '@/components/org/InviteMemberDialog.vue'

const route = useRoute()
const router = useRouter()
const orgStore = useOrgStore()
const { showToast } = useToast()

const orgForm = ref({ name: '' })
const saving = ref(false)
const showInviteDialog = ref(false)
const showDeleteDialog = ref(false)

const loading = computed(() => orgStore.loading)
const currentOrg = computed(() => orgStore.currentOrg)
const members = computed(() => orgStore.members)
const isOwner = computed(() => orgStore.isOwner)
const isAdmin = computed(() => orgStore.isAdmin)
const canManageMembers = computed(() => orgStore.canManageMembers)

function showNotification(message, type = 'success') {
  showToast({ message, type })
}

async function loadOrg(orgId) {
  if (!orgId) return
  await orgStore.fetchOrganization(orgId)
  if (currentOrg.value) {
    orgForm.value.name = currentOrg.value.name
  }
}

onMounted(() => {
  loadOrg(route.params.orgId)
})

watch(
  () => route.params.orgId,
  (newOrgId) => {
    if (newOrgId) loadOrg(newOrgId)
  },
)

watch(currentOrg, (newOrg) => {
  if (newOrg) {
    orgForm.value.name = newOrg.name
  }
})

async function saveOrgDetails() {
  saving.value = true
  const result = await orgStore.updateOrganization(currentOrg.value.id, {
    name: orgForm.value.name,
  })
  saving.value = false

  if (result.success) {
    showNotification('Organization updated successfully')
  } else {
    showNotification(result.error || 'Failed to update organization', 'error')
  }
}

async function handleRoleChange({ userId, newRole }) {
  const result = await orgStore.changeMemberRole(currentOrg.value.id, userId, newRole)
  if (result.success) {
    showNotification('Member role updated')
  } else {
    showNotification(result.error || 'Failed to update role', 'error')
  }
}

async function handleRemoveMember(userId) {
  const result = await orgStore.removeMember(currentOrg.value.id, userId)
  if (result.success) {
    showNotification('Member removed')
  } else {
    showNotification(result.error || 'Failed to remove member', 'error')
  }
}

async function handleTransferOwnership(newOwnerId) {
  const result = await orgStore.transferOwnership(currentOrg.value.id, newOwnerId)
  if (result.success) {
    showNotification('Ownership transferred successfully')
  } else {
    showNotification(result.error || 'Failed to transfer ownership', 'error')
  }
}

function handleMemberInvited(member) {
  showNotification(`Member ${member.user_id.slice(0, 8)}... invited successfully`)
  showInviteDialog.value = false
}

async function deleteOrg() {
  const result = await orgStore.deleteOrganization(currentOrg.value.id)
  if (result.success) {
    showNotification('Organization deleted')
    router.push('/Dashboard')
  } else {
    showNotification(result.error || 'Failed to delete organization', 'error')
  }
  showDeleteDialog.value = false
}
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
.org-card {
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
}
</style>
