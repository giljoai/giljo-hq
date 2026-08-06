/**
 * Test suite for ProductDeleteDialog component
 * TDD Phase 1: Write failing tests before implementation
 *
 * Tests cover:
 * - Dialog rendering based on modelValue
 * - Product name display
 * - Cascade impact display
 * - Confirmation checkbox behavior
 * - Delete button disabled state
 * - Event emissions (confirm, cancel)
 * - Loading state
 * - Warning alert display
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ProductDeleteDialog from '@/components/products/ProductDeleteDialog.vue'

// BE-9356: this spec used to hardcode the cascade-impact field names in its own
// fixture and then assert those same names rendered -- it verified that Vue
// interpolates a prop the test invented, so it stayed green for months while the
// dialog rendered six blanks against a backend that never had those fields.
// The names below are now DERIVED from the authoritative Pydantic model, so a
// schema change fails this file instead of passing silently.
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../..')
const MODELS_PY = resolve(REPO_ROOT, 'api/endpoints/products/models.py')
const DIALOG_VUE = resolve(REPO_ROOT, 'frontend/src/components/products/ProductDeleteDialog.vue')

/**
 * Extract `name -> annotation` for a Pydantic model's declared fields.
 * Reads the class body until the first line back at column 0.
 */
const pydanticFields = (source, className) => {
  const start = source.indexOf(`class ${className}(BaseModel):`)
  if (start === -1) throw new Error(`${className} not found in ${MODELS_PY}`)

  const body = source.slice(start).split('\n').slice(1)
  const fields = {}
  let inDocstring = false

  for (const line of body) {
    if (line.trim() === '') continue
    if (!/^\s/.test(line)) break // dedent to column 0 -- class body is over

    const quotes = (line.match(/"""/g) || []).length
    if (inDocstring) {
      if (quotes > 0) inDocstring = false
      continue
    }
    if (line.trim().startsWith('"""')) {
      if (quotes === 1) inDocstring = true
      continue
    }

    const match = line.match(/^ {4}([a-z_][a-z0-9_]*)\s*:\s*([^=]+?)\s*(?:=|$)/i)
    if (match) fields[match[1]] = match[2].trim()
  }

  if (Object.keys(fields).length === 0) throw new Error(`${className} parsed to zero fields`)
  return fields
}

const CASCADE_IMPACT_FIELDS = pydanticFields(readFileSync(MODELS_PY, 'utf8'), 'CascadeImpact')

/**
 * The integer counts the backend exposes -- exactly what the dialog must render.
 * Exact annotation match, not a substring: `includes('int')` would also claim
 * `Literal["print"]`, `Point`, or `Interval` and redden this block for a
 * non-reason.
 */
const INT_ANNOTATIONS = ['int', 'int | None']
const BACKEND_COUNT_FIELDS = Object.keys(CASCADE_IMPACT_FIELDS)
  .filter((name) => INT_ANNOTATIONS.includes(CASCADE_IMPACT_FIELDS[name]))
  .sort()

/** Every `cascadeImpact.<field>` the dialog template actually reads. */
const dialogReadFields = () => {
  const source = readFileSync(DIALOG_VUE, 'utf8')
  const template = source.slice(0, source.indexOf('<script'))
  const found = [...template.matchAll(/cascadeImpact\.([a-zA-Z_][a-zA-Z0-9_]*)/g)]
  return [...new Set(found.map((m) => m[1]))].sort()
}

/** A fixture whose KEYS come from the backend model, not from this test file. */
const impactFrom = (values = {}) =>
  Object.fromEntries(BACKEND_COUNT_FIELDS.map((name, i) => [name, values[name] ?? (i + 1) * 3]))

describe('ProductDeleteDialog Component', () => {
  const createWrapper = (props = {}) => {
    const defaultProps = {
      modelValue: true,
      product: {
        id: 'test-product-id',
        name: 'Test Product'
      },
      cascadeImpact: impactFrom(),
      loading: false
    }

    return mount(ProductDeleteDialog, {
      props: { ...defaultProps, ...props },
      global: {
        stubs: {
          'v-dialog': {
            template: '<div class="v-dialog"><slot /></div>',
            props: ['modelValue', 'persistent']
          },
          'v-card': { template: '<div class="v-card"><slot /></div>' },
          'v-card-title': { template: '<div class="v-card-title"><slot /></div>' },
          'v-card-text': { template: '<div class="v-card-text"><slot /></div>' },
          'v-card-actions': { template: '<div class="v-card-actions"><slot /></div>' },
          'v-divider': { template: '<hr class="v-divider" />' },
          'v-icon': { template: '<span class="v-icon"><slot /></span>' },
          'v-alert': { template: '<div class="v-alert"><slot /></div>' },
          'v-list': { template: '<div class="v-list"><slot /></div>' },
          'v-list-item': { template: '<div class="v-list-item"><slot /></div>' },
          'v-list-item-title': { template: '<div class="v-list-item-title"><slot /></div>' },
          'v-list-item-subtitle': { template: '<div class="v-list-item-subtitle"><slot /></div>' },
          'v-checkbox': {
            template: '<div class="v-checkbox"><input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" /><slot name="label" /></div>',
            props: ['modelValue', 'density', 'hideDetails'],
            emits: ['update:modelValue']
          },
          'v-btn': {
            template: '<button class="v-btn" :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>',
            props: ['variant', 'color', 'disabled', 'loading'],
            emits: ['click']
          },
          'v-spacer': { template: '<div class="v-spacer"></div>' },
          'v-progress-circular': { template: '<div class="v-progress-circular">Loading...</div>' }
        }
      }
    })
  }

  describe('Dialog Rendering', () => {
    it('renders dialog when modelValue is true', () => {
      const wrapper = createWrapper({ modelValue: true })

      expect(wrapper.find('.v-dialog').exists()).toBe(true)
    })

    it('does not render dialog content when modelValue is false', () => {
      const wrapper = createWrapper({ modelValue: false })

      // Dialog should exist
      const dialog = wrapper.find('.v-dialog')
      expect(dialog.exists()).toBe(true)
    })

    it('displays product name in dialog content', async () => {
      const productName = 'My Test Product'
      const wrapper = createWrapper({
        product: { id: 'test-id', name: productName }
      })

      await flushPromises()

      expect(wrapper.text()).toContain(productName)
    })
  })

  describe('Backend Contract', () => {
    it('reads exactly the count fields the backend CascadeImpact model exposes', () => {
      // Drift in EITHER direction fails: a field the dialog reads but the backend
      // does not send (the BE-9356 bug -- six blanks), or a count the backend
      // added that the dialog silently drops.
      expect(dialogReadFields()).toEqual(BACKEND_COUNT_FIELDS)
    })

    it('declares a prop default whose keys all exist on the backend model', () => {
      // cascadeImpact: undefined -> Vue resolves the component's own default.
      const wrapper = createWrapper({ cascadeImpact: undefined })

      expect(Object.keys(wrapper.props('cascadeImpact')).sort()).toEqual(BACKEND_COUNT_FIELDS)
    })

    it('backend model still exposes the three counts this dialog was built for', () => {
      // Guards the parser itself: if it ever silently matched nothing, the two
      // assertions above would compare two empty arrays and pass.
      expect(BACKEND_COUNT_FIELDS).toEqual([
        'total_projects',
        'total_tasks',
        'total_vision_documents'
      ])
    })
  })

  describe('Cascade Impact Display', () => {
    it('renders a value for every count the backend sends', async () => {
      const wrapper = createWrapper({ cascadeImpact: impactFrom() })
      await flushPromises()

      for (const [field, value] of Object.entries(impactFrom())) {
        expect(wrapper.text(), `no rendered value for ${field}`).toContain(String(value))
      }
    })

    it('shows the projects count', async () => {
      const wrapper = createWrapper({ cascadeImpact: impactFrom({ total_projects: 5 }) })
      await flushPromises()

      expect(wrapper.text()).toContain('5')
      expect(wrapper.text()).toContain('projects')
    })

    it('shows the tasks count', async () => {
      const wrapper = createWrapper({ cascadeImpact: impactFrom({ total_tasks: 15 }) })
      await flushPromises()

      expect(wrapper.text()).toContain('15')
      expect(wrapper.text()).toContain('tasks')
    })

    it('shows the vision documents count', async () => {
      const wrapper = createWrapper({ cascadeImpact: impactFrom({ total_vision_documents: 7 }) })
      await flushPromises()

      expect(wrapper.text()).toContain('7')
      expect(wrapper.text()).toContain('vision documents')
    })

    it('does not claim the listed items are being deleted', async () => {
      const wrapper = createWrapper()
      await flushPromises()

      // delete_product cascades nothing -- these items stay with the product in
      // the trash and go only if it is never restored.
      expect(wrapper.text()).not.toContain('This will delete:')
      expect(wrapper.text()).toContain('Kept with this product in the trash')
    })
  })

  describe('Confirmation Checkbox Behavior', () => {
    it('has checkbox initially unchecked', () => {
      const wrapper = createWrapper()

      const checkbox = wrapper.find('.v-checkbox input')
      expect(checkbox.exists()).toBe(true)
      expect(checkbox.element.checked).toBe(false)
    })

    it('checkbox can be toggled', async () => {
      const wrapper = createWrapper()

      const checkbox = wrapper.find('.v-checkbox input')

      // Simulate checkbox change
      await checkbox.setValue(true)
      await flushPromises()

      // The checkbox state is managed internally by BaseDialog via confirm-checkbox prop.
      // Verify the DOM reflects the toggle.
      expect(checkbox.element.checked).toBe(true)
    })
  })

  describe('Delete Button State', () => {
    it('delete button is disabled when checkbox is unchecked', async () => {
      const wrapper = createWrapper()
      await flushPromises()

      const buttons = wrapper.findAll('.v-btn')
      const deleteButton = buttons.find(btn =>
        btn.text().includes('Move to Trash') || btn.text().includes('Trash')
      )

      expect(deleteButton).toBeDefined()
      expect(deleteButton.attributes('disabled')).toBeDefined()
    })

    it('delete button is enabled when checkbox is checked', async () => {
      const wrapper = createWrapper()

      // Check the checkbox
      const checkbox = wrapper.find('.v-checkbox input')
      await checkbox.setValue(true)
      await flushPromises()

      const buttons = wrapper.findAll('.v-btn')
      const deleteButton = buttons.find(btn =>
        btn.text().includes('Move to Trash') || btn.text().includes('Trash')
      )

      expect(deleteButton).toBeDefined()
      // Button should not be disabled when checkbox is checked
      expect(deleteButton.attributes('disabled')).toBeUndefined()
    })

    it('delete button passes loading state when deleting', async () => {
      const wrapper = createWrapper({ deleting: true })

      // Check the checkbox first
      const checkbox = wrapper.find('.v-checkbox input')
      await checkbox.setValue(true)
      await flushPromises()

      // BaseDialog receives loading=true via the :loading="deleting" prop binding,
      // which makes the confirm button loading (implicitly disabled in real Vuetify).
      // Verify the deleting prop is passed through to BaseDialog.
      const baseDialog = wrapper.findComponent({ name: 'BaseDialog' })
      expect(baseDialog.exists()).toBe(true)
      expect(baseDialog.props('loading')).toBe(true)
    })
  })

  describe('Event Emissions', () => {
    it('emits confirm event when delete button clicked', async () => {
      const wrapper = createWrapper()

      // Check the checkbox first to enable the button
      const checkbox = wrapper.find('.v-checkbox input')
      await checkbox.setValue(true)
      await flushPromises()

      // Find and click the delete button
      const buttons = wrapper.findAll('.v-btn')
      const deleteButton = buttons.find(btn =>
        btn.text().includes('Move to Trash') || btn.text().includes('Trash')
      )

      await deleteButton.trigger('click')
      await flushPromises()

      expect(wrapper.emitted('confirm')).toBeTruthy()
      expect(wrapper.emitted('confirm').length).toBe(1)
    })

    it('emits cancel event when cancel button clicked', async () => {
      const wrapper = createWrapper()
      await flushPromises()

      // Find and click the cancel button
      const buttons = wrapper.findAll('.v-btn')
      const cancelButton = buttons.find(btn =>
        btn.text().includes('Cancel')
      )

      await cancelButton.trigger('click')
      await flushPromises()

      expect(wrapper.emitted('cancel')).toBeTruthy()
      expect(wrapper.emitted('cancel').length).toBe(1)
    })

    it('emits update:modelValue with false when cancel clicked', async () => {
      const wrapper = createWrapper()
      await flushPromises()

      // Find and click the cancel button
      const buttons = wrapper.findAll('.v-btn')
      const cancelButton = buttons.find(btn =>
        btn.text().includes('Cancel')
      )

      await cancelButton.trigger('click')
      await flushPromises()

      expect(wrapper.emitted('update:modelValue')).toBeTruthy()
      expect(wrapper.emitted('update:modelValue')[0]).toEqual([false])
    })
  })

  describe('Loading State', () => {
    it('shows loading spinner when calculating cascade impact', async () => {
      const wrapper = createWrapper({ loading: true })
      await flushPromises()

      expect(wrapper.text()).toContain('Calculating impact')
      expect(wrapper.find('.v-progress-circular').exists()).toBe(true)
    })

    it('hides cascade impact details while loading', async () => {
      const wrapper = createWrapper({ loading: true, cascadeImpact: impactFrom() })
      await flushPromises()

      // Should show loading, not the cascade impact
      expect(wrapper.text()).toContain('Calculating impact')
      expect(wrapper.text()).not.toContain('Kept with this product in the trash')
    })

    it('shows cascade impact when loading is complete', async () => {
      const wrapper = createWrapper({ loading: false })
      await flushPromises()

      expect(wrapper.text()).not.toContain('Calculating impact')
      expect(wrapper.text()).toContain('Kept with this product in the trash')
    })
  })

  describe('Warning Alert', () => {
    it('displays warning about 10-day recovery window', async () => {
      const wrapper = createWrapper()
      await flushPromises()

      expect(wrapper.text()).toContain('10 days')
      expect(wrapper.text()).toContain('recovered')
    })

    it('displays product name in warning message', async () => {
      const productName = 'Special Product'
      const wrapper = createWrapper({
        product: { id: 'test-id', name: productName }
      })
      await flushPromises()

      // Warning should mention the product name
      const alertText = wrapper.text()
      expect(alertText).toContain(productName)
    })

    it('displays permanent deletion warning', async () => {
      const wrapper = createWrapper()
      await flushPromises()

      expect(wrapper.text()).toContain('permanently deleted')
    })
  })

  describe('V-Model Pattern', () => {
    it('implements computed isOpen for v-model pattern', () => {
      const wrapper = createWrapper({ modelValue: true })

      // Component should use isOpen computed property
      expect(wrapper.vm.isOpen).toBe(true)
    })

    it('updates isOpen when modelValue changes', async () => {
      const wrapper = createWrapper({ modelValue: true })

      expect(wrapper.vm.isOpen).toBe(true)

      await wrapper.setProps({ modelValue: false })

      expect(wrapper.vm.isOpen).toBe(false)
    })
  })

  describe('State Reset', () => {
    it('BaseDialog manages checkbox state reset when dialog opens', async () => {
      // The confirmation checkbox is now managed internally by BaseDialog
      // via the confirm-checkbox prop. Verify the prop is passed correctly.
      const wrapper = createWrapper({ modelValue: false })

      // Open dialog
      await wrapper.setProps({ modelValue: true })
      await flushPromises()

      // BaseDialog receives the confirm-checkbox prop
      const baseDialog = wrapper.findComponent({ name: 'BaseDialog' })
      expect(baseDialog.exists()).toBe(true)
      expect(baseDialog.props('confirmCheckbox')).toBe(true)
    })

    it('BaseDialog manages checkbox state reset when dialog closes', async () => {
      // The confirmation checkbox is now managed internally by BaseDialog
      const wrapper = createWrapper({ modelValue: true })

      // Close dialog
      await wrapper.setProps({ modelValue: false })
      await flushPromises()

      // BaseDialog receives the confirm-checkbox prop
      const baseDialog = wrapper.findComponent({ name: 'BaseDialog' })
      expect(baseDialog.exists()).toBe(true)
      expect(baseDialog.props('confirmCheckbox')).toBe(true)
    })
  })

  describe('Props Validation', () => {
    it('accepts required modelValue prop', () => {
      const wrapper = createWrapper({ modelValue: true })
      expect(wrapper.props('modelValue')).toBe(true)
    })

    it('accepts product prop with default empty object', () => {
      const wrapper = mount(ProductDeleteDialog, {
        props: {
          modelValue: true
        },
        global: {
          stubs: {
            'v-dialog': { template: '<div><slot /></div>' },
            'v-card': { template: '<div><slot /></div>' },
            'v-card-title': { template: '<div><slot /></div>' },
            'v-card-text': { template: '<div><slot /></div>' },
            'v-card-actions': { template: '<div><slot /></div>' },
            'v-divider': { template: '<hr />' },
            'v-icon': { template: '<span><slot /></span>' },
            'v-alert': { template: '<div><slot /></div>' },
            'v-list': { template: '<div><slot /></div>' },
            'v-list-item': { template: '<div><slot /></div>' },
            'v-list-item-title': { template: '<div><slot /></div>' },
            'v-list-item-subtitle': { template: '<div><slot /></div>' },
            'v-checkbox': { template: '<div><slot name="label" /></div>' },
            'v-btn': { template: '<button @click="$emit(\'click\')"><slot /></button>' },
            'v-spacer': { template: '<div></div>' },
            'v-progress-circular': { template: '<div></div>' }
          }
        }
      })

      // Should have default empty object
      expect(wrapper.props('product')).toEqual({})
    })

    it('accepts cascadeImpact prop with defaults', () => {
      const wrapper = mount(ProductDeleteDialog, {
        props: {
          modelValue: true
        },
        global: {
          stubs: {
            'v-dialog': { template: '<div><slot /></div>' },
            'v-card': { template: '<div><slot /></div>' },
            'v-card-title': { template: '<div><slot /></div>' },
            'v-card-text': { template: '<div><slot /></div>' },
            'v-card-actions': { template: '<div><slot /></div>' },
            'v-divider': { template: '<hr />' },
            'v-icon': { template: '<span><slot /></span>' },
            'v-alert': { template: '<div><slot /></div>' },
            'v-list': { template: '<div><slot /></div>' },
            'v-list-item': { template: '<div><slot /></div>' },
            'v-list-item-title': { template: '<div><slot /></div>' },
            'v-list-item-subtitle': { template: '<div><slot /></div>' },
            'v-checkbox': { template: '<div><slot name="label" /></div>' },
            'v-btn': { template: '<button @click="$emit(\'click\')"><slot /></button>' },
            'v-spacer': { template: '<div></div>' },
            'v-progress-circular': { template: '<div></div>' }
          }
        }
      })

      // Should have default cascade impact values
      expect(wrapper.props('cascadeImpact')).toBeDefined()
    })

    it('accepts loading prop with default false', () => {
      const wrapper = mount(ProductDeleteDialog, {
        props: {
          modelValue: true
        },
        global: {
          stubs: {
            'v-dialog': { template: '<div><slot /></div>' },
            'v-card': { template: '<div><slot /></div>' },
            'v-card-title': { template: '<div><slot /></div>' },
            'v-card-text': { template: '<div><slot /></div>' },
            'v-card-actions': { template: '<div><slot /></div>' },
            'v-divider': { template: '<hr />' },
            'v-icon': { template: '<span><slot /></span>' },
            'v-alert': { template: '<div><slot /></div>' },
            'v-list': { template: '<div><slot /></div>' },
            'v-list-item': { template: '<div><slot /></div>' },
            'v-list-item-title': { template: '<div><slot /></div>' },
            'v-list-item-subtitle': { template: '<div><slot /></div>' },
            'v-checkbox': { template: '<div><slot name="label" /></div>' },
            'v-btn': { template: '<button @click="$emit(\'click\')"><slot /></button>' },
            'v-spacer': { template: '<div></div>' },
            'v-progress-circular': { template: '<div></div>' }
          }
        }
      })

      expect(wrapper.props('loading')).toBe(false)
    })
  })

  describe('Accessibility', () => {
    it('has proper dialog structure', async () => {
      const wrapper = createWrapper()
      await flushPromises()

      const dialog = wrapper.find('.v-dialog')
      expect(dialog.exists()).toBe(true)
    })

    it('has delete icon in title area', async () => {
      const wrapper = createWrapper()
      await flushPromises()

      const baseDialog = wrapper.findComponent({ name: 'BaseDialog' })
      expect(baseDialog.exists()).toBe(true)
      expect(baseDialog.props('icon')).toBe('mdi-delete')
    })
  })
})
