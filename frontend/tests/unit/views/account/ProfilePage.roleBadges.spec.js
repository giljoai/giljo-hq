/**
 * FE-9172: hide the Workspace (Owner) + Role (Admin) badge rows on hosted SaaS.
 *
 * Product boundary (2026-07-14): hosted SaaS is single-user / account-owner —
 * it must not present an Admin badge or Teams-oriented administration chrome.
 * CE is the self-hosted/operator edition where the badges are real, so they
 * stay visible there. Display-only: role="admin" and its guards are unchanged.
 *
 * Edition Scope: Both
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

// ------------------------------------------------------------------ Mocks --

vi.mock('@/services/api', () => ({
  apiClient: { post: vi.fn(), put: vi.fn(), get: vi.fn() },
  default: {
    auth: {
      updateUser: vi.fn().mockResolvedValue({ data: {} }),
    },
  },
}))

vi.mock('@/stores/user', () => ({
  useUserStore: vi.fn(() => ({
    currentUser: {
      id: 1,
      username: 'testuser',
      first_name: 'Test',
      last_name: 'User',
      email: 'user@example.com',
      role: 'admin',
    },
    currentOrg: { name: 'Test Workspace' },
    orgRole: 'owner',
  })),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: vi.fn(() => ({ showToast: vi.fn() })),
}))

vi.mock('@/components/common/RoleBadge.vue', () => ({
  default: { template: '<span data-test="role-badge" />' },
}))

// NOTE: no vi.mock of the saas/ email-change module here. This spec ships to
// CE (tests/unit/views/), where frontend/src/saas/ does not exist — a saas/
// reference would break the exported tree. The ADR-004 glob loader is a
// no-op in CE and side-effect-free here in SaaS mode (its only import,
// @/services/api, is mocked above; no seam is injected in this spec).

vi.mock('@/services/setupService', () => ({
  default: {
    checkEnhancedStatus: vi.fn().mockResolvedValue({ mode: 'ce' }),
  },
}))

// ------------------------------------------- Import after mocks are in place --
import { createRouter, createMemoryHistory } from 'vue-router'
import ProfilePage from '@/views/account/ProfilePage.vue'

// FE-9427: ProfilePage calls useRouter() -- after a successful password change
// it logs out and pushes /login. Without a router installed that returned
// `undefined`.
const authRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/login', name: 'Login', component: { template: '<div />' } },
  ],
})
import setupService from '@/services/setupService'

// ================================================================= Tests ===

describe('ProfilePage.vue — Workspace/Role badge edition visibility (FE-9172)', () => {
  let vuetify

  beforeEach(() => {
    vuetify = createVuetify({ components, directives })
  })

  async function mountPage(mode) {
    vi.mocked(setupService.checkEnhancedStatus).mockResolvedValue({ mode })
    const wrapper = mount(ProfilePage, {
      global: { plugins: [vuetify, authRouter] },
    })
    await flushPromises()
    return wrapper
  }

  it('CE mode: shows the Workspace/Role box with both badges', async () => {
    const wrapper = await mountPage('ce')

    expect(wrapper.find('[data-test="workspace-role-box"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Workspace')
    expect(wrapper.text()).toContain('Role')
    expect(wrapper.findAll('[data-test="role-badge"]').length).toBe(2)
  })

  it('SaaS mode: hides the Workspace/Role box and both badges', async () => {
    const wrapper = await mountPage('saas')

    expect(wrapper.find('[data-test="workspace-role-box"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-test="role-badge"]').length).toBe(0)
  })

  it('SaaS mode: profile form fields still render (only badges hide)', async () => {
    const wrapper = await mountPage('saas')

    expect(wrapper.find('[data-test="email-field"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="save-profile-btn"]').exists()).toBe(true)
  })
})
