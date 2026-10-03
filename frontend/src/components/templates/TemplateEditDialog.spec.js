
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import TemplateEditDialog from './TemplateEditDialog.vue'


const tooltipStub = {
  props: ['text', 'location'],
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

const dialogStub = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: `<div class="v-dialog"><slot /><button class="dialog-backdrop-close" @click="$emit('update:modelValue', false)" /></div>`,
}

const selectStub = {
  props: ['modelValue', 'items', 'label'],
  emits: ['update:modelValue'],
  template: `<div class="v-select" data-stub="select" v-bind="$attrs">
    <button
      v-for="item in (items || [])"
      :key="item"
      :data-role="item"
      :class="'role-option-' + item"
      @click="$emit('update:modelValue', item)"
    />
  </div>`,
}

const textFieldStub = {
  props: ['modelValue', 'label'],
  emits: ['update:modelValue'],
  template: `<input
    class="v-text-field"
    :data-label="label"
    :value="modelValue"
    v-bind="$attrs"
    @input="$emit('update:modelValue', $event.target.value)"
  />`,
}

const textareaStub = {
  props: ['modelValue', 'label'],
  emits: ['update:modelValue'],
  template: `<textarea
    class="v-textarea"
    :value="modelValue"
    v-bind="$attrs"
    @input="$emit('update:modelValue', $event.target.value)"
  ></textarea>`,
}


function makeTemplate(overrides = {}) {
  return {
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
    ...overrides,
  }
}

const defaultRoleOptions = ['analyzer', 'designer', 'frontend', 'backend', 'implementer', 'tester', 'reviewer', 'documenter']

function mountDialog(propsData = {}) {
  return mount(TemplateEditDialog, {
    props: {
      modelValue: true,
      template: makeTemplate(),
      saving: false,
      generatedName: '',
      roleOptions: defaultRoleOptions,
      hasChanges: true,
      ...propsData,
    },
    global: {
      stubs: {
        'v-dialog': dialogStub,
        'v-select': selectStub,
        'v-text-field': textFieldStub,
        'v-textarea': textareaStub,
        'v-tooltip': tooltipStub,
        Teleport: true,
      },
    },
  })
}


describe('TemplateEditDialog — render', () => {
  it('shows "Create new Template" title when template.id is null', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('.dlg-title').text()).toBe('Create new Template')
  })

  it('create mode header has no icon or badge besides the close button', () => {
    const wrapper = mountDialog()
    const header = wrapper.find('.dlg-header')
    expect(header.findAll('.v-icon, .mdi, [class*="badge"], [class*="pill"]').length).toBe(
      header.findAll('.dlg-close .v-icon, .dlg-close .mdi').length,
    )
    expect(header.findAll('.dlg-title *').length).toBe(0)
  })

  it('create mode primary button reads Save', () => {
    const wrapper = mountDialog()
    const primary = wrapper.find('.dlg-footer [color="primary"]')
    expect(primary.text()).toBe('Save')
  })

  it('shows "Edit Template" title when template.id is set', () => {
    const wrapper = mountDialog({ template: makeTemplate({ id: 42 }) })
    expect(wrapper.find('.dlg-title').text()).toBe('Edit Template')
  })

  it('renders the Save button', () => {
    const wrapper = mountDialog()
    const saveBtn = wrapper.findAll('button').find((b) => b.text().includes('Save'))
    expect(saveBtn).toBeTruthy()
  })

  it('renders the Cancel button', () => {
    const wrapper = mountDialog()
    const cancelBtn = wrapper.findAll('button').find((b) => b.text().includes('Cancel'))
    expect(cancelBtn).toBeTruthy()
  })

  it('renders the close (X) button with aria-label Close', () => {
    const wrapper = mountDialog()
    const closeBtn = wrapper.find('[aria-label="Close"]')
    expect(closeBtn.exists()).toBe(true)
  })

  it('renders generatedName preview when generatedName is set', () => {
    const wrapper = mountDialog({
      template: makeTemplate({ role: 'analyzer', custom_suffix: 'fast' }),
      generatedName: 'analyzer-fast',
    })
    expect(wrapper.text()).toContain('analyzer-fast')
  })

  it('does not render generatedName section when generatedName is empty', () => {
    const wrapper = mountDialog({ generatedName: '' })
    expect(wrapper.text()).not.toContain('Agent Name:')
  })

  it('reflects current user_instructions in the textarea', () => {
    const wrapper = mountDialog({
      template: makeTemplate({ user_instructions: 'Do important work' }),
    })
    const textarea = wrapper.find('.v-textarea')
    expect(textarea.exists()).toBe(true)
    expect(textarea.element.value).toBe('Do important work')
  })
})


describe('TemplateEditDialog — emit: save', () => {
  it('emits save when Save button is clicked', async () => {
    const wrapper = mountDialog({ hasChanges: true })
    const saveBtn = wrapper.findAll('button').find((b) => b.text().includes('Save'))
    await saveBtn.trigger('click')
    expect(wrapper.emitted('save')).toHaveLength(1)
  })
})

describe('TemplateEditDialog — emit: close', () => {
  it('emits close when Cancel button is clicked', async () => {
    const wrapper = mountDialog()
    const cancelBtn = wrapper.findAll('button').find((b) => b.text().includes('Cancel'))
    await cancelBtn.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('emits close when the X (dlg-close) button is clicked', async () => {
    const wrapper = mountDialog()
    await wrapper.find('[aria-label="Close"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})

describe('TemplateEditDialog — emit: role-change', () => {
  it('emits role-change with the selected role when the role select changes', async () => {
    const wrapper = mountDialog()
    const backendOption = wrapper.find('.role-option-backend')
    expect(backendOption.exists()).toBe(true)
    await backendOption.trigger('click')

    expect(wrapper.emitted('role-change')).toHaveLength(1)
    expect(wrapper.emitted('role-change')[0]).toEqual(['backend'])
  })
})

describe('TemplateEditDialog — emit: update:template', () => {
  it('emits update:template with the merged object when custom_suffix changes', async () => {
    const tpl = makeTemplate({ role: 'analyzer', custom_suffix: '', description: 'original' })
    const wrapper = mountDialog({ template: tpl })

    const suffixInput = wrapper.find('[data-label="Custom Suffix (optional)"]')
    expect(suffixInput.exists()).toBe(true)

    await suffixInput.setValue('fast')

    const emitted = wrapper.emitted('update:template')
    expect(emitted).toHaveLength(1)
    expect(emitted[0][0]).toMatchObject({ custom_suffix: 'fast', description: 'original', role: 'analyzer' })
  })

  it('emits update:template with merged object when description changes', async () => {
    const tpl = makeTemplate({ custom_suffix: 'x', description: '' })
    const wrapper = mountDialog({ template: tpl })

    const descInput = wrapper.find('[data-label="Description"]')
    expect(descInput.exists()).toBe(true)
    await descInput.setValue('New description')

    const emitted = wrapper.emitted('update:template')
    expect(emitted).toHaveLength(1)
    expect(emitted[0][0]).toMatchObject({ description: 'New description', custom_suffix: 'x' })
  })

  it('emits update:template when user_instructions textarea changes', async () => {
    const tpl = makeTemplate({ user_instructions: '' })
    const wrapper = mountDialog({ template: tpl })

    const textarea = wrapper.find('.v-textarea')
    expect(textarea.exists()).toBe(true)
    await textarea.setValue('New instructions')

    const emitted = wrapper.emitted('update:template')
    expect(emitted).toHaveLength(1)
    expect(emitted[0][0]).toMatchObject({ user_instructions: 'New instructions' })
  })
})

describe('TemplateEditDialog — emit: update:modelValue', () => {
  it('emits update:modelValue=false when the dialog stub fires update:modelValue', async () => {
    const wrapper = mountDialog()
    const backdropClose = wrapper.find('.dialog-backdrop-close')
    expect(backdropClose.exists()).toBe(true)
    await backdropClose.trigger('click')

    expect(wrapper.emitted('update:modelValue')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')[0]).toEqual([false])
  })
})


describe('TemplateEditDialog — FE-9610c: no cross-product affordance', () => {
  it('offers neither bulk action', () => {
    const wrapper = mountDialog({ template: makeTemplate({ id: 'tpl-1', role: 'analyzer' }) })

    expect(wrapper.find('[data-testid="enable-all-products"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="disable-all-products"]').exists()).toBe(false)
  })

  it('says nothing about other products, or about moving an agent between them', () => {
    const wrapper = mountDialog({ template: makeTemplate({ id: 'tpl-1', role: 'analyzer' }) })
    const text = wrapper.text()

    expect(text).not.toMatch(/all products/i)
    expect(text).not.toMatch(/move|reassign|transfer/i)
  })

  it('exposes no account-wide enable control', () => {
    const wrapper = mountDialog({ template: makeTemplate({ id: 'tpl-1', role: 'analyzer' }) })

    expect(wrapper.find('[data-testid="template-retire-switch"]').exists()).toBe(false)
    expect(wrapper.text()).not.toMatch(/retire|available in all/i)
  })
})
describe('TemplateEditDialog — model and effort hints (BE-9605b)', () => {
  it('renders two plain text inputs defaulting to inherit', () => {
    const wrapper = mountDialog({ template: makeTemplate({ model: undefined, effort: undefined }) })
    const model = wrapper.find('[data-testid="model-input"]')
    const effort = wrapper.find('[data-testid="effort-input"]')
    expect(model.exists()).toBe(true)
    expect(effort.exists()).toBe(true)
    expect(model.element.value).toBe('inherit')
    expect(effort.element.value).toBe('inherit')
  })

  it('reflects stored free text verbatim', () => {
    const wrapper = mountDialog({ template: makeTemplate({ model: 'whatever is newest', effort: 'think hard' }) })
    expect(wrapper.find('[data-testid="model-input"]').element.value).toBe('whatever is newest')
    expect(wrapper.find('[data-testid="effort-input"]').element.value).toBe('think hard')
  })

  it('emits update:template with the typed model and effort', async () => {
    const wrapper = mountDialog()
    await wrapper.find('[data-testid="model-input"]').setValue('claude-opus-5 or newer')
    await wrapper.find('[data-testid="effort-input"]').setValue('max')
    const emitted = wrapper.emitted('update:template')
    expect(emitted[0][0].model).toBe('claude-opus-5 or newer')
    expect(emitted[1][0].effort).toBe('max')
  })

  it('shows the inherit help text on both fields', () => {
    const wrapper = mountDialog()
    const hint = "Prose instruction for the harness; 'inherit' = same as the orchestrator"
    expect(wrapper.find('[data-testid="model-input"]').attributes('hint')).toBe(hint)
    expect(wrapper.find('[data-testid="effort-input"]').attributes('hint')).toBe(hint)
  })
})
