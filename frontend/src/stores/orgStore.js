import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'
import { useUserStore } from './user'
import { parseErrorResponse } from '@/utils/errorMessages'

export const useOrgStore = defineStore('org', () => {
  const organizations = ref([])
  const currentOrg = ref(null)
  const members = ref([])
  const loading = ref(false)
  const error = ref(null)

  const userRole = computed(() => {
    if (!currentOrg.value || !members.value.length) return null
    const userStore = useUserStore()
    const userId = userStore.currentUser?.id
    if (!userId) return null
    const membership = members.value.find((m) => m.user_id === userId)
    return membership?.role || null
  })

  const isOwner = computed(() => {
    return userRole.value === 'owner'
  })

  const isAdmin = computed(() => {
    return ['owner', 'admin'].includes(userRole.value)
  })

  const canManageMembers = computed(() => {
    return ['owner', 'admin'].includes(userRole.value)
  })

  async function fetchOrganizations() {
    loading.value = true
    error.value = null
    try {
      const response = await api.organizations.list()
      organizations.value = response.data
      return { success: true, data: organizations.value }
    } catch (err) {
      error.value = err.message
      return { success: false, error: err.message }
    } finally {
      loading.value = false
    }
  }

  async function fetchOrganization(orgId) {
    loading.value = true
    error.value = null
    try {
      const response = await api.organizations.get(orgId)
      currentOrg.value = response.data
      members.value = response.data.members || []
      return { success: true, data: currentOrg.value }
    } catch (err) {
      if (err?.response?.status === 404) {
        currentOrg.value = null
        members.value = []
        error.value = null
        return { success: false, error: 'Workspace not found. It may have been deleted.' }
      }
      error.value = err.message
      return { success: false, error: err.message }
    } finally {
      loading.value = false
    }
  }

  async function createOrganization(orgData) {
    loading.value = true
    try {
      const response = await api.organizations.create(orgData)
      organizations.value.push(response.data)
      return { success: true, data: response.data }
    } catch (err) {
      return { success: false, error: parseErrorResponse(err).message }
    } finally {
      loading.value = false
    }
  }

  async function updateOrganization(orgId, orgData) {
    loading.value = true
    try {
      const response = await api.organizations.update(orgId, orgData)
      currentOrg.value = response.data
      const index = organizations.value.findIndex((o) => o.id === orgId)
      if (index >= 0) {
        organizations.value[index] = response.data
      }
      return { success: true, data: response.data }
    } catch (err) {
      return { success: false, error: parseErrorResponse(err).message }
    } finally {
      loading.value = false
    }
  }

  async function deleteOrganization(orgId) {
    loading.value = true
    try {
      await api.organizations.delete(orgId)
      organizations.value = organizations.value.filter((o) => o.id !== orgId)
      if (currentOrg.value?.id === orgId) {
        currentOrg.value = null
      }
      return { success: true }
    } catch (err) {
      return { success: false, error: parseErrorResponse(err).message }
    } finally {
      loading.value = false
    }
  }

  async function fetchMembers(orgId) {
    try {
      const response = await api.organizations.listMembers(orgId)
      members.value = response.data
      return { success: true, data: members.value }
    } catch (err) {
      return { success: false, error: err.message }
    }
  }

  async function inviteMember(orgId, userId, role) {
    try {
      const response = await api.organizations.inviteMember(orgId, {
        user_id: userId,
        role: role,
      })
      members.value.push(response.data)
      return { success: true, data: response.data }
    } catch (err) {
      return { success: false, error: parseErrorResponse(err).message }
    }
  }

  async function changeMemberRole(orgId, userId, newRole) {
    try {
      const response = await api.organizations.changeMemberRole(orgId, userId, { role: newRole })
      const index = members.value.findIndex((m) => m.user_id === userId)
      if (index >= 0) {
        members.value[index] = response.data
      }
      return { success: true, data: response.data }
    } catch (err) {
      return { success: false, error: parseErrorResponse(err).message }
    }
  }

  async function removeMember(orgId, userId) {
    try {
      await api.organizations.removeMember(orgId, userId)
      members.value = members.value.filter((m) => m.user_id !== userId)
      return { success: true }
    } catch (err) {
      return { success: false, error: parseErrorResponse(err).message }
    }
  }

  async function transferOwnership(orgId, newOwnerId) {
    try {
      await api.organizations.transferOwnership(orgId, {
        new_owner_id: newOwnerId,
      })
      await fetchMembers(orgId)
      return { success: true }
    } catch (err) {
      return { success: false, error: parseErrorResponse(err).message }
    }
  }

  function clearOrgData() {
    organizations.value = []
    currentOrg.value = null
    members.value = []
    error.value = null
  }

  return {
    organizations,
    currentOrg,
    members,
    loading,
    error,

    userRole,
    isOwner,
    isAdmin,
    canManageMembers,

    fetchOrganizations,
    fetchOrganization,
    createOrganization,
    updateOrganization,
    deleteOrganization,
    fetchMembers,
    inviteMember,
    changeMemberRole,
    removeMember,
    transferOwnership,
    clearOrgData,
  }
})
