import { ref, computed } from 'vue'
import api from '@/services/api'
import { templateRowActive } from '@/components/templates/templateTableConfig'

const ORCHESTRATOR_ROW = Object.freeze({
  id: '__orchestrator__',
  name: 'orchestrator',
  role: 'orchestrator',
  is_active: true,
  updated_at: null,
  _system: true,
})

const DEFAULT_EDITING_TEMPLATE = () => ({
  id: null,
  name: '',
  role: '',
  cli_tool: 'claude',
  custom_suffix: '',
  background_color: '',
  description: '',
  user_instructions: '',
  model: 'sonnet',
  tools: null,
})

export function useTemplateData(search, filterRole, filterStatus, productId, showAllProducts) {
  const templates = ref([])
  const loading = ref(false)
  const activeStats = ref({
    totalActive: null,
    totalCapacity: null,
    userActive: 0,
    userLimit: 15,
    remainingUserSlots: 15,
    systemReserved: 1,
  })
  const previewContent = ref('')

  const editingTemplate = ref(DEFAULT_EDITING_TEMPLATE())

  const orchestratorRow = ORCHESTRATOR_ROW

  const filteredTemplates = computed(() => {
    let filtered = templates.value

    if (filterRole.value) {
      filtered = filtered.filter((t) => t.role === filterRole.value)
    }

    if (filterStatus.value) {
      filtered = filtered.filter((t) =>
        filterStatus.value === 'active' ? templateRowActive(t) : !templateRowActive(t),
      )
    }

    if (!filterRole.value && !filterStatus.value) {
      return [orchestratorRow, ...filtered]
    }
    return filtered
  })

  const availableRoles = computed(() =>
    [...new Set(templates.value.map((t) => t.role).filter(Boolean))].sort(),
  )

  const generatedName = computed(() => {
    const role = editingTemplate.value.role
    const suffix = editingTemplate.value.custom_suffix
    if (!role) return ''
    if (!suffix) return role
    const cleanSuffix = suffix
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, '')
      .replace(/\s+/g, '-')
    return `${role}-${cleanSuffix}`
  })

  const totalActiveAgents = computed(() => activeStats.value.totalActive)

  const totalCapacity = computed(() => {
    if (activeStats.value.totalCapacity !== null) {
      return activeStats.value.totalCapacity
    }
    return (activeStats.value.userLimit || 15) + (activeStats.value.systemReserved || 1)
  })

  const remainingUserSlots = computed(() => {
    if (typeof activeStats.value.remainingUserSlots === 'number') {
      return Math.max(0, activeStats.value.remainingUserSlots)
    }
    return Math.max(0, (activeStats.value.userLimit || 15) - (activeStats.value.userActive || 0))
  })

  const userAgentLimit = computed(() => activeStats.value.userLimit ?? 15)

  const loadTemplates = async () => {
    const scope = productId?.value || null
    if (!scope && !showAllProducts?.value) {
      templates.value = []
      return
    }
    loading.value = true
    try {
      const response = await api.templates.list(showAllProducts?.value ? null : scope)
      templates.value = (response.data || []).filter((t) => !t.is_system_role)
    } catch (error) {
      console.error('Failed to load templates:', error)
    } finally {
      loading.value = false
    }
  }

  const loadActiveCount = async () => {
    const scope = productId?.value || null
    if (!scope) return
    try {
      const response = await api.templates.activeCount(scope)
      const data = response.data || {}
      const userActive = data.active_count ?? 0
      const userLimit = data.limit ?? 15
      const systemReserved = 1
      activeStats.value = {
        totalActive: userActive + systemReserved,
        totalCapacity: userLimit + systemReserved,
        userActive,
        userLimit,
        remainingUserSlots: Math.max(0, userLimit - userActive),
        systemReserved,
      }
    } catch (error) {
      console.error('[TEMPLATE MANAGER] Failed to load active count:', error)
      activeStats.value = {
        ...activeStats.value,
        totalActive: activeStats.value.totalActive ?? activeStats.value.systemReserved,
      }
    }
  }

  const resetEditingTemplate = () => {
    editingTemplate.value = DEFAULT_EDITING_TEMPLATE()
  }

  const importingDefaults = ref(false)
  const importDefaults = async () => {
    const scope = productId?.value || null
    if (!scope) throw new Error('Select a product tab before adding agents to it.')
    importingDefaults.value = true
    try {
      const response = await api.templates.importDefaults(scope)
      await loadTemplates()
      await loadActiveCount()
      return response.data
    } finally {
      importingDefaults.value = false
    }
  }

  return {
    templates,
    loading,
    activeStats,
    previewContent,
    editingTemplate,
    orchestratorRow,
    filteredTemplates,
    availableRoles,
    generatedName,
    totalActiveAgents,
    totalCapacity,
    remainingUserSlots,
    userAgentLimit,
    loadTemplates,
    loadActiveCount,
    resetEditingTemplate,
    importingDefaults,
    importDefaults,
  }
}
