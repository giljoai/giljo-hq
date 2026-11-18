import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), query: {}, list: null, fail: false, save: vi.fn() }))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push, replace: h.replace, currentRoute: { value: { query: h.query } } }),
  useRoute: () => ({ query: h.query }),
}))
vi.mock('@/services/api', () => ({
  default: {
    onboarding: {
      startList: vi.fn(async () => {
        if (h.fail) throw new Error('down')
        return { data: h.list }
      }),
    },
  },
}))
vi.mock('@/stores/websocket', () => ({ useWebSocketStore: () => ({ on: () => () => {}, off: () => {} }) }))
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: { id: 'u-1' }, updateSetupState: (...a) => h.save(...a) }),
}))
vi.mock('@/services/setupService', () => ({ default: { getGitSettings: vi.fn().mockResolvedValue({ settings: { enabled: false } }) } }))
vi.mock('@/components/TemplateManager.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/ApiKeyManager.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/ConnectedAppsManager.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/AgentExport.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/settings/ContextPriorityConfig.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/tools/ToolsConnectDirectory.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/settings/integrations/GitIntegrationCard.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/settings/BannerPreferencesCard.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/settings/BellPreferencesCard.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/settings/PopoutPreferencesCard.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/settings/ToastPreferencesCard.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/common/BaseDialog.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/onboarding/VideosLibraryDialog.vue', () => ({
  default: {
    name: 'VideosLibraryDialog',
    props: ['modelValue'],
    emits: ['close', 'open-tour'],
    template: '<div data-testid="library-stub" :data-open="String(modelValue)" />',
  },
}))

import ToolsView from '@/views/ToolsView.vue'
import { useGuideStore } from '@/stores/guide'
import { startListPayload } from '../../tests/helpers/startListRows'

const stubs = {
  'v-container': { template: '<div><slot /></div>' },
  'v-icon': { template: '<i><slot /></i>' },
  'v-img': { template: '<span />' },
  'v-window': { props: ['modelValue'], template: '<div :data-tab="modelValue"><slot /></div>' },
  'v-window-item': { template: '<div><slot /></div>' },
}
const payload = (n) => {
  const keys = ['tool_connected', 'skills_installed', 'product_exists', 'project_created', 'project_staged', 'project_built']
  return startListPayload(Object.fromEntries(keys.map((k, i) => [k, i < n ? { done: true } : {}])))
}

async function mountTools() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const w = mount(ToolsView, { global: { plugins: [pinia], stubs } })
  await flushPromises()
  return { w, pinia }
}
const card = (w, name) => w.find(`[data-testid="learning-card-${name}"]`)
const tab = (w) => w.find('[data-testid="learning-settings-tab"]')

describe('Tools > Learning: the tab', () => {
  beforeEach(() => {
    h.push.mockClear()
    h.replace.mockClear()
    h.query = {}
    h.fail = false
    h.list = payload(2)
  })

  it('is labelled "Learning" and the old "Startup" label is gone', async () => {
    const { w } = await mountTools()
    expect(tab(w).text()).toMatch(/Learning$/)
    expect(w.find('[data-testid="startup-settings-tab"]').exists()).toBe(false)
    expect(w.findAll('.pill-toggle').map((b) => b.text()).join(' ')).not.toContain('Startup')
  })

  it('?tab=learning lands on it', async () => {
    h.query = { tab: 'learning' }
    const { w } = await mountTools()
    expect(w.find('[data-tab]').attributes('data-tab')).toBe('learning')
  })

  it('the old address ?tab=startup still lands on it', async () => {
    h.query = { tab: 'startup' }
    const { w } = await mountTools()
    expect(w.find('[data-tab]').attributes('data-tab')).toBe('learning')
  })

  it('has a heading and one line under it', async () => {
    const { w } = await mountTools()
    const header = w.find('[data-testid="learning-cards"]').element.previousElementSibling
    expect(header.querySelector('h2').textContent).toBe('Learning')
    expect(header.querySelector('p').textContent.length).toBeGreaterThan(10)
  })
})

describe('Tools > Learning: exactly four cards', () => {
  beforeEach(() => {
    h.push.mockClear()
    h.query = {}
    h.fail = false
    h.list = payload(2)
  })

  it('Getting started checklist, Connect a tool, Videos and animations, User guide, in that order', async () => {
    const { w } = await mountTools()
    expect(w.findAll('.learning-card').map((c) => c.find('.learning-card-title').text())).toEqual([
      'Getting started checklist',
      'Connect a tool',
      'Videos and animations',
      'User guide',
    ])
  })

  it('each card has an icon in the tinted rounded square', async () => {
    const { w } = await mountTools()
    const icons = w.findAll('.learning-card .learning-card-icon')
    expect(icons).toHaveLength(4)
    for (const i of icons) {
      expect(i.attributes('style')).toMatch(/background: var\(--agent-[a-z]+-tinted\)/)
      expect(i.find('i').text()).toMatch(/^mdi-/)
    }
  })

  it('the old cards "Learning" and "How to get going" are not cards any more', async () => {
    const { w } = await mountTools()
    expect(w.find('[data-testid="startup-card-intro-video"]').exists()).toBe(false)
    expect(w.findAll('.learning-card-title').map((t) => t.text())).not.toContain('Learning')
    expect(w.findAll('.learning-card-title').map((t) => t.text())).not.toContain('How to get going')
  })

  it('Getting started checklist turns the pane back on and goes nowhere; the count shows', async () => {
    const { w, pinia } = await mountTools()
    expect(card(w, 'getting-started').text()).toContain('2 of 6 done')
    const turnOn = vi.spyOn(useGuideStore(pinia), 'turnOn').mockResolvedValue(true)
    await card(w, 'getting-started').trigger('click')
    expect(turnOn).toHaveBeenCalledTimes(1)
    expect(h.push).not.toHaveBeenCalled()
  })

  it('a refused save of the checklist card says so in plain words, and pressing again retries', async () => {
    h.save.mockReset()
    h.save.mockRejectedValueOnce(Object.assign(new Error('Too many requests'), { response: { status: 429 } }))
    const { w } = await mountTools()
    expect(w.find('[data-testid="learning-card-error"]').exists()).toBe(false)
    await card(w, 'getting-started').trigger('click')
    await flushPromises()
    const err = w.find('[data-testid="learning-card-error"]')
    expect(err.exists()).toBe(true)
    expect(err.attributes('role')).toBe('alert')
    expect(err.text()).toBe('Could not bring the guide back. Please try again.')
    h.save.mockResolvedValueOnce({ guide_closed: false })
    await card(w, 'getting-started').trigger('click')
    await flushPromises()
    expect(h.save).toHaveBeenCalledTimes(2)
    expect(w.find('[data-testid="learning-card-error"]').exists()).toBe(false)
  })

  it('says "All 6 done" at the end and shows no count when the read failed', async () => {
    h.list = payload(6)
    expect(card((await mountTools()).w, 'getting-started').text()).toContain('All 6 done')
    h.fail = true
    const failed = card((await mountTools()).w, 'getting-started')
    expect(failed.exists()).toBe(true)
    expect(failed.text()).not.toContain('done')
  })

  it('Connect a tool opens the pop-up fresh: Home with ?openSetup=new', async () => {
    const { w } = await mountTools()
    await card(w, 'connect').trigger('click')
    expect(h.push).toHaveBeenCalledWith({ path: '/home', query: { openSetup: 'new' } })
  })

  it('Videos and animations opens the library, which closes again', async () => {
    const { w } = await mountTools()
    const lib = () => w.find('[data-testid="library-stub"]')
    expect(lib().attributes('data-open')).toBe('false')
    await card(w, 'videos').trigger('click')
    expect(lib().attributes('data-open')).toBe('true')
    w.findComponent({ name: 'VideosLibraryDialog' }).vm.$emit('close')
    await w.vm.$nextTick()
    expect(lib().attributes('data-open')).toBe('false')
  })

  it('the animated tour entry of the library starts the tour on Home from its first stop', async () => {
    const { w } = await mountTools()
    w.findComponent({ name: 'VideosLibraryDialog' }).vm.$emit('open-tour')
    expect(h.push).toHaveBeenCalledWith({ path: '/home', query: { openGuide: 'true' } })
  })

  it('User guide goes where the avatar menu goes', async () => {
    const { w } = await mountTools()
    await card(w, 'user-guide').trigger('click')
    expect(h.push).toHaveBeenCalledWith({ name: 'UserGuide' })
  })

  it('the cards are keyboard operable', async () => {
    const { w } = await mountTools()
    for (const name of ['getting-started', 'connect', 'videos', 'user-guide']) {
      expect(card(w, name).attributes('tabindex')).toBe('0')
      expect(card(w, name).attributes('role')).toMatch(/button|link/)
    }
  })

  it('the Connect subtitle still names the product from branding', async () => {
    const { w } = await mountTools()
    expect(w.text()).toContain('Connect external tools and services to your Giljo HQ workspace')
  })
})
