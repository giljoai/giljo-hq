import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const apiMock = vi.hoisted(() => ({
  settings: {
    getHandoverTemplate: vi.fn(),
    updateHandoverTemplate: vi.fn(),
    resetHandoverTemplate: vi.fn(),
  },
}))
vi.mock('@/services/api', () => ({ default: apiMock, api: apiMock }))

import HandoverTemplateView from '@/components/settings/tabs/HandoverTemplateView.vue'

const textareaStub = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: `<textarea class="v-textarea" v-bind="$attrs" :value="modelValue" @input="$emit('update:modelValue', $event.target.value)"></textarea>`,
}

const textarea = (w) => w.find('[data-test="handover-template-textarea"]')

async function mountView() {
  const wrapper = mount(HandoverTemplateView, {
    global: { stubs: { Teleport: true, 'v-textarea': textareaStub } },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  apiMock.settings.getHandoverTemplate.mockResolvedValue({
    data: { handover_template: 'Stored template text', is_default: false },
  })
})

describe('FE-9643b — loading the stored template', () => {
  it('loads the account template into the editor on mount', async () => {
    const wrapper = await mountView()

    expect(apiMock.settings.getHandoverTemplate).toHaveBeenCalledTimes(1)
    expect(textarea(wrapper).element.value).toBe('Stored template text')
  })

  it('offers Restore Default only when the account has its own template', async () => {
    apiMock.settings.getHandoverTemplate.mockResolvedValue({
      data: { handover_template: 'Default text', is_default: true },
    })
    const wrapper = await mountView()

    expect(wrapper.find('[data-test="handover-reset-btn"]').attributes('disabled')).toBeDefined()
  })
})

describe('FE-9643b — saving', () => {
  it('disables Save until the text changes, then saves the edit', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('[data-test="handover-save-btn"]').attributes('disabled')).toBeDefined()

    await textarea(wrapper).setValue('Stored template text\n\n## My section\n- a note')
    expect(wrapper.find('[data-test="handover-save-btn"]').attributes('disabled')).toBeUndefined()

    apiMock.settings.updateHandoverTemplate.mockResolvedValue({
      data: { handover_template: 'Stored template text\n\n## My section\n- a note', is_default: false },
    })
    await wrapper.find('[data-test="handover-save-btn"]').trigger('click')
    await flushPromises()

    expect(apiMock.settings.updateHandoverTemplate).toHaveBeenCalledWith(
      'Stored template text\n\n## My section\n- a note',
    )
    expect(wrapper.find('[data-test="handover-success-alert"]').exists()).toBe(true)
  })

  it('shows the heading the server appends when one was missing', async () => {
    const wrapper = await mountView()
    await textarea(wrapper).setValue('Just my own notes, no headings')

    apiMock.settings.updateHandoverTemplate.mockResolvedValue({
      data: {
        handover_template:
          'Just my own notes, no headings\n\n## Verify before trusting\n- <fill this in>',
        is_default: false,
      },
    })
    await wrapper.find('[data-test="handover-save-btn"]').trigger('click')
    await flushPromises()

    expect(textarea(wrapper).element.value).toContain('## Verify before trusting')
  })

  it('surfaces the server error and does not clear the editor on a failed save', async () => {
    const wrapper = await mountView()
    await textarea(wrapper).setValue('too long or whatever')

    apiMock.settings.updateHandoverTemplate.mockRejectedValue({
      response: {
        status: 422,
        data: { error_code: 'VALIDATIONERROR', message: 'Over the 8000-character limit.' },
      },
    })
    await wrapper.find('[data-test="handover-save-btn"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="handover-error-alert"]').text()).toContain(
      'Over the 8000-character limit.',
    )
    expect(textarea(wrapper).element.value).toBe('too long or whatever')
  })
})

describe('FE-9643b — resetting', () => {
  it('restores the shipped default and shows it in the editor', async () => {
    const wrapper = await mountView()

    apiMock.settings.resetHandoverTemplate.mockResolvedValue({
      data: { handover_template: 'The shipped default template', is_default: true },
    })
    await wrapper.find('[data-test="handover-reset-btn"]').trigger('click')
    await flushPromises()

    expect(apiMock.settings.resetHandoverTemplate).toHaveBeenCalledTimes(1)
    expect(textarea(wrapper).element.value).toBe('The shipped default template')
    expect(wrapper.find('[data-test="handover-reset-btn"]').attributes('disabled')).toBeDefined()
  })
})
