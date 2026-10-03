/**
 * SaaS-only account UI appears only on a positive SaaS mode.
 *
 * An unresolved or unexpected mode ('unknown', '', a typo) must render the
 * account shell without the SaaS-only Connected Accounts tab.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

import AccountShell from '@/views/account/AccountShell.vue'

const checkEnhancedStatus = vi.fn()
vi.mock('@/services/setupService', () => ({
  default: { checkEnhancedStatus: (...args) => checkEnhancedStatus(...args) },
}))

const Empty = { template: '<div />' }

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/account',
        component: AccountShell,
        children: [
          { path: 'profile', name: 'AccountProfile', component: Empty },
          { path: 'billing', name: 'AccountBilling', component: Empty },
          { path: 'danger', name: 'AccountDanger', component: Empty },
          { path: 'connected', name: 'AccountConnectedAccounts', component: Empty },
        ],
      },
    ],
  })
}

async function mountShell(mode) {
  checkEnhancedStatus.mockResolvedValue({ mode })
  const router = makeRouter()
  await router.push('/account/profile')
  await router.isReady()
  const wrapper = mount(AccountShell, {
    global: { plugins: [createVuetify({ components, directives }), router] },
  })
  await flushPromises()
  return wrapper
}

describe('AccountShell edition gate', () => {
  beforeEach(() => {
    checkEnhancedStatus.mockReset()
  })

  it.each(['unknown', '', 'sass'])('mode %j shows no SaaS-only Connected Accounts tab', async (mode) => {
    const wrapper = await mountShell(mode)

    expect(wrapper.find('[data-test="account-connected-tab"]').exists()).toBe(false)
  })

  it('mode ce shows no Connected Accounts tab', async () => {
    const wrapper = await mountShell('ce')

    expect(wrapper.find('[data-test="account-connected-tab"]').exists()).toBe(false)
  })

  it('mode saas shows the Connected Accounts tab', async () => {
    const wrapper = await mountShell('saas')

    expect(wrapper.find('[data-test="account-connected-tab"]').exists()).toBe(true)
  })
})
