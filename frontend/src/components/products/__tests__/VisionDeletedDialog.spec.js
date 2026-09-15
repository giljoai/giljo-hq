
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import VisionDeletedDialog from '@/components/products/VisionDeletedDialog.vue'

const listItemWithAppend = {
  template: `<div class="v-list-item"><slot /><slot name="append" /></div>`,
}

const defaultDocs = [
  { id: 'doc-aaa1', filename: 'spec.md', document_name: 'spec.md' },
  { id: 'doc-bbb2', filename: 'readme.txt', document_name: 'readme.txt' },
]

function mountDialog(props = {}) {
  return mount(VisionDeletedDialog, {
    props: {
      modelValue: true,
      deletedDocuments: defaultDocs,
      ...props,
    },
    global: {
      stubs: {
        'v-list-item': listItemWithAppend,
      },
      directives: {
        draggable: {},
      },
    },
  })
}

describe('VisionDeletedDialog', () => {
  it('(a) renders soft-deleted docs from prop', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('[data-testid="vision-deleted-dialog"]').exists()).toBe(true)
    const text = wrapper.text()
    expect(text).toContain('spec.md')
    expect(text).toContain('readme.txt')
  })

  it('(b) restore button emits restore event with the doc', async () => {
    const wrapper = mountDialog()
    const btn = wrapper.find('[data-testid="restore-vision"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(wrapper.emitted('restore')).toBeTruthy()
    expect(wrapper.emitted('restore')[0][0]).toEqual(defaultDocs[0])
  })

  it('(c) shows empty state when deletedDocuments list is empty', () => {
    const wrapper = mountDialog({ deletedDocuments: [] })
    expect(wrapper.text()).toContain('No deleted documents')
    expect(wrapper.find('[data-testid="restore-vision"]').exists()).toBe(false)
  })

  it('(d) restore button is disabled while restoringId matches that doc', () => {
    const wrapper = mountDialog({ restoringId: 'doc-aaa1' })
    const buttons = wrapper.findAll('[data-testid="restore-vision"]')
    expect(buttons[0].attributes('disabled')).toBeDefined()
    expect(buttons[1].attributes('disabled')).toBeUndefined()
  })
})
