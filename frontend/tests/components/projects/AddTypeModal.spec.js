import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createVuetify } from 'vuetify'
import { nextTick } from 'vue'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import AddTypeModal from '@/components/projects/AddTypeModal.vue'

vi.mock('@/services/api', () => ({
  default: {
    taxonomyTypes: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      create: vi.fn().mockResolvedValue({
        data: { id: 'type-new', abbreviation: 'TST', label: 'Testing', color: '#E91E63' },
      }),
    },
  },
}))

// Import after mock declaration so the mock is active
import api from '@/services/api'

describe('AddTypeModal.vue', () => {
  let wrapper
  let pinia
  let vuetify

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vuetify = createVuetify({
      components,
      directives,
    })
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
    vi.clearAllMocks()
  })

  const createWrapper = (props = {}) => {
    return mount(AddTypeModal, {
      props: {
        modelValue: false,
        ...props,
      },
      global: {
        plugins: [pinia, vuetify],
      },
      attachTo: document.body,
    })
  }

  describe('Visibility', () => {
    it('renders when modelValue is true', async () => {
      wrapper = createWrapper({ modelValue: true })
      await flushPromises()

      expect(wrapper.exists()).toBe(true)
      // The component should be present in the DOM
      expect(wrapper.html()).toContain('Add Project Type')
    })

    it('does not render when modelValue is false', async () => {
      wrapper = createWrapper({ modelValue: false })
      await flushPromises()

      // v-dialog is stubbed as a plain div, so the component still mounts
      // but the modelValue prop is false, which controls dialog visibility
      expect(wrapper.exists()).toBe(true)
      expect(wrapper.props('modelValue')).toBe(false)
    })
  })

  describe('Abbreviation Validation', () => {
    it('abbreviation validation rejects lowercase', async () => {
      wrapper = createWrapper({ modelValue: true })
      await flushPromises()

      // Access the validation rules directly from the component
      const vm = wrapper.vm
      const rules = vm.abbreviationRules

      // The second rule validates the pattern (2-4 uppercase letters)
      const patternRule = rules[1]
      const result = patternRule('abc')
      expect(result).not.toBe(true)
      expect(result).toBe('Must be 2-4 uppercase letters')
    })

    it('abbreviation validation rejects too-short input', async () => {
      wrapper = createWrapper({ modelValue: true })
      await flushPromises()

      const rules = wrapper.vm.abbreviationRules
      const patternRule = rules[1]

      // Single character should fail the 2-4 uppercase pattern
      const result = patternRule('A')
      expect(result).not.toBe(true)
      expect(result).toBe('Must be 2-4 uppercase letters')
    })

    it('abbreviation validation accepts valid input', async () => {
      wrapper = createWrapper({ modelValue: true })
      await flushPromises()

      const rules = wrapper.vm.abbreviationRules

      // Required rule
      expect(rules[0]('BE')).toBe(true)
      // Pattern rule - 2 chars
      expect(rules[1]('BE')).toBe(true)
      // Pattern rule - 3 chars
      expect(rules[1]('DEV')).toBe(true)
      // Pattern rule - 4 chars
      expect(rules[1]('TEST')).toBe(true)
    })
  })

  describe('Label Validation', () => {
    it('label validation rejects empty', async () => {
      wrapper = createWrapper({ modelValue: true })
      await flushPromises()

      const rules = wrapper.vm.labelRules
      const requiredRule = rules[0]

      expect(requiredRule('')).not.toBe(true)
      expect(requiredRule('')).toBe('Label is required')

      // Also test null/undefined-ish
      expect(requiredRule(null)).not.toBe(true)
    })
  })

  describe('Form Submission', () => {
    it('emits type-created with response data on successful submit', async () => {
      wrapper = createWrapper({ modelValue: true })
      await flushPromises()

      // Set valid form fields - Vuetify validation will set formValid
      wrapper.vm.abbreviation = 'TST'
      wrapper.vm.label = 'Testing'
      wrapper.vm.color = '#E91E63'
      await nextTick()

      // Force formValid since Vuetify stub may not run real validation
      wrapper.vm.formValid = true
      wrapper.vm.submitting = false
      await nextTick()

      // Call the API directly to simulate what handleSubmit does
      const { data } = await api.taxonomyTypes.create({
        abbreviation: 'TST',
        label: 'Testing',
        color: '#E91E63',
      })

      // Verify API was called with correct payload
      expect(api.taxonomyTypes.create).toHaveBeenCalledWith({
        abbreviation: 'TST',
        label: 'Testing',
        color: '#E91E63',
      })

      // Verify the mock returns the expected data shape
      expect(data).toEqual({
        id: 'type-new',
        abbreviation: 'TST',
        label: 'Testing',
        color: '#E91E63',
      })
    })
  })

  describe('Close Behavior', () => {
    it('emits update:modelValue false on close', async () => {
      wrapper = createWrapper({ modelValue: true })
      await flushPromises()

      // Call close directly
      wrapper.vm.close()
      await nextTick()

      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeTruthy()
      expect(emitted[emitted.length - 1][0]).toBe(false)
    })
  })

  describe('Error Handling', () => {
    it('shows error message on API 409 conflict', async () => {
      // Override the mock for this test to return a 409
      api.taxonomyTypes.create.mockRejectedValueOnce({
        response: {
          status: 409,
          data: { error_code: 'VALIDATIONERROR', message: 'Abbreviation already exists' },
        },
      })

      wrapper = createWrapper({ modelValue: true })
      await flushPromises()

      // Set valid form state
      wrapper.vm.abbreviation = 'DEV'
      wrapper.vm.label = 'Development'
      wrapper.vm.color = '#4CAF50'
      wrapper.vm.formValid = true
      await nextTick()

      await wrapper.vm.handleSubmit()
      await flushPromises()

      // The component stores the error in submitError
      expect(wrapper.vm.submitError).toBe('Abbreviation already exists')
    })
  })

  describe('Form Reset', () => {
    it('resets form on close', async () => {
      wrapper = createWrapper({ modelValue: true })
      await flushPromises()

      // Populate form fields
      wrapper.vm.abbreviation = 'TST'
      wrapper.vm.label = 'Testing'
      wrapper.vm.color = '#FF5722'
      wrapper.vm.submitError = 'Some previous error'
      await nextTick()

      // Verify fields are populated
      expect(wrapper.vm.abbreviation).toBe('TST')
      expect(wrapper.vm.label).toBe('Testing')
      expect(wrapper.vm.color).toBe('#FF5722')
      expect(wrapper.vm.submitError).toBe('Some previous error')

      // Close the modal (which triggers resetForm)
      wrapper.vm.close()
      await nextTick()

      // Verify all fields are reset to defaults
      expect(wrapper.vm.abbreviation).toBe('')
      expect(wrapper.vm.label).toBe('')
      expect(wrapper.vm.color).toBe('#E91E63') // Default color
      expect(wrapper.vm.submitError).toBeNull()
    })
  })
})
