
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

function codingToolSelect(wrapper) {
  return wrapper.find('[data-testid="cli-tool-select"]')
}

describe('TemplateEditDialog — Coding tool dropdown (INF-6049c)', () => {
  it('renders the Coding tool select with the surviving tools (INF-9605a)', () => {
    const wrapper = mountDialog()
    const select = codingToolSelect(wrapper)
    expect(select.exists()).toBe(true)
    const values = select.findAll('button').map((b) => b.attributes('data-value'))
    expect(values).toEqual(['claude', 'codex', 'generic'])
  })

  it('reflects the template current cli_tool', () => {
    const wrapper = mountDialog({ template: makeTemplate({ cli_tool: 'codex' }) })
    expect(codingToolSelect(wrapper).attributes('data-testid')).toBe('cli-tool-select')
    expect(codingToolSelect(wrapper).exists()).toBe(true)
  })

  it('shows a retired cli_tool once as "Generic (was Gemini)" (INF-9605a)', () => {
    const wrapper = mountDialog({ template: makeTemplate({ cli_tool: 'gemini' }) })
    const select = codingToolSelect(wrapper)
    const legacy = select.find('[data-value="gemini"]')
    expect(legacy.exists()).toBe(true)
    expect(legacy.text()).toBe('Generic (was Gemini)')
    expect(select.find('[data-value="antigravity"]').exists()).toBe(false)
  })

  it('folds a retired cli_tool to generic on the next edit of any field (INF-9605a)', async () => {
    const wrapper = mountDialog({ template: makeTemplate({ cli_tool: 'antigravity', role: 'implementer' }) })
    const codexBtn = codingToolSelect(wrapper).find('[data-value="codex"]')
    await codexBtn.trigger('click')
    expect(wrapper.emitted('update:template')[0][0]).toMatchObject({ cli_tool: 'codex' })

    const wrapper2 = mountDialog({ template: makeTemplate({ cli_tool: 'gemini', role: 'implementer' }) })
    const suffix = wrapper2.find('input[aria-label="Custom agent name suffix"]')
    expect(suffix.exists()).toBe(true)
    await suffix.setValue('fastapi')
    const emitted = wrapper2.emitted('update:template')
    expect(emitted).toHaveLength(1)
    expect(emitted[0][0]).toMatchObject({ custom_suffix: 'fastapi', cli_tool: 'generic' })
  })

  it('persists a change by emitting update:template with the new cli_tool', async () => {
    const wrapper = mountDialog({ template: makeTemplate({ cli_tool: 'claude', role: 'implementer' }) })
    const codexBtn = codingToolSelect(wrapper).find('[data-value="codex"]')
    expect(codexBtn.exists()).toBe(true)
    await codexBtn.trigger('click')

    const emitted = wrapper.emitted('update:template')
    expect(emitted).toHaveLength(1)
    expect(emitted[0][0]).toMatchObject({ cli_tool: 'codex', role: 'implementer' })
  })

  it('defaults the displayed value to claude when cli_tool is unset', () => {
    const wrapper = mountDialog({ template: makeTemplate({ cli_tool: undefined }) })
    expect(codingToolSelect(wrapper).find('[data-value="generic"]').exists()).toBe(true)
  })
})
