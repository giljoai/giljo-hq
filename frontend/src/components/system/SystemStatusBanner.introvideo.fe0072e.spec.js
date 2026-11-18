import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ push: vi.fn(), writes: vi.fn() }))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))
vi.mock('@/services/configService', () => ({
  default: { fetchConfig: vi.fn().mockResolvedValue({}), getGiljoMode: vi.fn(() => 'ce') },
}))
vi.mock('@/composables/useTutorialState', async (importOriginal) => ({
  ...(await importOriginal()),
  isActivateBreadcrumbArmed: () => false,
  clearActivateBreadcrumb: vi.fn(),
}))
vi.mock('@/composables/useOnboardingReminders', () => ({
  useOnboardingReminders: () => ({
    showIntegrationReminder: { value: () => false },
    showAgentReminder: { value: () => false },
    dismissIntegrationReminder: vi.fn(),
    dismissAgentReminder: vi.fn(),
  }),
}))
vi.mock('@/composables/useIntegrationStatus', async () => {
  const { ref } = await import('vue')
  return {
    useIntegrationStatus: () => ({
      gitEnabled: ref(true),
      resolved: ref(true),
      loading: ref(false),
      refresh: vi.fn().mockResolvedValue(),
    }),
  }
})
vi.mock('@/stores/websocket', () => ({ useWebSocketStore: () => ({ on: () => () => {} }) }))
vi.mock('@/services/api', () => {
  const apiObj = {
    stats: { getDashboard: vi.fn(() => Promise.resolve({ data: { project_status_dist: {} } })) },
    notifications: { list: vi.fn(), markRead: vi.fn(), markDismissed: h.writes },
    threads: { list: vi.fn(() => Promise.resolve({ data: { threads: [] } })) },
    templateProposals: { count: vi.fn(() => Promise.resolve({ data: { count: 0 } })), list: vi.fn() },
  }
  return { default: apiObj, api: apiObj }
})

import SystemStatusBanner from './SystemStatusBanner.vue'
import { useUserStore } from '@/stores/user'

const stubs = { 'v-icon': { template: '<i class="v-icon"><slot /></i>' } }


const OLD = '2025-06-01T00:00:00Z'
const NEW = '2099-01-01T00:00:00Z'

const mem = new Map()
function installMemoryStorage() {
  mem.clear()
  window.localStorage = {
    getItem: (k) => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => mem.set(k, String(v)),
    removeItem: (k) => mem.delete(k),
    clear: () => mem.clear(),
  }
}

async function mountBanner(user, dismissed = []) {
  mem.set('giljo_banner_dismissals_user-1', JSON.stringify(dismissed))
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia], stubs } })
  useUserStore().currentUser = { id: 'user-1', role: 'admin', ...user }
  await flushPromises()
  await flushPromises()
  return wrapper
}
const row = (w) => w.find('[data-testid="intro-video-banner"]')

describe('SystemStatusBanner start-video row (FE-0072e)', () => {
  beforeEach(() => {
    h.push.mockClear()
    h.writes.mockClear()
    installMemoryStorage()
  })

  it('shows the words and the button for an account that existed before the release', async () => {
    const w = await mountBanner({ created_at: OLD, intro_video_seen: true })
    expect(row(w).exists()).toBe(true)
    expect(row(w).text()).toContain(
      'New: a getting started guide and a short video are in Tools, Learning. Get familiar with Giljo HQ.',
    )
    expect(w.get('[data-testid="intro-video-banner-cta"]').text()).toBe('Take a look')
  })

  it('is the strip\'s own nudge row, with the same classes and the Gil avatar', async () => {
    const w = await mountBanner({ created_at: OLD, intro_video_seen: true })
    expect(row(w).classes()).toContain('system-banner-alert')
    expect(row(w).find('img.system-banner-alert__avatar').exists()).toBe(true)
    expect(w.get('[data-testid="intro-video-banner-cta"]').classes()).toContain('system-banner-btn--cta')
  })

  it('a new account never sees it', async () => {
    const w = await mountBanner({ created_at: NEW, intro_video_seen: true })
    expect(row(w).exists()).toBe(false)
  })

  it('an account that has not seen the video (pop-up pending) never sees it', async () => {
    const w = await mountBanner({ created_at: OLD, intro_video_seen: false })
    expect(row(w).exists()).toBe(false)
  })

  it('no created_at, no row', async () => {
    const w = await mountBanner({ intro_video_seen: true })
    expect(row(w).exists()).toBe(false)
  })

  it('the button goes to Tools, Learning, and the row is handled', async () => {
    const w = await mountBanner({ created_at: OLD, intro_video_seen: true })
    expect(h.push).not.toHaveBeenCalled()
    await w.get('[data-testid="intro-video-banner-cta"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({ path: '/tools', query: { tab: 'learning' } })
    await flushPromises()
    expect(row(w).exists()).toBe(false)
  })

  it('close hides it for good, with nothing written to the server', async () => {
    const w = await mountBanner({ created_at: OLD, intro_video_seen: true })
    await w.get('[data-testid="intro-video-banner-dismiss"]').trigger('click')
    await flushPromises()
    expect(row(w).exists()).toBe(false)
    expect(h.writes).not.toHaveBeenCalled()
    expect(mem.get('giljo_banner_dismissals_user-1')).toContain('intro-video:banner')
    const again = await mountBanner({ created_at: OLD, intro_video_seen: true }, ['intro-video:banner'])
    expect(row(again).exists()).toBe(false)
  })

  it('there is no getting-started row any more: an old "hidden" mark in this browser changes nothing', async () => {
    const w = await mountBanner({ created_at: OLD, intro_video_seen: true }, ['start-list:hidden'])
    expect(w.find('[data-testid="start-list-banner"]').exists()).toBe(false)
    expect(row(w).exists()).toBe(true)
  })
})
