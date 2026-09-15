<template>
  <v-list>
    <v-list-item v-for="member in members" :key="member.id">
      <template #prepend>
        <v-avatar color="primary" size="40">
          <span class="text-uppercase">{{ getInitials(member) }}</span>
        </v-avatar>
      </template>

      <v-list-item-title>
        {{ getMemberDisplayName(member) }}
      </v-list-item-title>

      <v-list-item-subtitle>
        <v-chip :color="roleColor(member.role)" size="small" class="mr-2">
          {{ member.role }}
        </v-chip>
        <span class="text-body-small"> Joined {{ formatDate(member.joined_at) }} </span>
      </v-list-item-subtitle>

      <template #append>
        <v-menu v-if="canManage && member.role !== 'owner'">
          <template #activator="{ props }">
            <v-btn icon="mdi-dots-vertical" variant="text" v-bind="props" />
          </template>
          <v-list>
            <v-list-item
              v-for="role in availableRoles"
              :key="role"
              :disabled="member.role === role"
              @click="$emit('change-role', { userId: member.user_id, newRole: role })"
            >
              <v-list-item-title>Make {{ role }}</v-list-item-title>
            </v-list-item>
            <v-divider />
            <v-list-item class="text-error" @click="$emit('remove', member.user_id)">
              <v-list-item-title>Remove from org</v-list-item-title>
            </v-list-item>
          </v-list>
        </v-menu>

        <v-btn
          v-if="isOwner && member.role === 'admin'"
          color="warning"
          variant="text"
          size="small"
          @click="$emit('transfer', member.user_id)"
        >
          Transfer Ownership
        </v-btn>
      </template>
    </v-list-item>

    <v-list-item v-if="!members.length">
      <v-list-item-title class="text-center text-grey"> No members </v-list-item-title>
    </v-list-item>
  </v-list>
</template>

<script setup>
import { useFormatDate } from '@/composables/useFormatDate'

const { formatDate } = useFormatDate()


defineProps({
  members: { type: Array, required: true },
  canManage: { type: Boolean, default: false },
  isOwner: { type: Boolean, default: false },
})

defineEmits(['change-role', 'remove', 'transfer'])

const availableRoles = ['admin', 'member', 'viewer']

function roleColor(role) {
  const colors = {
    owner: 'purple',
    admin: 'blue',
    member: 'green',
    viewer: 'grey',
  }
  return colors[role] || 'grey'
}


function getInitials(member) {
  if (member.username) {
    return member.username.slice(0, 2).toUpperCase()
  }
  if (member.email) {
    return member.email.slice(0, 2).toUpperCase()
  }
  return member.user_id ? member.user_id.slice(0, 2).toUpperCase() : '??'
}

function getMemberDisplayName(member) {
  if (member.username) return member.username
  if (member.email) return member.email
  return `User: ${member.user_id?.slice(0, 8) || 'Unknown'}...`
}
</script>
