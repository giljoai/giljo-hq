import { computed, ref } from 'vue'
import { getAgentColor as getAgentColorConfig } from '@/config/agentColors'

/**
 * BE-9394 — the agent edit/create dialog's state machine.
 *
 * Owns one concern end to end: what the dialog is currently editing, what it looked
 * like when it opened, and therefore whether anything has actually changed. Opening
 * (create / edit / duplicate), closing, and the two field-update handlers all belong
 * to that same question, so they live together rather than beside the list, the
 * filters and the export machinery in `TemplateManager.vue`.
 *
 * Extracted for the reason `useProductAgentAssignments` was extracted from the same
 * component: `TemplateManager.vue` sat at exactly 800 lines against the flat
 * `ci_guardrails.sh` cap, which — unlike a `size_budgets.txt` entry — carries no
 * tolerance band at all, so the next added line failed CI outright. A budget entry
 * would have been a raise, which is what that mechanism exists to refuse.
 *
 * `originalSnapshot` is the load-bearing piece and the reason this is a state machine
 * rather than a bag of handlers: it is captured once on open and diffed against, which
 * is what tells an ordinary edit apart from a deliberate change to a specific field.
 * It is deliberately null in create and duplicate mode — there is no prior state to
 * compare against, and callers rely on that distinction.
 *
 * Edition scope: CE
 */
export function useTemplateEditDialog(editingTemplate, resetEditingTemplate) {
  const editDialog = ref(false)

  // Dirty tracking: snapshot original state on dialog open
  const originalSnapshot = ref(null)
  const TRACKED_FIELDS = [
    'role',
    'custom_suffix',
    'description',
    'user_instructions',
    'model',
    'tools',
    'cli_tool',
    // BE-9394: the retire switch is a real edit, so moving it alone must enable Save
    // (the dialog's Save is :disabled="!hasChanges"). Safe to diff as a boolean here --
    // both sides are seeded from the same normalized object on open, so an untouched
    // control compares equal rather than reading as dirty.
    'is_active',
  ]

  const hasChanges = computed(() => {
    if (!originalSnapshot.value) {
      // Create mode: require at least a role
      return !!editingTemplate.value.role
    }
    return TRACKED_FIELDS.some(
      (f) => (editingTemplate.value[f] ?? '') !== (originalSnapshot.value[f] ?? ''),
    )
  })

  /**
   * BE-9394 — did the user actually move the tenant-wide retire switch?
   *
   * The update payload carries `is_active` ONLY when this is true, and that
   * conditional is the whole safety property of the two-flag model:
   *
   * - An ordinary edit (rename, reword, change the model) leaves the tenant flag
   *   out of the request entirely, so saving any change to a deliberately retired
   *   agent cannot silently un-retire it. That is the boundary BE-9391's guard was
   *   written to hold, preserved rather than weakened.
   * - It also closes a lost-update window an unconditional send would open:
   *   `editingTemplate` is a COPY taken when the dialog opened, while WebSocket
   *   updates keep patching the live row underneath it. Always sending would write
   *   a stale flag back over a concurrent change.
   *
   * Compared as booleans on purpose -- `undefined` and `false` both mean retired,
   * and treating them as different would make an untouched control look moved.
   */
  const retireChanged = computed(
    () =>
      !!originalSnapshot.value &&
      !!editingTemplate.value.is_active !== !!originalSnapshot.value.is_active,
  )

  const openCreateDialog = () => {
    resetEditingTemplate()
    originalSnapshot.value = null
    editDialog.value = true
  }

  const editTemplate = (template) => {
    // Extract suffix from name: "implementer-backend" with role "implementer" → suffix "backend"
    const role = template.role || ''
    const name = template.name || ''
    const extractedSuffix = name.startsWith(`${role}-`) ? name.slice(role.length + 1) : ''

    const normalized = {
      ...template,
      user_instructions: template.user_instructions || '',
      cli_tool: template.cli_tool || 'claude',
      custom_suffix: extractedSuffix,
      background_color: template.background_color || '',
      model: template.model || 'sonnet',
      tools: template.tools || null,
    }
    editingTemplate.value = { ...normalized }
    originalSnapshot.value = { ...normalized }
    editDialog.value = true
  }

  const duplicateTemplate = (template) => {
    editingTemplate.value = {
      ...template,
      id: null,
      is_default: false, // FE-9386: a copy is never the role default
      // BE-9394: a copy is named by the SERVER, from role + suffix, not by free text.
      // This used to set `name: "<name> (Copy)"` with an empty suffix -- but the server
      // regenerates the name from slugify_name(role, custom_suffix) and consults the
      // supplied `name` only when role is falsy, which it never is here. So "(Copy)"
      // was silently discarded and the copy landed as "<role>-2". A name here is an
      // identity surface, not a label: it is what the exported filename, the harness
      // frontmatter, and get_template_by_name (which spawn resolves against) all use,
      // so the name the user is shown must be the string the server actually derives.
      // Supplying the suffix instead makes all of them agree on "<role>-copy".
      user_instructions: template.user_instructions || '',
      cli_tool: template.cli_tool || 'claude',
      custom_suffix: 'copy',
      background_color: template.background_color || '',
      model: template.model || 'sonnet',
      tools: template.tools || null,
    }
    originalSnapshot.value = null
    editDialog.value = true
  }

  const closeEditDialog = () => {
    editDialog.value = false
    originalSnapshot.value = null
    resetEditingTemplate()
  }

  // Handover 0103: Handle role change (auto-set background_color + write role back to editingTemplate)
  // Called by TemplateEditDialog @role-change. Must mutate in-place so downstream
  // spread in onUpdateTemplate does not clobber the role assignment.
  const onRoleChange = (newRole) => {
    editingTemplate.value.role = newRole
    editingTemplate.value.background_color = getAgentColorConfig(newRole).hex
  }

  // Handle field updates emitted by TemplateEditDialog via @update:template.
  // Merges the spread update into editingTemplate while preserving any concurrent mutations.
  const onUpdateTemplate = (updated) => {
    editingTemplate.value = { ...editingTemplate.value, ...updated }
  }

  return {
    editDialog,
    originalSnapshot,
    TRACKED_FIELDS,
    hasChanges,
    retireChanged,
    openCreateDialog,
    editTemplate,
    duplicateTemplate,
    closeEditDialog,
    onRoleChange,
    onUpdateTemplate,
  }
}
