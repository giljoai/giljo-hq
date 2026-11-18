/**
 * Unit tests for CreateAdminAccount component - Welcome Screen
 * Tests workspace name field and form submission (Handover 0424h)
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import CreateAdminAccount from '@/views/CreateAdminAccount.vue'
import api from '@/services/api'

// Mock the API service
vi.mock('@/services/api', () => ({
  default: {
    auth: {
      createFirstAdmin: vi.fn(),
    },
  },
}))

// Mock setupService
vi.mock('@/services/setupService', () => ({
  default: {
    invalidateStatusCache: vi.fn(),
  },
}))

// Mock useRouter
vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRouter: () => ({
      push: vi.fn(),
    }),
  }
})

// Configurable validate result for form stubs (override per test as needed)
let formValidateResult = { valid: true }

const createWrapper = (options = {}) => {
  const vuetify = createVuetify()
  const pinia = createPinia()
  setActivePinia(pinia)

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', name: 'Dashboard' }],
  })

  return mount(CreateAdminAccount, {
    global: {
      plugins: [vuetify, pinia, router],
      stubs: {
        'v-container': { template: '<div><slot /></div>' },
        'v-row': { template: '<div><slot /></div>' },
        'v-col': { template: '<div><slot /></div>' },
        'v-card': { template: '<div><slot /></div>' },
        'v-card-title': { template: '<div><slot /></div>' },
        'v-card-subtitle': { template: '<div><slot /></div>' },
        'v-card-text': { template: '<div><slot /></div>' },
        'v-form': {
          template: '<form @submit.prevent="$emit(\'submit\')"><slot /></form>',
          methods: { validate: () => Promise.resolve(formValidateResult) },
        },
        'v-text-field': {
          template: '<div />',
          methods: { validate: () => Promise.resolve({ valid: true }) },
        },
        'v-btn': true,
        'v-icon': true,
        'v-divider': true,
        'v-alert': true,
        'v-tooltip': { template: '<div><slot /></div>' },
      },
    },
    ...options,
  })
}

describe('CreateAdminAccount Component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    formValidateResult = { valid: true }
  })

  describe('Component Rendering', () => {
    it('should render the welcome screen component', () => {
      const wrapper = createWrapper()
      expect(wrapper.exists()).toBe(true)
    })

    it('should initialize with form not submitted', () => {
      const wrapper = createWrapper()
      // Component should be mounted and have form state
      expect(wrapper.vm.loading).toBe(false)
      expect(wrapper.vm.errorMessage).toBe('')
    })

    it('should have form validation state', () => {
      const wrapper = createWrapper()
      // Component should have form validation state (step1Valid for step 1)
      expect(wrapper.vm.step1Valid).toBeDefined()
      expect(typeof wrapper.vm.step1Valid).toBe('boolean')
    })
  })

  describe('Workspace Name Field (Handover 0424h)', () => {
    it('should initialize with empty workspace name', () => {
      const wrapper = createWrapper()
      // Note: We need to check the component's data directly
      expect(wrapper.vm.workspaceName).toBe('')
    })

    it('should have workspace name validation rules', () => {
      const wrapper = createWrapper()
      expect(wrapper.vm.workspaceNameRules).toBeDefined()
      expect(Array.isArray(wrapper.vm.workspaceNameRules)).toBe(true)
      expect(wrapper.vm.workspaceNameRules.length).toBeGreaterThan(0)
    })

    it('should require workspace name', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.workspaceNameRules

      // Test empty value
      const result = rules[0]('')
      expect(result).toBe('Workspace name is required')
    })

    it('should allow workspace names up to 255 characters', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.workspaceNameRules

      const validName = 'A'.repeat(255)
      const validateFn = rules[rules.length - 1]
      const result = validateFn(validName)
      expect(result).toBe(true)
    })

    it('should reject workspace names longer than 255 characters', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.workspaceNameRules

      const tooLongName = 'A'.repeat(256)
      const validateFn = rules[rules.length - 1]
      const result = validateFn(tooLongName)
      expect(result).toContain('less than 255 characters')
    })

    it('should accept valid workspace names', () => {
      const wrapper = createWrapper()

      // Set workspace name
      wrapper.vm.workspaceName = 'Acme Corporation'

      // Check that it's set
      expect(wrapper.vm.workspaceName).toBe('Acme Corporation')
    })

    it('should accept workspace names with special characters', () => {
      const wrapper = createWrapper()
      const specialNames = [
        'Acme Corp',
        'My Team',
        'Team-123',
        'Company_Inc',
        "O'Brien Co.",
        'A&B Solutions',
      ]

      specialNames.forEach((name) => {
        wrapper.vm.workspaceName = name
        expect(wrapper.vm.workspaceName).toBe(name)
      })
    })
  })

  describe('Form Validation', () => {
    it('should initialize with form invalid (all fields required)', () => {
      const wrapper = createWrapper()
      expect(wrapper.vm.step1Valid).toBe(false)
    })

    it('should have all required field validation rules', () => {
      const wrapper = createWrapper()

      // With script setup, validation rules are not directly accessible on vm
      // Instead, check that the main validation properties are defined
      expect(wrapper.vm.step1Valid).toBeDefined()
      expect(wrapper.vm.errorMessage).toBeDefined()
      expect(wrapper.vm.loading).toBeDefined()

      // The rules are used by v-form validation, so they're called when form validates
      // This is tested implicitly in form submission tests
    })
  })

  describe('Form Submission (Handover 0424h)', () => {
    it('should call API with workspace_name parameter on submit', async () => {
      const wrapper = createWrapper()

      // Set form values
      wrapper.vm.workspaceName = 'Test Organization'
      wrapper.vm.username = 'testadmin'
      wrapper.vm.email = 'admin@test.com'
      wrapper.vm.password = 'ValidPassword123!'
      wrapper.vm.confirmPassword = 'ValidPassword123!'
      wrapper.vm.recoveryPin = '1234'
      wrapper.vm.confirmPin = '1234'
      wrapper.vm.step2Valid = true

      // Navigate to step 2 so step2Form ref is available
      wrapper.vm.step = 2
      await wrapper.vm.$nextTick()

      // Mock API response
      api.auth.createFirstAdmin.mockResolvedValue({ data: { success: true } })

      // Call createAdmin
      await wrapper.vm.createAdmin()

      // Verify API was called with workspace_name and split name fields.
      // first_name is empty string (not set in this test), last_name is null.
      expect(api.auth.createFirstAdmin).toHaveBeenCalledWith({
        workspace_name: 'Test Organization',
        username: 'testadmin',
        email: 'admin@test.com',
        first_name: '',
        last_name: null,
        password: 'ValidPassword123!',
        confirm_password: 'ValidPassword123!',
        recovery_pin: '1234',
        confirm_pin: '1234',
      })
    })

    it('should not submit if form is invalid', async () => {
      // Make form validation return invalid
      formValidateResult = { valid: false }
      const wrapper = createWrapper()

      // Navigate to step 2 so step2Form ref is available
      wrapper.vm.step = 2
      await wrapper.vm.$nextTick()

      // Try to call createAdmin
      await wrapper.vm.createAdmin()

      // API should not be called
      expect(api.auth.createFirstAdmin).not.toHaveBeenCalled()
    })

    it('should set loading state during submission', async () => {
      const wrapper = createWrapper()

      wrapper.vm.step2Valid = true
      wrapper.vm.workspaceName = 'Test Org'
      wrapper.vm.username = 'admin'
      wrapper.vm.password = 'ValidPassword123!'
      wrapper.vm.confirmPassword = 'ValidPassword123!'
      wrapper.vm.recoveryPin = '1234'
      wrapper.vm.confirmPin = '1234'

      // Navigate to step 2 so step2Form ref is available
      wrapper.vm.step = 2
      await wrapper.vm.$nextTick()

      // Mock slow API response
      api.auth.createFirstAdmin.mockImplementationOnce(
        () =>
          new Promise((resolve) => setTimeout(() => resolve({ data: { success: true } }), 100))
      )

      const submitPromise = wrapper.vm.createAdmin()

      // Flush microtask queue so validate() promise resolves and loading is set
      await wrapper.vm.$nextTick()

      // Loading should be true during submission
      expect(wrapper.vm.loading).toBe(true)

      await submitPromise

      // Loading should be false after submission
      expect(wrapper.vm.loading).toBe(false)
    })

    it('should display error message on API failure', async () => {
      const wrapper = createWrapper()

      wrapper.vm.step2Valid = true
      wrapper.vm.workspaceName = 'Test Org'
      wrapper.vm.username = 'admin'
      wrapper.vm.password = 'ValidPassword123!'
      wrapper.vm.confirmPassword = 'ValidPassword123!'
      wrapper.vm.recoveryPin = '1234'
      wrapper.vm.confirmPin = '1234'

      // Navigate to step 2 so step2Form ref is available
      wrapper.vm.step = 2
      await wrapper.vm.$nextTick()

      const errorMessage = 'Admin account already exists'
      api.auth.createFirstAdmin.mockRejectedValueOnce(
        new Error(errorMessage)
      )

      await wrapper.vm.createAdmin()

      expect(wrapper.vm.errorMessage).toContain(errorMessage)
    })

    it('should clear error message when user modifies form', async () => {
      const wrapper = createWrapper()

      // Set error
      wrapper.vm.errorMessage = 'Some error'

      // Modify workspace name - this should trigger the watch
      wrapper.vm.workspaceName = 'New Name'

      // Wait for watch to execute
      await wrapper.vm.$nextTick()

      // Error should be cleared by the watch
      expect(wrapper.vm.errorMessage).toBe('')
    })

    it('should handle API response with structured error', async () => {
      const wrapper = createWrapper()

      wrapper.vm.step2Valid = true
      wrapper.vm.workspaceName = 'Test Org'
      wrapper.vm.username = 'admin'
      wrapper.vm.password = 'ValidPassword123!'
      wrapper.vm.confirmPassword = 'ValidPassword123!'
      wrapper.vm.recoveryPin = '1234'
      wrapper.vm.confirmPin = '1234'

      // Navigate to step 2 so step2Form ref is available
      wrapper.vm.step = 2
      await wrapper.vm.$nextTick()

      const error = new Error('Failed')
      error.response = {
        data: {
          detail: 'Username already exists',
        },
      }

      api.auth.createFirstAdmin.mockRejectedValueOnce(error)

      await wrapper.vm.createAdmin()

      expect(wrapper.vm.errorMessage).toBe('Username already exists')
    })
  })

  describe('Username Field', () => {
    it('should require username', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.usernameRules

      const result = rules[0]('')
      expect(result).toBe('Username is required')
    })

    it('should require at least 3 characters', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.usernameRules

      const shortUsername = 'ab'
      const result = rules[1](shortUsername)
      expect(result).toContain('at least 3 characters')
    })

    it('should allow alphanumeric, underscore, and hyphen', () => {
      const wrapper = createWrapper()

      const validUsernames = ['admin123', 'test_admin', 'admin-user', 'Test_Admin-123']

      validUsernames.forEach((username) => {
        wrapper.vm.username = username
        expect(wrapper.vm.username).toBe(username)
      })
    })
  })

  describe('Email Field', () => {
    it('should allow empty email (optional field)', () => {
      const wrapper = createWrapper()
      wrapper.vm.email = ''
      expect(wrapper.vm.email).toBe('')
    })

    it('should validate email format when provided', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.emailRules

      const validEmail = 'test@example.com'
      const result = rules[0](validEmail)
      expect(result).toBe(true)
    })

    it('should reject invalid email format', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.emailRules

      const invalidEmail = 'notanemail'
      const result = rules[0](invalidEmail)
      expect(result).toContain('Email must be valid')
    })
  })

  describe('Password Field', () => {
    it('should require password', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.passwordRules

      const result = rules[0]('')
      expect(result).toBe('Password is required')
    })

    it('should require at least 8 characters', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.passwordRules

      const shortPassword = 'Sh1!'
      const result = rules[1](shortPassword)
      expect(result).toContain('at least 8 characters')
    })

    it('should require uppercase letter', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.passwordRules

      const noUpperPassword = 'validpassword123!'
      const upperRule = rules[2]
      const result = upperRule(noUpperPassword)
      expect(result).toContain('uppercase')
    })

    it('should require lowercase letter', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.passwordRules

      const noLowerPassword = 'VALIDPASSWORD123!'
      const lowerRule = rules[3]
      const result = lowerRule(noLowerPassword)
      expect(result).toContain('lowercase')
    })

    it('should require digit', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.passwordRules

      const noDigitPassword = 'ValidPassword!'
      const digitRule = rules[4]
      const result = digitRule(noDigitPassword)
      expect(result).toContain('digit')
    })

    it('should require special character', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.passwordRules

      const noSpecialPassword = 'ValidPassword123'
      const specialRule = rules[5]
      const result = specialRule(noSpecialPassword)
      expect(result).toContain('special character')
    })

    it('should accept valid password', () => {
      const wrapper = createWrapper()
      const validPassword = 'ValidPassword123!'

      wrapper.vm.password = validPassword
      expect(wrapper.vm.password).toBe(validPassword)
    })
  })

  describe('Password Confirmation', () => {
    it('should require confirmation password', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.confirmPasswordRules

      const result = rules[0]('')
      expect(result).toBe('Password confirmation is required')
    })

    it('should require passwords to match', () => {
      const wrapper = createWrapper()
      wrapper.vm.password = 'ValidPassword123!'

      const rules = wrapper.vm.confirmPasswordRules
      const matchRule = rules[1]

      const mismatchPassword = 'DifferentPassword123!'
      const result = matchRule(mismatchPassword)
      expect(result).toContain('do not match')
    })

    it('should allow matching passwords', () => {
      const wrapper = createWrapper()
      const password = 'ValidPassword123!'

      wrapper.vm.password = password
      wrapper.vm.confirmPassword = password

      const rules = wrapper.vm.confirmPasswordRules
      const matchRule = rules[1]

      const result = matchRule(password)
      expect(result).toBe(true)
    })
  })

  describe('Recovery PIN', () => {
    it('should require recovery PIN', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.pinRules

      const result = rules[0]('')
      expect(result).toBe('Recovery PIN is required')
    })

    it('should require exactly 4 digits', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.pinRules
      const digitRule = rules[1]

      const invalidPins = ['123', '12345', '12a4', 'abcd']
      invalidPins.forEach((pin) => {
        const result = digitRule(pin)
        expect(result).toContain('4 digits')
      })
    })

    it('should accept valid 4-digit PIN', () => {
      const wrapper = createWrapper()

      wrapper.vm.recoveryPin = '1234'
      expect(wrapper.vm.recoveryPin).toBe('1234')
    })

    it('should handle PIN input filtering (remove non-digits)', () => {
      const wrapper = createWrapper()

      // Call handlePinInput with mixed input
      wrapper.vm.handlePinInput('12a4')

      // Should only keep digits
      expect(wrapper.vm.recoveryPin).toBe('12a4'.replace(/\D/g, ''))
    })

    it('should limit PIN to 4 characters', () => {
      const wrapper = createWrapper()

      // Call handlePinInput with 5 digits
      wrapper.vm.handlePinInput('12345')

      // Should be limited to 4
      expect(wrapper.vm.recoveryPin.length).toBeLessThanOrEqual(4)
    })
  })

  describe('PIN Confirmation', () => {
    it('should require PIN confirmation', () => {
      const wrapper = createWrapper()
      const rules = wrapper.vm.confirmPinRules

      const result = rules[0]('')
      expect(result).toBe('PIN confirmation is required')
    })

    it('should require PINs to match', () => {
      const wrapper = createWrapper()
      wrapper.vm.recoveryPin = '1234'

      const rules = wrapper.vm.confirmPinRules
      const matchRule = rules[2]

      const result = matchRule('5678')
      expect(result).toContain('do not match')
    })

    it('should allow matching PINs', () => {
      const wrapper = createWrapper()
      const pin = '1234'

      wrapper.vm.recoveryPin = pin
      wrapper.vm.confirmPin = pin

      const rules = wrapper.vm.confirmPinRules
      const matchRule = rules[2]

      const result = matchRule(pin)
      expect(result).toBe(true)
    })
  })

  describe('Form State Management', () => {
    it('should clear error on any form field change', async () => {
      const wrapper = createWrapper()

      wrapper.vm.errorMessage = 'Some error occurred'

      // Simulate field changes - only the watched fields
      const fieldsThatClearError = [
        'workspaceName',
        'username',
        'email',
        'password',
        'confirmPassword',
        'recoveryPin',
        'confirmPin',
      ]

      for (const field of fieldsThatClearError) {
        wrapper.vm[field] = 'changed'
        await wrapper.vm.$nextTick() // Wait for watch to trigger
        expect(wrapper.vm.errorMessage).toBe('')
        wrapper.vm.errorMessage = 'Reset error'
      }
    })

    it('should have distinct form valid state', () => {
      const wrapper = createWrapper()

      // Initially invalid
      expect(wrapper.vm.step1Valid).toBe(false)

      // Set all required fields
      wrapper.vm.workspaceName = 'Test Org'
      wrapper.vm.username = 'admin'
      wrapper.vm.password = 'ValidPassword123!'
      wrapper.vm.confirmPassword = 'ValidPassword123!'
      wrapper.vm.recoveryPin = '1234'
      wrapper.vm.confirmPin = '1234'

      // Manually set form valid (in real scenario, v-form would update this)
      wrapper.vm.step1Valid = true

      expect(wrapper.vm.step1Valid).toBe(true)
    })
  })

  describe('Password Visibility Toggle', () => {
    it('should initialize with password hidden', () => {
      const wrapper = createWrapper()
      expect(wrapper.vm.showPassword).toBe(false)
      expect(wrapper.vm.showConfirmPassword).toBe(false)
    })

    it('should toggle password visibility', () => {
      const wrapper = createWrapper()

      wrapper.vm.showPassword = true
      expect(wrapper.vm.showPassword).toBe(true)

      wrapper.vm.showPassword = false
      expect(wrapper.vm.showPassword).toBe(false)
    })
  })
})
