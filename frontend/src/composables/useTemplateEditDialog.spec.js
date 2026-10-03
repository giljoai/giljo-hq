import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'
import { useTemplateEditDialog } from './useTemplateEditDialog'

function setup() {
  const editing = ref({})
  const dialog = useTemplateEditDialog(editing, vi.fn())
  return { editing, dialog }
}

const SPARSE = { id: 't1', name: 'implementer-backend', role: 'implementer', is_default: true }
const FULL = {
  id: 't2', name: 'tester', role: 'tester', is_default: false, user_instructions: 'u', cli_tool: 'codex',
  background_color: '#123456', model: 'opus', tools: ['a'],
}

describe('useTemplateEditDialog defaults', () => {
  it.each([
    ['sparse', SPARSE, { user_instructions: '', cli_tool: 'claude', custom_suffix: 'backend', background_color: '', model: 'sonnet', tools: null }],
    ['full', FULL, { user_instructions: 'u', cli_tool: 'codex', custom_suffix: '', background_color: '#123456', model: 'opus', tools: ['a'] }],
  ])('editTemplate fills the %s template and snapshots it', (_n, tpl, filled) => {
    const { editing, dialog } = setup()
    dialog.editTemplate(tpl)
    expect(editing.value).toEqual({ ...tpl, ...filled })
    expect(dialog.originalSnapshot.value).toEqual({ ...tpl, ...filled })
    expect(dialog.editDialog.value).toBe(true)
  })

  it.each([
    ['sparse', SPARSE, { user_instructions: '', cli_tool: 'claude', background_color: '', model: 'sonnet', tools: null }],
    ['full', FULL, { user_instructions: 'u', cli_tool: 'codex', background_color: '#123456', model: 'opus', tools: ['a'] }],
  ])('duplicateTemplate copies the %s template as a new "-copy" with no snapshot', (_n, tpl, filled) => {
    const { editing, dialog } = setup()
    dialog.duplicateTemplate(tpl)
    expect(editing.value).toEqual({ ...tpl, ...filled, id: null, is_default: false, custom_suffix: 'copy' })
    expect(dialog.originalSnapshot.value).toBeNull()
    expect(dialog.editDialog.value).toBe(true)
  })
})
