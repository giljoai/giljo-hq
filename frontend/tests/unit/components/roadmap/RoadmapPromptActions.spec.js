/**
 * RoadmapPromptActions.vue + RoadmapPromptDialog.vue — FE-9617
 *
 * The roadmap toolbar is one split control: a loud Create/Refresh button that
 * copies the generated prompt, and a caret menu with exactly two items — copy,
 * or edit-then-copy. The edit dialog opens pre-filled and its Copy travels the
 * SAME copy path as the primary click (one `copy` emit, one clipboard writer
 * in the parent view), carrying the edited text.
 *
 * Edition Scope: Both
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import RoadmapPromptActions from '@/components/roadmap/RoadmapPromptActions.vue'
import RoadmapPromptDialog from '@/components/roadmap/RoadmapPromptDialog.vue'

const stubs = {
  'v-btn': { template: '<button><slot /></button>' },
  'v-icon': { template: '<i><slot /></i>' },
  'v-menu': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
  'v-list': { template: '<div><slot /></div>' },
  'v-list-item': {
    props: ['title'],
    template: '<div class="v-list-item" @click="$emit(\'click\')">{{ title }}<slot /></div>',
  },
}

const dialogStubs = {
  ...stubs,
  'v-textarea': {
    props: ['modelValue'],
    template:
      '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  BaseDialog: {
    props: ['modelValue', 'title', 'confirmLabel'],
    template:
      '<div class="base-dialog"><span class="dlg-title">{{ title }}</span><slot />' +
      '<button class="dlg-confirm" @click="$emit(\'confirm\')">{{ confirmLabel }}</button></div>',
  },
}

function mountActions(props = {}) {
  return mount(RoadmapPromptActions, {
    props: { isEmpty: false, promptText: 'GENERATED PROMPT', ...props },
    global: { stubs: dialogStubs },
  })
}

describe('RoadmapPromptActions.vue — the split copy button', () => {
  it('reads "Create Roadmap" on an empty roadmap and "Refresh Roadmap" otherwise', () => {
    expect(mountActions({ isEmpty: true }).get('[data-testid="roadmap-copy-prompt"]').text()).toBe(
      'Create Roadmap'
    )
    expect(mountActions({ isEmpty: false }).get('[data-testid="roadmap-copy-prompt"]').text()).toBe(
      'Refresh Roadmap'
    )
  })

  it('the primary click emits copy with NO edited text', async () => {
    const w = mountActions()
    await w.get('[data-testid="roadmap-copy-prompt"]').trigger('click')
    expect(w.emitted('copy')).toHaveLength(1)
    expect(w.emitted('copy')[0]).toEqual([undefined])
  })

  it('the caret exposes exactly two menu items: copy, and edit-then-copy', () => {
    const w = mountActions()
    expect(w.get('[data-testid="roadmap-prompt-menu"]').attributes('aria-label')).toBe(
      'More prompt options'
    )
    const items = w.findAll('.v-list-item')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toContain('Copy prompt')
    expect(items[1].text()).toContain('Edit prompt, then copy')
  })

  it('"Copy prompt" in the menu emits the same plain copy as the primary click', async () => {
    const w = mountActions()
    await w.get('[data-testid="roadmap-prompt-menu-copy"]').trigger('click')
    expect(w.emitted('copy')[0]).toEqual([undefined])
  })

  it('"Edit prompt, then copy" opens the dialog pre-filled with the generated prompt', async () => {
    const w = mountActions()
    expect(w.findComponent(RoadmapPromptDialog).props('modelValue')).toBe(false)
    await w.get('[data-testid="roadmap-prompt-menu-edit"]').trigger('click')
    expect(w.vm.dialogOpen).toBe(true)
    expect(w.get('[data-testid="roadmap-prompt-dialog-text"]').element.value).toBe(
      'GENERATED PROMPT'
    )
  })

  it('Copy from the dialog emits the EDITED text on the one copy channel, then closes', async () => {
    const w = mountActions()
    await w.get('[data-testid="roadmap-prompt-menu-edit"]').trigger('click')
    await w.get('[data-testid="roadmap-prompt-dialog-text"]').setValue('do the database first')
    await w.get('.dlg-confirm').trigger('click')
    expect(w.emitted('copy')[0]).toEqual(['do the database first'])
    expect(w.vm.dialogOpen).toBe(false)
  })
})

describe('RoadmapPromptDialog.vue', () => {
  function mountDialog(props = {}) {
    return mount(RoadmapPromptDialog, {
      props: { modelValue: true, promptText: 'GENERATED PROMPT', ...props },
      global: { stubs: dialogStubs },
    })
  }

  it('is titled "Edit the roadmap prompt" and says the edits are used once', () => {
    const w = mountDialog()
    expect(w.get('.dlg-title').text()).toBe('Edit the roadmap prompt')
    expect(w.get('[data-testid="roadmap-prompt-dialog-note"]').text()).toBe(
      'Your edits are used once; they are not saved.'
    )
  })

  it('re-fills from the current prompt each time it opens, discarding the last edit', async () => {
    const w = mountDialog({ modelValue: false })
    await w.setProps({ modelValue: true })
    await w.get('[data-testid="roadmap-prompt-dialog-text"]').setValue('one-off edit')
    await w.setProps({ modelValue: false })
    await w.setProps({ modelValue: true, promptText: 'A FRESHER PROMPT' })
    expect(w.get('[data-testid="roadmap-prompt-dialog-text"]').element.value).toBe(
      'A FRESHER PROMPT'
    )
  })

  it('an in-flight edit SURVIVES the generated prompt changing under an open dialog', async () => {
    // A WS refetch can flip the roadmap from empty to non-empty while the
    // dialog is open, which swaps the parent's generated prompt from create to
    // refresh. The pre-fill belongs to OPENING the dialog; a prompt change
    // underneath must not wipe what the user has typed.
    const w = mountDialog({ promptText: 'CREATE PROMPT' })
    await w.get('[data-testid="roadmap-prompt-dialog-text"]').setValue('my one-off instructions')
    await w.setProps({ promptText: 'REFRESH PROMPT' })
    expect(w.get('[data-testid="roadmap-prompt-dialog-text"]').element.value).toBe(
      'my one-off instructions'
    )
  })

  it('Copy emits the edited text and closes the dialog', async () => {
    const w = mountDialog()
    await w.get('[data-testid="roadmap-prompt-dialog-text"]').setValue('ship the toolbar')
    await w.get('.dlg-confirm').trigger('click')
    expect(w.emitted('copy')[0]).toEqual(['ship the toolbar'])
    expect(w.emitted('update:modelValue').at(-1)).toEqual([false])
  })
})
