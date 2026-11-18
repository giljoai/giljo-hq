import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

const h = vi.hoisted(() => ({
  route: null,
  push: vi.fn(),
  replace: vi.fn(),
  user: null,
  setupSaves: [],
  list: null,
  listFails: false,
  wsHandlers: new Map(),
  hasProducts: false,
  hasActiveProduct: false,
  projects: [],
}))

vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  h.route = reactive({ query: {} })
  return {
    useRoute: () => h.route,
    useRouter: () => ({ push: h.push, replace: h.replace }),
  }
})
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getRawConfig: vi.fn().mockReturnValue(null),
    getVersion: vi.fn().mockReturnValue('probe'),
  },
}))
vi.mock('@/services/api', () => ({
  default: {
    templates: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      activeCount: vi.fn().mockResolvedValue({ data: { max_slots: 16 } }),
    },
    stats: { getDashboard: vi.fn().mockResolvedValue({ data: { recent_projects: [] } }) },
    onboarding: {
      startList: vi.fn(async () => {
        if (h.listFails) throw new Error('network')
        return { data: JSON.parse(JSON.stringify(h.list)) }
      }),
    },
  },
}))
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on: (type, fn) => {
      if (!h.wsHandlers.has(type)) h.wsHandlers.set(type, new Set())
      h.wsHandlers.get(type).add(fn)
      return () => h.wsHandlers.get(type)?.delete(fn)
    },
  }),
}))
vi.mock('@/components/GilMascot.vue', () => ({ default: { name: 'GilMascot', template: '<div />' } }))
vi.mock('@/components/dashboard/RecentProjectsList.vue', () => ({
  default: { name: 'RecentProjectsList', template: '<div />' },
}))
vi.mock('@/components/projects/ProjectReviewModal.vue', () => ({
  default: { name: 'ProjectReviewModal', template: '<div />' },
}))
vi.mock('@/components/setup/SetupWizardOverlay.vue', () => ({
  default: {
    name: 'SetupWizardOverlay',
    props: ['modelValue', 'currentStep', 'selectedTools', 'fresh'],
    emits: ['update:modelValue', 'update:currentStep', 'dismiss', 'step-complete'],
    template:
      '<div data-testid="wizard-stub" :data-open="String(modelValue)" :data-step="currentStep" :data-fresh="String(fresh)" />',
  },
}))
vi.mock('@/components/tutorial/TutorialOverlay.vue', () => ({
  default: {
    name: 'TutorialOverlay',
    props: ['modelValue', 'startOver', 'startAt'],
    emits: ['dismiss', 'update:modelValue'],
    template:
      '<div data-testid="tour-stub" :data-open="String(modelValue)" :data-start-at="String(startAt)" />',
  },
}))
vi.mock('@/stores/user', async () => {
  const { reactive } = await import('vue')
  const currentUser = reactive({ id: 'u-1' })
  const store = {
    currentUser,
    updateSetupState: vi.fn(async (payload) => {
      h.setupSaves.push({ ...payload })
      Object.assign(currentUser, payload)
    }),
  }
  h.user = store
  return { useUserStore: () => store }
})
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    get activeProduct() {
      return h.hasActiveProduct ? { id: 'p1' } : null
    },
    get hasProducts() {
      return h.hasProducts
    },
    get effectiveProductId() {
      return h.hasActiveProduct ? 'p1' : null
    },
    fetchProducts: vi.fn().mockResolvedValue(),
  }),
}))
vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    get projects() {
      return h.projects
    },
    get activeProjects() {
      return []
    },
    fetchProjects: vi.fn().mockResolvedValue(),
  }),
}))

const stubs = {
  teleport: true,
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': { template: '<button v-bind="$attrs"><slot /></button>' },
  'router-link': { template: '<a><slot /></a>' },
}

function listPayload(over = {}) {
  const rows = {
    tool_connected: { done: false, live: false, tool_name: null },
    skills_installed: { done: false },
    product_exists: { done: false, product_name: null },
    project_staged: { done: false, has_project: false },
    project_built: { done: false },
    ...over,
  }
  const done_count = Object.values(rows).filter((r) => r.done).length
  return { rows, done_count }
}

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

async function settle() {
  for (let i = 0; i < 25; i++) await Promise.resolve()
  await nextTick()
  for (let i = 0; i < 25; i++) await Promise.resolve()
}

let homePinia = null

async function mountHome(user = {}) {
  const WelcomeView = (await import('@/views/WelcomeView.vue')).default
  Object.keys(h.user.currentUser).forEach((k) => delete h.user.currentUser[k])
  Object.assign(h.user.currentUser, {
    id: 'u-1',
    full_name: 'Alex Test',
    setup_complete: true,
    learning_complete: false,
    setup_step_completed: 4,
    setup_selected_tools: ['claude_code'],
    ...user,
  })
  const pinia = createPinia()
  setActivePinia(pinia)
  homePinia = pinia
  const w = mount(WelcomeView, { global: { stubs, plugins: [pinia] } })
  await settle()
  return w
}

const tour = (w) => w.find('[data-testid="tour-stub"]')
const wizard = (w) => w.find('[data-testid="wizard-stub"]')


describe('Home without the start list (FE-0072c)', () => {
  beforeEach(async () => {
    await import('vue-router')
    setActivePinia(createPinia())
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    h.route.query = {}
    h.push.mockClear()
    h.replace.mockClear()
    h.setupSaves.length = 0
    h.list = listPayload()
    h.listFails = false
    h.wsHandlers.clear()
    h.hasProducts = false
    h.hasActiveProduct = false
    h.projects = []
    installMemoryStorage()
    window.innerWidth = 1024
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  describe('the list is gone', () => {
    it('no start list, whatever the account has done', async () => {
      h.list = listPayload({ tool_connected: { done: true, live: true, tool_name: 'X' } })
      const w = await mountHome({ setup_complete: false, setup_step_completed: 0 })
      expect(w.find('[data-testid="start-list"]').exists()).toBe(false)
      expect(w.text()).not.toContain('Your first 10 minutes')
    })

    it('does not read the start list or listen for its events (the layout does)', async () => {
      await mountHome()
      const api = (await import('@/services/api')).default
      expect(api.onboarding.startList).not.toHaveBeenCalled()
      expect(h.wsHandlers.size).toBe(0)
    })

    it('no Finish setup / Resume Setup card', async () => {
      h.hasProducts = true
      h.hasActiveProduct = true
      h.projects = [{ id: 'pr1' }]
      const w = await mountHome({ setup_complete: false, setup_step_completed: 1 })
      expect(w.find('.setup-cta').exists()).toBe(false)
      expect(w.text()).not.toContain('Finish setup')
      expect(w.text()).not.toContain('Resume Setup')
    })

    it('?startList=show is no longer handled: no redirect, no list', async () => {
      h.route.query = { startList: 'show' }
      const w = await mountHome()
      expect(h.replace).not.toHaveBeenCalled()
      expect(w.find('[data-testid="start-list"]').exists()).toBe(false)
    })
  })

  describe('Quick Launch shows as it did before the list existed', () => {
    it('setup unfinished: the Quick Setup card', async () => {
      const w = await mountHome({ setup_complete: false, setup_step_completed: 0 })
      expect(w.text()).toContain('Quick Launch')
      expect(w.text()).toContain('Quick Setup')
    })

    it('setup unfinished and the getting-started pane on screen: no Quick Setup card, the rest of the chain applies', async () => {
      const { useStartListStore } = await import('@/stores/startList')
      const w = await mountHome({
        setup_complete: false,
        setup_step_completed: 0,
        created_at: new Date().toISOString(),
        intro_video_seen: true,
      })
      expect(w.text()).toContain('Quick Setup')
      useStartListStore(homePinia).rows = listPayload().rows
      await settle()
      const { useGuideStore } = await import('@/stores/guide')
      expect(useGuideStore(homePinia).visible).toBe(true)
      expect(w.text()).not.toContain('Quick Setup')
      expect(w.text()).toContain('Quick Launch')
      expect(w.text()).toContain('New Product')
    })

    it('setup unfinished, an older account with no pane: the Quick Setup card stays', async () => {
      const { useStartListStore } = await import('@/stores/startList')
      const w = await mountHome({
        setup_complete: false,
        setup_step_completed: 0,
        created_at: '2025-01-01T00:00:00Z',
        intro_video_seen: true,
      })
      useStartListStore(homePinia).rows = listPayload().rows
      await settle()
      const { useGuideStore } = await import('@/stores/guide')
      expect(useGuideStore(homePinia).visible).toBe(false)
      expect(w.text()).toContain('Quick Setup')
    })

    it('set up, no product: the New Product card', async () => {
      const w = await mountHome({ setup_complete: true })
      expect(w.text()).toContain('New Product')
    })

    it('a product and a project: Dashboard and the rest', async () => {
      h.hasProducts = true
      h.hasActiveProduct = true
      h.projects = [{ id: 'pr1' }]
      const w = await mountHome({ setup_complete: true })
      expect(w.text()).toContain('Dashboard')
    })

    it('a product and no project: New Project and the two starter cards', async () => {
      h.hasProducts = true
      h.hasActiveProduct = true
      const w = await mountHome({ setup_complete: true })
      expect(w.text()).toContain('New Project')
      expect(w.text()).toContain('Bootstrap a new product')
      expect(w.text()).toContain('Import an existing product')
    })
  })

  describe('the setup pop-up opens only when asked', () => {
    it('stays closed on a new account', async () => {
      const w = await mountHome({ setup_complete: false, setup_step_completed: 0, setup_selected_tools: [] })
      expect(wizard(w).attributes('data-open')).toBe('false')
    })

    it('?openSetup=true opens it by itself and clears the query', async () => {
      h.route.query = { openSetup: 'true' }
      const w = await mountHome({ setup_complete: false, setup_step_completed: 0 })
      expect(wizard(w).attributes('data-open')).toBe('true')
      expect(h.replace).toHaveBeenCalledWith({ path: '/home' })
    })

    it('?openSetup=true while Home is already open opens it (the layout and the pane send it here)', async () => {
      const w = await mountHome({ setup_complete: false, setup_step_completed: 0, setup_selected_tools: [] })
      expect(wizard(w).attributes('data-open')).toBe('false')
      h.route.query = { openSetup: 'true' }
      await settle()
      expect(wizard(w).attributes('data-open')).toBe('true')
      expect(h.replace).toHaveBeenCalledWith({ path: '/home' })
    })

    it('?openGuide=true still opens the tour', async () => {
      h.route.query = { openGuide: 'true' }
      const w = await mountHome({ setup_complete: true })
      expect(tour(w).attributes('data-open')).toBe('true')
    })

    it('tells the layout while the pop-up is open, so setup_complete is not saved under it', async () => {
      const { useGuideStore } = await import('@/stores/guide')
      h.route.query = { openSetup: 'true' }
      const w = await mountHome({ setup_complete: false })
      expect(useGuideStore().setupWizardOpen).toBe(true)
      w.findComponent({ name: 'SetupWizardOverlay' }).vm.$emit('update:modelValue', false)
      await settle()
      expect(useGuideStore().setupWizardOpen).toBe(false)
    })
  })

  describe('the setup pop-up is three steps: Choose tool, Connect it, Setup instructions', () => {
    const saves = () => h.setupSaves.map((p) => ({ ...p }))

    it('?openSetup=true on an account saved at step 4 opens at Connect, never past it', async () => {
      h.route.query = { openSetup: 'true' }
      const w = await mountHome({ setup_complete: true, setup_step_completed: 4, setup_selected_tools: ['claude_code'] })
      expect(wizard(w).attributes('data-open')).toBe('true')
      expect(wizard(w).attributes('data-step')).toBe('1')
    })

    it('?openSetup=true on an account saved at step 3 opens at Connect', async () => {
      h.route.query = { openSetup: 'true' }
      const w = await mountHome({ setup_complete: false, setup_step_completed: 3, setup_selected_tools: ['claude_code'] })
      expect(wizard(w).attributes('data-step')).toBe('1')
    })

    it('a saved step with no saved tools opens at Choose tools, not at an empty Connect', async () => {
      h.route.query = { openSetup: 'true' }
      const w = await mountHome({ setup_complete: false, setup_step_completed: 2, setup_selected_tools: [] })
      expect(wizard(w).attributes('data-step')).toBe('0')
    })

    it('leaving Connect saves step 2 and never saves setup_complete', async () => {
      h.route.query = { openSetup: 'true' }
      const w = await mountHome({ setup_complete: false, setup_step_completed: 0, setup_selected_tools: ['claude_code'] })
      const wiz = w.findComponent({ name: 'SetupWizardOverlay' })
      wiz.vm.$emit('step-complete', { step: 1, data: { connectedTools: ['claude_code'] } })
      wiz.vm.$emit('update:modelValue', false)
      wiz.vm.$emit('dismiss')
      await settle()
      expect(saves()).toEqual([{ setup_step_completed: 2 }])
      expect(wizard(w).attributes('data-open')).toBe('false')
    })

    it('saved step values 0 to 4 with a saved tool: 0 opens Choose tool, 1 to 4 open Connect', async () => {
      const seen = []
      for (const saved of [0, 1, 2, 3, 4]) {
        h.route.query = { openSetup: 'true' }
        const w = await mountHome({ setup_complete: false, setup_step_completed: saved, setup_selected_tools: ['claude_code'] })
        seen.push(wizard(w).attributes('data-step'))
        w.unmount()
      }
      expect(seen).toEqual(['0', '1', '1', '1', '1'])
    })

    it('leaving Setup instructions (Done) saves step 3 and never setup_complete', async () => {
      h.route.query = { openSetup: 'true' }
      const w = await mountHome({ setup_complete: false, setup_step_completed: 1, setup_selected_tools: ['claude_code'] })
      const wiz = w.findComponent({ name: 'SetupWizardOverlay' })
      wiz.vm.$emit('step-complete', { step: 2, data: {} })
      wiz.vm.$emit('dismiss')
      await settle()
      expect(saves()).toEqual([{ setup_step_completed: 3 }])
    })

    it('?openSetup=true is not the fresh start', async () => {
      h.route.query = { openSetup: 'true' }
      const w = await mountHome({ setup_complete: true, setup_step_completed: 4, setup_selected_tools: ['claude_code'] })
      expect(wizard(w).attributes('data-fresh')).toBe('false')
    })

    it('?openSetup=new ("Connect a tool") opens at Choose tool, fresh, whatever was saved', async () => {
      h.route.query = { openSetup: 'new' }
      const w = await mountHome({ setup_complete: true, setup_step_completed: 4, setup_selected_tools: ['claude_code'] })
      expect(wizard(w).attributes('data-open')).toBe('true')
      expect(wizard(w).attributes('data-step')).toBe('0')
      expect(wizard(w).attributes('data-fresh')).toBe('true')
      expect(h.replace).toHaveBeenCalledWith({ path: '/home' })
    })

    it('?openSetup=new while Home is already open opens it too', async () => {
      const w = await mountHome({ setup_complete: true, setup_step_completed: 4, setup_selected_tools: ['codex_cli'] })
      h.route.query = { openSetup: 'new' }
      await settle()
      expect(wizard(w).attributes('data-step')).toBe('0')
      expect(wizard(w).attributes('data-fresh')).toBe('true')
    })

    it('a second tool is added to the saved list, not swapped for it', async () => {
      h.route.query = { openSetup: 'new' }
      const w = await mountHome({ setup_complete: true, setup_step_completed: 4, setup_selected_tools: ['codex_cli', 'claude_code'] })
      w.findComponent({ name: 'SetupWizardOverlay' }).vm.$emit('step-complete', { step: 0, data: { tools: ['opencode', 'claude_code'] } })
      await settle()
      expect(saves()).toEqual([{ setup_selected_tools: ['claude_code', 'codex_cli', 'opencode'], setup_step_completed: 1 }])
    })

    it('a normal first pick still replaces the saved list', async () => {
      h.route.query = { openSetup: 'true' }
      const w = await mountHome({ setup_complete: false, setup_step_completed: 0, setup_selected_tools: [] })
      w.findComponent({ name: 'SetupWizardOverlay' }).vm.$emit('step-complete', { step: 0, data: { tools: ['opencode'] } })
      await settle()
      expect(saves()).toEqual([{ setup_selected_tools: ['opencode'], setup_step_completed: 1 }])
    })

    it('closing the pop-up with X never saves setup_complete', async () => {
      h.route.query = { openSetup: 'true' }
      const w = await mountHome({ setup_complete: false, setup_step_completed: 2, setup_selected_tools: ['claude_code'] })
      const wiz = w.findComponent({ name: 'SetupWizardOverlay' })
      wiz.vm.$emit('update:currentStep', 3)
      wiz.vm.$emit('dismiss')
      await settle()
      expect(saves().some((p) => 'setup_complete' in p)).toBe(false)
    })
  })

  describe('the start-video link (FE-0072e) stays', () => {
    const DAY = 24 * 60 * 60 * 1000
    const ago = (days) => new Date(Date.now() - days * DAY).toISOString()
    const videoCard = (w) => w.find('[data-testid="intro-video-home-card"]')

    it('is there for an account of 29 days', async () => {
      const w = await mountHome({ created_at: ago(29), intro_video_seen: true })
      expect(videoCard(w).exists()).toBe(true)
      expect(w.text()).toContain('How to get going')
    })

    it('is not there for an account of 31 days', async () => {
      const w = await mountHome({ created_at: ago(31), intro_video_seen: true })
      expect(videoCard(w).exists()).toBe(false)
    })
  })
})
