import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  mode: { value: 'ce' },
  integShow: { fn: () => true },
  agentShow: { fn: () => false },
  dismissInteg: vi.fn(),
  dismissAgent: vi.fn(),
  git: { value: false },
  serena: { value: false },
  resolved: { value: false },
  dist: { value: { active: 2 } },
  refreshDeferred: { value: null },
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getGiljoMode: vi.fn(() => h.mode.value),
  },
}))

vi.mock('@/composables/useTutorialState', async (importOriginal) => ({
  ...(await importOriginal()),
  isActivateBreadcrumbArmed: () => false,
  clearActivateBreadcrumb: vi.fn(),
}))

vi.mock('@/composables/useOnboardingReminders', () => ({
  useOnboardingReminders: () => ({
    showIntegrationReminder: { value: (hp) => h.integShow.fn(hp) },
    showAgentReminder: { value: (hc) => h.agentShow.fn(hc) },
    dismissIntegrationReminder: h.dismissInteg,
    dismissAgentReminder: h.dismissAgent,
  }),
}))

vi.mock('@/composables/useIntegrationStatus', async () => {
  const { ref } = await import('vue')
  return {
    useIntegrationStatus: () => {
      const gitEnabled = ref(h.git.value)
      const serenaEnabled = ref(h.serena.value)
      const resolved = ref(h.resolved.value)
      return {
        gitEnabled,
        serenaEnabled,
        resolved,
        loading: ref(false),
        refresh: () =>
          h.refreshDeferred.value.promise.then(
            ({ git, serena, failed }) => {
              if (failed) return
              gitEnabled.value = git
              serenaEnabled.value = serena
              resolved.value = true
            },
          ),
      }
    },
  }
})

vi.mock('@/services/api', () => {
  const apiObj = {
    stats: {
      getDashboard: vi.fn(() =>
        Promise.resolve({ data: { project_status_dist: h.dist.value } }),
      ),
    },
    notifications: { list: vi.fn(), markRead: vi.fn(), markDismissed: vi.fn() },
  }
  return { default: apiObj, api: apiObj }
})

import SystemStatusBanner from './SystemStatusBanner.vue'
import { useNotificationStore } from '@/stores/notifications'
import { useUserStore } from '@/stores/user'
import { useProductStore } from '@/stores/products'

const globalStubs = { 'v-icon': { template: '<i class="v-icon"><slot /></i>' } }
const NUDGE = '[data-testid="onboarding-integration-banner"]'

function makeDeferred() {
  let settle
  const promise = new Promise((res) => {
    settle = res
  })
  return { promise, settle }
}

async function mountPending() {
  h.refreshDeferred.value = makeDeferred()
  const wrapper = mount(SystemStatusBanner, { global: { stubs: globalStubs } })
  useNotificationStore().notifications = []
  useUserStore().currentUser = { role: 'admin' }
  useProductStore().activeProduct = { id: 'p1' }
  await flushPromises()
  return wrapper
}

async function settleWith(payload) {
  h.refreshDeferred.value.settle(payload)
  await flushPromises()
}

describe('SystemStatusBanner integration nudge — resolved-status gating (FE-9233)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.push.mockClear()
    h.dismissInteg.mockClear()
    h.integShow.fn = () => true
    h.agentShow.fn = () => false
    h.git.value = false
    h.serena.value = false
    h.resolved.value = false
    h.dist.value = { active: 2 }
  })

  it('THE FLASH: the nudge is absent while integration status is still pending', async () => {
    const wrapper = await mountPending()
    expect(wrapper.find(NUDGE).exists()).toBe(false)
  })

  it('stays absent through resolution on a box where both integrations are enabled', async () => {
    const wrapper = await mountPending()
    expect(wrapper.find(NUDGE).exists()).toBe(false)
    await settleWith({ git: true, serena: true })
    expect(wrapper.find(NUDGE).exists()).toBe(false)
  })

  it('LOAD-BEARING: still appears after resolution when integrations are genuinely off', async () => {
    const wrapper = await mountPending()
    expect(wrapper.find(NUDGE).exists()).toBe(false)
    await settleWith({ git: false, serena: false })
    expect(wrapper.find(NUDGE).exists()).toBe(true)
  })

  it('LOAD-BEARING: appears after resolution when only one integration is on', async () => {
    const wrapper = await mountPending()
    await settleWith({ git: true, serena: false })
    expect(wrapper.find(NUDGE).exists()).toBe(true)
  })

  it('stays absent when the status fetch fails (never nag from unproven data)', async () => {
    const wrapper = await mountPending()
    await settleWith({ failed: true })
    expect(wrapper.find(NUDGE).exists()).toBe(false)
  })

  it('dismissal cadence is untouched: dismiss still persists and hides the row', async () => {
    const wrapper = await mountPending()
    await settleWith({ git: false, serena: false })
    expect(wrapper.find(NUDGE).exists()).toBe(true)

    const dismiss = wrapper.find(`${NUDGE} [data-testid="banner-dismiss"]`)
    const btn = dismiss.exists()
      ? dismiss
      : wrapper.find(NUDGE).findAll('button').at(-1)
    await btn.trigger('click')
    await flushPromises()

    expect(h.dismissInteg).toHaveBeenCalledTimes(1)
    expect(wrapper.find(NUDGE).exists()).toBe(false)
  })
})
