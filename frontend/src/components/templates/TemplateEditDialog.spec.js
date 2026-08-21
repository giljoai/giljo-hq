/**
 * TemplateEditDialog.spec.js — FE-6042b
 *
 * Co-located child spec for TemplateEditDialog.vue.
 * Covers render variants and EVERY emit.
 *
 * Strategy: custom stubs that can emit Vue-level events so the component's
 * @update:model-value listeners actually fire — matching the approach used
 * in TemplateManager.spec.js and TemplatesTable.spec.js.
 *
 * Edition scope: CE
 */

import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import TemplateEditDialog from './TemplateEditDialog.vue'

// ---------------------------------------------------------------------------
// Stubs
// ---------------------------------------------------------------------------

const tooltipStub = {
  props: ['text', 'location'],
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

/**
 * v-dialog stub: renders slot contents so child elements are accessible.
 * Exposes an update:model-value emitter so the component's binding fires.
 */
const dialogStub = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: `<div class="v-dialog"><slot /><button class="dialog-backdrop-close" @click="$emit('update:modelValue', false)" /></div>`,
}

/**
 * v-select stub for role: clicking triggers update:modelValue with a new value.
 * Emits Vue-level event so the component's @update:model-value="$emit('role-change', $event)" fires.
 */
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

/**
 * v-text-field stub: input event triggers update:modelValue.
 */
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

/**
 * v-textarea stub: input event triggers update:modelValue.
 */
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

// ---------------------------------------------------------------------------
// Default props
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Render variants
// ---------------------------------------------------------------------------

describe('TemplateEditDialog — render', () => {
  it('shows "Create Template" title when template.id is null', () => {
    const wrapper = mountDialog()
    expect(wrapper.text()).toContain('Create Template')
  })

  it('shows "Edit Template" title when template.id is set', () => {
    const wrapper = mountDialog({ template: makeTemplate({ id: 42 }) })
    expect(wrapper.text()).toContain('Edit Template')
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

// ---------------------------------------------------------------------------
// Emits — every declared emit
// ---------------------------------------------------------------------------

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
    // selectStub renders one button per role option; click "backend"
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

    // Find custom_suffix field by data-label (textFieldStub sets data-label from :label prop)
    const suffixInput = wrapper.find('[data-label="Custom Suffix (optional)"]')
    expect(suffixInput.exists()).toBe(true)

    await suffixInput.setValue('fast')

    const emitted = wrapper.emitted('update:template')
    expect(emitted).toHaveLength(1)
    // custom_suffix updated, sibling fields preserved (proves update() spreads correctly)
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
    // dialogStub has a .dialog-backdrop-close button that emits update:modelValue=false
    const backdropClose = wrapper.find('.dialog-backdrop-close')
    expect(backdropClose.exists()).toBe(true)
    await backdropClose.trigger('click')

    expect(wrapper.emitted('update:modelValue')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')[0]).toEqual([false])
  })
})

// ---------------------------------------------------------------------------
// FE-9385c — the availability control is one line, and its label holds still
// ---------------------------------------------------------------------------
// This control had NO coverage before: the heading could be removed and the
// label rewritten and the whole suite stayed green. That gap is why these exist.

describe('TemplateEditDialog — FE-9385c availability control', () => {
  // tests/setup.js stubs v-switch as a bare checkbox, so the label arrives as an
  // attribute rather than as rendered text here. Asserting the attribute is what
  // is actually observable in this harness; asserting wrapper.text() would pass
  // or fail for reasons that have nothing to do with the label.
  const retireSwitch = (wrapper) => wrapper.find('[data-testid="retire-switch"]')

  it('reads "Available in all products" when the agent IS available', () => {
    const wrapper = mountDialog({ template: makeTemplate({ id: 7, is_active: true }) })

    expect(retireSwitch(wrapper).attributes('label')).toBe('Available in all products')
  })

  it('reads the SAME label when the agent is NOT available', () => {
    // The behaviour change: the label used to flip to "Retired everywhere". A
    // caption that rewrites itself as you toggle is harder to read at a glance,
    // and the switch position already carries the state.
    const wrapper = mountDialog({ template: makeTemplate({ id: 7, is_active: false }) })

    expect(retireSwitch(wrapper).attributes('label')).toBe('Available in all products')
    expect(wrapper.html()).not.toContain('Retired everywhere')
  })

  it('no longer renders the redundant "Availability" heading', () => {
    const wrapper = mountDialog({ template: makeTemplate({ id: 7, is_active: true }) })

    // The switch and its own label said everything the heading said.
    expect(wrapper.text()).not.toMatch(/\bAvailability\b/)
  })

  it('carries an aria-label matching the visible label', () => {
    // The string most likely to be missed when visible text changes.
    const wrapper = mountDialog({ template: makeTemplate({ id: 7, is_active: true }) })

    expect(wrapper.html()).toContain('aria-label="Available in all products"')
    expect(wrapper.html()).not.toMatch(/aria-label="Availability/)
  })

  it('still hides the control on CREATE, where the choice would mean nothing', () => {
    // Unchanged behaviour, pinned because the markup around it moved: a new
    // agent is born available, so offering the toggle would imply a decision
    // nothing acts on.
    const wrapper = mountDialog({ template: makeTemplate({ id: null }) })

    expect(wrapper.text()).not.toContain('Available in all products')
  })
})
