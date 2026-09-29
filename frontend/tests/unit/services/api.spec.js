/**
 * API Service Tests - Prompts Namespace
 * Handover 0344: CLI Mode Play Button API Fix
 *
 * Tests for api.prompts.implementation() method
 * Note: The api service is mocked in tests/setup.js
 */
import { describe, it, expect } from 'vitest'
import { api } from '@/services/api'

describe('api.js - Prompts Service', () => {
  describe('prompts namespace', () => {
    it('prompts namespace exists', () => {
      expect(api.prompts).toBeDefined()
      expect(typeof api.prompts).toBe('object')
    })

    it('prompts has all required methods', () => {
      // Verify all methods exist (mocked in tests/setup.js)
      expect(typeof api.prompts.staging).toBe('function')
      expect(typeof api.prompts.agentPrompt).toBe('function')
      expect(typeof api.prompts.implementation).toBe('function')
    })
  })

  describe('prompts.implementation() - Handover 0344', () => {
    it('prompts.implementation method exists and is a function', () => {
      expect(api.prompts.implementation).toBeDefined()
      expect(typeof api.prompts.implementation).toBe('function')
    })

    it('prompts.implementation returns a promise when called', async () => {
      const result = api.prompts.implementation('test-project-id')
      expect(result).toBeInstanceOf(Promise)

      // Verify the mock resolves correctly
      const response = await result
      expect(response.data).toBeDefined()
      expect(response.data.prompt).toBeDefined()
    })

    it('prompts.implementation returns implementation prompt data', async () => {
      const response = await api.prompts.implementation('test-project-id')

      // Verify structure matches expected response from backend
      expect(response.data.prompt).toBe('Mock implementation prompt')
      expect(response.data.agent_count).toBe(3)
    })

    it('prompts.implementation can be called with different project IDs', async () => {
      const projectIds = ['proj-1', 'proj-2', 'proj-uuid-123']

      for (const projectId of projectIds) {
        const response = await api.prompts.implementation(projectId)
        expect(response.data).toBeDefined()
        expect(api.prompts.implementation).toHaveBeenCalledWith(projectId)
      }
    })
  })

  describe('prompts methods - Consistency Check', () => {
    it('all prompts methods are functions', () => {
      const methods = Object.keys(api.prompts)

      // Should have 8 methods (staging, execution, agentPrompt, implementation,
      // orchestrator + FE-6165f chainStaging, chainImplementation
      // + FE-9629 chainMember — one chain member's own orchestrator prompt).
      // FE-9655a retired termination with the Stop project row action.
      expect(methods.length).toBe(8)
      expect(api.prompts.termination).toBeUndefined()
      expect(api.prompts.chainStaging).toBeDefined()
      expect(api.prompts.chainImplementation).toBeDefined()
      expect(api.prompts.chainMember).toBeDefined()

      // All should be functions
      methods.forEach((method) => {
        expect(typeof api.prompts[method]).toBe('function')
      })
    })

    it('implementation method follows the same pattern as agentPrompt', async () => {
      // Both should return promises that resolve to response objects
      const implementationResult = await api.prompts.implementation('test-id')
      const agentPromptResult = await api.prompts.agentPrompt('test-id')

      expect(implementationResult.data).toBeDefined()
      expect(agentPromptResult.data).toBeDefined()
      expect(implementationResult.data.prompt).toBeDefined()
      expect(agentPromptResult.data.prompt).toBeDefined()
    })
  })
})
