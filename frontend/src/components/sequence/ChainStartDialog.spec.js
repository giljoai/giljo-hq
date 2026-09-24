import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const mockResolveRunOrder = vi.fn()
const mockStartSequence = vi.fn()

vi.mock('@/composables/useSequenceRunner', () => ({
  useSequenceRunner: () => ({
    creating: ref(false),
    resolveRunOrder: mockResolveRunOrder,
    startSequence: mockStartSequence,
  }),
}))

import ChainStartDialog from './ChainStartDialog.vue'

const BaseDialogStub = {
  name: 'BaseDialog',
  props: ['modelValue', 'title', 'confirmLabel'],
  emits: ['confirm', 'cancel', 'update:modelValue'],
  template: `<div v-if="modelValue" data-testid="dlg"><span class="dlg-title">{{ title }}</span><slot />
    <button data-testid="dlg-confirm" @click="$emit('confirm')">{{ confirmLabel }}</button>
    <button data-testid="dlg-cancel" @click="$emit('cancel')">Cancel</button></div>`,
}

const projects = [
  { id: 'p2', name: 'Second', taxonomy_alias: 'BE-0002' },
  { id: 'p1', name: 'First', taxonomy_alias: 'BE-0001' },
]
const ordered = [
  { project_id: 'p1', name: 'First', taxonomy_alias: 'BE-0001', locked: false },
  { project_id: 'p2', name: 'Second', taxonomy_alias: 'BE-0002', locked: false },
]

function mountDialog(props = {}) {
  return mount(ChainStartDialog, {
    props: { modelValue: true, projects, ...props },
    global: { stubs: { BaseDialog: BaseDialogStub, 'v-progress-linear': true } },
  })
}

describe('ChainStartDialog', () => {
  beforeEach(() => {
    mockResolveRunOrder.mockReset().mockResolvedValue(ordered)
    mockStartSequence.mockReset()
  })

  it('shows the resolved run order before anything is created', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    expect(mockResolveRunOrder).toHaveBeenCalledWith(projects)
    const items = wrapper.findAll('[data-testid="chain-order"] li')
    expect(items.map((li) => li.find('.chain-order-alias').text())).toEqual(['BE-0001', 'BE-0002'])
    expect(items.map((li) => li.find('.chain-order-name').text())).toEqual(['First', 'Second'])
    expect(wrapper.find('[data-testid="dlg-confirm"]').text()).toBe('Start chain (2)')
    expect(mockStartSequence).not.toHaveBeenCalled()
  })

  it('starts the chain in that order and closes', async () => {
    const run = { id: 'run-1' }
    mockStartSequence.mockResolvedValue(run)
    const wrapper = mountDialog()
    await flushPromises()

    await wrapper.find('[data-testid="dlg-confirm"]').trigger('click')
    await flushPromises()

    expect(mockStartSequence).toHaveBeenCalledWith({ projectIds: ['p1', 'p2'], resolvedOrder: ['p1', 'p2'] })
    expect(wrapper.emitted('started')).toEqual([[run]])
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })

  it('stays open when the server refuses the chain (the runner already showed why)', async () => {
    mockStartSequence.mockResolvedValue(null)
    const wrapper = mountDialog()
    await flushPromises()
    await wrapper.find('[data-testid="dlg-confirm"]').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('started')).toBeUndefined()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('cancel closes without creating anything', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    await wrapper.find('[data-testid="dlg-cancel"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    expect(mockStartSequence).not.toHaveBeenCalled()
  })
})
