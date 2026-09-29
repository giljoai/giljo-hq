
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import TemplateEditDialog from './TemplateEditDialog.vue'

const selectStub = {
  props: ['modelValue', 'items', 'label'],
  emits: ['update:modelValue'],
  template: `<div class="v-select" v-bind="$attrs">
    <button
      v-for="item in (items || [])"
      :key="(item && item.value !== undefined) ? item.value : item"
      :data-value="(item && item.value !== undefined) ? item.value : item"
      @click="$emit('update:modelValue', (item && item.value !== undefined) ? item.value : item)"
    >{{ (item && item.title !== undefined) ? item.title : item }}</button>
  </div>`,
}

const dialogStub = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: `<div class="v-dialog"><slot /></div>`,
}

const passthroughStub = {
  props: ['modelValue', 'label'],
  emits: ['update:modelValue'],
  template: `<input v-bind="$attrs" :value="modelValue" @input="$emit('update:modelValue', $event.target.value)" />`,
}

const tooltipStub = {
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

function makeTemplate(overrides = {}) {
  return {
    id: 7,
    name: 'implementer',
    role: 'implementer',
    cli_tool: 'claude',
    custom_suffix: '',
    background_color: '',
    description: '',
    user_instructions: '',
    model: 'sonnet',
    tools: null,
    ...overrides,
  }
}

function mountDialog(propsData = {}) {
  return mount(TemplateEditDialog, {
    props: {
      modelValue: true,
      template: makeTemplate(),
      saving: false,
      generatedName: '',
      roleOptions: ['analyzer', 'implementer', 'reviewer'],
      hasChanges: true,
      ...propsData,
    },
    global: {
      stubs: {
        'v-dialog': dialogStub,
        'v-select': selectStub,
        'v-text-field': passthroughStub,
        'v-textarea': passthroughStub,
        'v-tooltip': tooltipStub,
        Teleport: true,
      },
    },
  })
}

function harnessInput(wrapper) {
  return wrapper.find('[data-testid="cli-tool-input"]')
}

describe('TemplateEditDialog — Harness free-text field', () => {
  it('renders a free-text Harness field, not a fixed list', () => {
    const wrapper = mountDialog()
    expect(harnessInput(wrapper).exists()).toBe(true)
    expect(wrapper.find('[data-testid="cli-tool-select"]').exists()).toBe(false)
  })

  it('reflects the template current harness, including a legacy value', () => {
    expect(harnessInput(mountDialog({ template: makeTemplate({ cli_tool: 'codex' }) })).element.value).toBe('codex')
    expect(harnessInput(mountDialog({ template: makeTemplate({ cli_tool: 'gemini' }) })).element.value).toBe('gemini')
  })

  it('persists a typed harness name by emitting update:template', async () => {
    const wrapper = mountDialog({ template: makeTemplate({ cli_tool: 'claude', role: 'implementer' }) })
    await harnessInput(wrapper).setValue('gemini-cli')
    const emitted = wrapper.emitted('update:template')
    expect(emitted).toHaveLength(1)
    expect(emitted[0][0]).toMatchObject({ cli_tool: 'gemini-cli', role: 'implementer' })
  })

  it('keeps a stored harness name when another field changes (no silent rewrite)', async () => {
    const wrapper = mountDialog({ template: makeTemplate({ cli_tool: 'gemini', role: 'implementer' }) })
    await wrapper.find('input[aria-label="Custom agent name suffix"]').setValue('fastapi')
    const emitted = wrapper.emitted('update:template')
    expect(emitted[0][0]).toMatchObject({ custom_suffix: 'fastapi', cli_tool: 'gemini' })
  })

  it('shows blank for an unset harness (the server reads blank as default)', () => {
    const wrapper = mountDialog({ template: makeTemplate({ cli_tool: undefined }) })
    expect(harnessInput(wrapper).element.value).toBe('')
  })
})
