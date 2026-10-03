import { computed, ref } from 'vue'
import { getAgentColor as getAgentColorConfig } from '@/config/agentColors'

export function useTemplateEditDialog(editingTemplate, resetEditingTemplate) {
  const editDialog = ref(false)

  const originalSnapshot = ref(null)
  const TRACKED_FIELDS = [
    'role',
    'custom_suffix',
    'description',
    'user_instructions',
    'model',
    'tools',
    'cli_tool',
  ]

  const hasChanges = computed(() => {
    if (!originalSnapshot.value) {
      return !!editingTemplate.value.role
    }
    return TRACKED_FIELDS.some(
      (f) => (editingTemplate.value[f] ?? '') !== (originalSnapshot.value[f] ?? ''),
    )
  })

  const withDefaults = (template, customSuffix) => ({
    ...template,
    user_instructions: template.user_instructions || '',
    cli_tool: template.cli_tool || 'claude',
    custom_suffix: customSuffix,
    background_color: template.background_color || '',
    model: template.model || 'sonnet',
    tools: template.tools || null,
  })

  const openCreateDialog = () => {
    resetEditingTemplate()
    originalSnapshot.value = null
    editDialog.value = true
  }

  const editTemplate = (template) => {
    const role = template.role || ''
    const name = template.name || ''
    const extractedSuffix = name.startsWith(`${role}-`) ? name.slice(role.length + 1) : ''

    const normalized = withDefaults(template, extractedSuffix)
    editingTemplate.value = { ...normalized }
    originalSnapshot.value = { ...normalized }
    editDialog.value = true
  }

  const duplicateTemplate = (template) => {
    editingTemplate.value = { ...withDefaults(template, 'copy'), id: null, is_default: false }
    originalSnapshot.value = null
    editDialog.value = true
  }

  const closeEditDialog = () => {
    editDialog.value = false
    originalSnapshot.value = null
    resetEditingTemplate()
  }

  const onRoleChange = (newRole) => {
    editingTemplate.value.role = newRole
    editingTemplate.value.background_color = getAgentColorConfig(newRole).hex
  }

  const onUpdateTemplate = (updated) => {
    editingTemplate.value = { ...editingTemplate.value, ...updated }
  }

  return {
    editDialog,
    originalSnapshot,
    TRACKED_FIELDS,
    hasChanges,
    openCreateDialog,
    editTemplate,
    duplicateTemplate,
    closeEditDialog,
    onRoleChange,
    onUpdateTemplate,
  }
}
