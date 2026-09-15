<template>
  <v-dialog v-model="dialogModel" max-width="500" persistent scrollable>
    <v-card v-draggable class="smooth-border">
      <div class="dlg-header">
        <v-icon class="dlg-icon" icon="mdi-account-plus" />
        <span class="dlg-title">Invite Member</span>
        <v-btn icon variant="text" size="small" class="dlg-close" @click="dialogModel = false">
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <v-divider />

      <v-card-text class="pa-4">
        <v-text-field
          v-model="userId"
          label="User ID"
          placeholder="Enter user ID to invite"
          :error-messages="error"
          data-test="invite-user-id"
        />
        <v-select v-model="role" :items="roles" label="Role" variant="outlined" density="compact" data-test="invite-role" />
      </v-card-text>

      <v-divider />

      <div class="dlg-footer">
        <v-spacer />
        <v-btn variant="text" data-test="invite-cancel" @click="dialogModel = false">Cancel</v-btn>
        <v-btn
          color="primary"
          variant="flat"
          :loading="loading"
          :disabled="!userId"
          data-test="invite-submit"
          @click="invite"
        >
          Invite
        </v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useOrgStore } from '@/stores/orgStore'

const props = defineProps({
  orgId: { type: String, required: true },
  modelValue: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'invited'])

const orgStore = useOrgStore()
const userId = ref('')
const role = ref('member')
const loading = ref(false)
const error = ref('')

const dialogModel = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const roles = [
  { title: 'Admin', value: 'admin' },
  { title: 'Member', value: 'member' },
  { title: 'Viewer', value: 'viewer' },
]

async function invite() {
  if (!userId.value) return

  loading.value = true
  error.value = ''

  const result = await orgStore.inviteMember(props.orgId, userId.value, role.value)

  loading.value = false

  if (result.success) {
    emit('invited', result.data)
    userId.value = ''
    role.value = 'member'
    dialogModel.value = false
  } else {
    error.value = result.error
  }
}
</script>
