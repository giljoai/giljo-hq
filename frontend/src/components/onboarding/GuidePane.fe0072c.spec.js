import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const h = vi.hoisted(() => ({
  list: null,
  push: vi.fn(),
  patch: vi.fn(),
  copy: vi.fn(),
  starter: vi.fn(),
  busy: { value: null },
  routeName: undefined,
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ meta: {}, query: {}, name: h.routeName }),
  useRouter: () => ({ push: h.push }),
}))
vi.mock('@/services/api', () => {
  const apiObj = {
    auth: { updateSetupState: (...a) => h.patch(...a), me: vi.fn() },
    onboarding: { startList: vi.fn(async () => ({ data: JSON.parse(JSON.stringify(h.list)) })) },
  }
  return { default: apiObj, api: apiObj }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: (...a) => h.copy(...a) }) }))
vi.mock('@/composables/useStarterProject', () => ({
  useStarterProject: () => ({ createFromTemplate: (...a) => h.starter(...a), busyTemplateId: h.busy }),
}))
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({ effectiveProductId: 'prod-1' }),
}))

import GuidePane from '@/components/onboarding/GuidePane.vue'
import StartProductDialog from '@/components/onboarding/StartProductDialog.vue'
import IntroVideoDialog from '@/components/onboarding/IntroVideoDialog.vue'
import { useGuideStore } from '@/stores/guide'
import { useStartListStore } from '@/stores/startList'
import { useUserStore } from '@/stores/user'
import { SETUP_REQUEST } from '@/content/onboarding/guide'
import { PROJECT_TEMPLATES } from '@/composables/projectTemplates'
import { ONBOARDING_INTRO_VIDEO, ONBOARDING_LESSONS } from '@/content/onboarding/videos'
import { startListPayload, ALL_DONE } from '../../../tests/helpers/startListRows'

const mem = new Map()
window.localStorage = {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => mem.set(k, String(v)),
  removeItem: (k) => mem.delete(k),
  clear: () => mem.clear(),
}

const CONNECTED = { tool_connected: { done: true, live: true, tool_name: 'Claude Code' } }
const SETUP = { ...CONNECTED, skills_installed: { done: true } }
const PRODUCT = { ...SETUP, product_exists: { done: true, product_name: 'Recipe Box' } }
const PROJECT = {
  ...PRODUCT,
  project_created: { done: true, project_id: 'p-9', project_name: 'Add a search box' },
}

async function mountPane(over = {}, { user = {}, folded = false } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  h.list = startListPayload(over)
  useUserStore().currentUser = {
    id: 'u-1', created_at: '2026-11-16T10:00:00Z', guide_closed: false, intro_video_seen: true, ...user,
  }
  await useStartListStore().refresh()
  const guide = useGuideStore()
  if (folded) guide.setFolded(true)
  const w = mount(GuidePane, {
    global: {
      plugins: [pinia],
      stubs: { StartProductDialog: true, IntroVideoDialog: true },
    },
  })
  await flushPromises()
  return { w, guide }
}
const id = (w, t) => w.find(`[data-testid="${t}"]`)

describe('GuidePane: when it exists', () => {
  beforeEach(() => {
    mem.clear()
    window.innerWidth = 1280
    Object.values(h).forEach((v) => v?.mockReset?.())
    h.patch.mockImplementation(async (p) => ({ data: p }))
    h.copy.mockResolvedValue(true)
  })

  it('a new account with the list read: the pane is there, open, with its title and count', async () => {
    const { w } = await mountPane(CONNECTED)
    expect(id(w, 'guide-pane').exists()).toBe(true)
    expect(w.text()).toContain('Getting started')
    expect(id(w, 'guide-pane-count').text()).toBe('1 of 6')
    expect(w.findAll('[data-testid^="guide-row-"][data-state]')).toHaveLength(6)
  })

  it('an older account: nothing at all', async () => {
    const { w } = await mountPane({}, { user: { created_at: '2026-10-01T00:00:00Z' } })
    expect(id(w, 'guide-pane').exists()).toBe(false)
  })

  it('a closed pane: nothing at all', async () => {
    const { w } = await mountPane({}, { user: { guide_closed: true } })
    expect(id(w, 'guide-pane').exists()).toBe(false)
  })

  it('takes its own column at desktop widths (permanent, not temporary)', async () => {
    const { w } = await mountPane()
    expect(id(w, 'guide-pane').attributes('temporary')).not.toBe('true')
    expect(id(w, 'guide-pane').attributes('location')).toBe('right')
  })

  it('on a small screen it is a temporary drawer and starts shut, with a button to open it', async () => {
    window.innerWidth = 700
    const { w } = await mountPane()
    expect(id(w, 'guide-pane').attributes('temporary')).toBe('true')
    expect(id(w, 'guide-pane-mobile-open').exists()).toBe(true)
  })
})

describe('GuidePane: rows', () => {
  beforeEach(() => {
    mem.clear()
    window.innerWidth = 1280
    Object.values(h).forEach((v) => v?.mockReset?.())
    h.patch.mockImplementation(async (p) => ({ data: p }))
    h.copy.mockResolvedValue(true)
  })

  it('ticks only what the server says; the current row shows help and its action', async () => {
    const { w } = await mountPane(CONNECTED)
    expect(id(w, 'guide-row-1').attributes('data-state')).toBe('done')
    expect(id(w, 'guide-row-1-line').text()).toBe('Claude Code is connected.')
    expect(id(w, 'guide-row-2').attributes('data-state')).toBe('current')
    expect(id(w, 'guide-row-2-line').text()).toBe('Ask your tool to run giljo_setup.')
    expect(id(w, 'guide-row-2-action').text()).toBe('Copy the request')
    expect(id(w, 'guide-row-3').attributes('data-state')).toBe('todo')
    expect(id(w, 'guide-row-3-line').exists()).toBe(false)
  })

  it('a click never ticks a row', async () => {
    const { w } = await mountPane()
    await id(w, 'guide-row-3').trigger('click')
    await id(w, 'guide-row-3-action').trigger('click')
    expect(id(w, 'guide-row-3').attributes('data-state')).not.toBe('done')
  })

  it('row 1 Connect opens the connect pop-up through home?openSetup=true', async () => {
    const { w } = await mountPane()
    await id(w, 'guide-row-1-action').trigger('click')
    expect(h.push).toHaveBeenCalledWith({ path: '/home', query: { openSetup: 'true' } })
  })

  it('row 1 connected before, not live: says so and offers Connect again', async () => {
    const { w } = await mountPane({ tool_connected: { done: true, live: false, tool_name: 'Claude Code' } })
    expect(id(w, 'guide-row-1-line').text()).toBe('Connected before. Connect again when you are ready.')
    expect(id(w, 'guide-row-1-action').exists()).toBe(true)
  })

  it('row 2 Copy the request copies the request; the button answers Copied in the primary colour for 2 s', async () => {
    vi.useFakeTimers()
    try {
      const { w } = await mountPane(CONNECTED)
      await id(w, 'guide-row-2-action').trigger('click')
      await vi.advanceTimersByTimeAsync(0)
      expect(h.copy).toHaveBeenCalledWith(SETUP_REQUEST)
      const btn = id(w, 'guide-row-2-action')
      expect(btn.text()).toBe('Copied')
      expect(btn.classes()).toContain('gp-btn--copied')
      expect(id(w, 'guide-row-2-live').text()).toBe('Copied')
      await vi.advanceTimersByTimeAsync(2100)
      expect(id(w, 'guide-row-2-action').text()).toBe('Copy the request')
      expect(id(w, 'guide-row-2-live').text()).toBe('')
    } finally {
      vi.useRealTimers()
    }
  })

  it('a refused copy says nothing', async () => {
    h.copy.mockResolvedValue(false)
    const { w } = await mountPane(CONNECTED)
    await id(w, 'guide-row-2-action').trigger('click')
    await flushPromises()
    expect(id(w, 'guide-row-2-action').text()).toBe('Copy the request')
    expect(id(w, 'guide-row-2-live').text()).toBe('')
    expect(w.text()).not.toContain('Copied')
  })

  it('row 3 Choose how to start opens the four-ways dialog', async () => {
    const { w } = await mountPane(SETUP)
    expect(w.findComponent(StartProductDialog).props('modelValue')).toBe(false)
    await id(w, 'guide-row-3-action').trigger('click')
    expect(w.findComponent(StartProductDialog).props('modelValue')).toBe(true)
    w.findComponent(StartProductDialog).vm.$emit('update:modelValue', false)
    await nextTick()
    expect(w.findComponent(StartProductDialog).props('modelValue')).toBe(false)
  })

  it('row 4 with a product: the two starters run the Home starter action, and the ask line shows', async () => {
    const { w } = await mountPane(PRODUCT)
    expect(id(w, 'guide-row-4-import').text()).toBe('Import an existing product')
    expect(id(w, 'guide-row-4-bootstrap').text()).toBe('Bootstrap a new product')
    expect(id(w, 'guide-row-4-ask').text()).toBe('Or ask your AI tool to make a project.')
    await id(w, 'guide-row-4-import').trigger('click')
    expect(h.starter).toHaveBeenCalledWith(PROJECT_TEMPLATES.find((t) => t.id === 'existing_product_bootstrap'))
    await id(w, 'guide-row-4-bootstrap').trigger('click')
    expect(h.starter).toHaveBeenCalledWith(PROJECT_TEMPLATES.find((t) => t.id === 'new_product_bootstrap'))
  })

  it('row 4 without a product: the buttons are off and the line says why', async () => {
    const { w } = await mountPane(SETUP)
    expect(id(w, 'guide-row-4-import').attributes('disabled')).toBeDefined()
    expect(id(w, 'guide-row-4-bootstrap').attributes('disabled')).toBeDefined()
    expect(id(w, 'guide-row-4-needs-product').text()).toBe('These need a product first. Add one in step 3.')
    await id(w, 'guide-row-4-import').trigger('click')
    expect(h.starter).not.toHaveBeenCalled()
  })

  it('row 4 done names the project and has no buttons', async () => {
    const { w } = await mountPane(PROJECT)
    expect(id(w, 'guide-row-4-line').text()).toBe('Project created: Add a search box.')
    expect(id(w, 'guide-row-4-import').exists()).toBe(false)
  })

  it('row 5 todo: the instruction, a flat picture of the play button, no buttons at all', async () => {
    const { w } = await mountPane(PROJECT)
    expect(id(w, 'guide-row-5').attributes('data-state')).toBe('todo')
    expect(id(w, 'guide-row-5-line').text()).toBe(
      'In Projects, press the play button on your project. Pick a mode, then press Stage.',
    )
    expect(id(w, 'guide-row-5-action').exists()).toBe(false)
    expect(w.text()).not.toContain('Open the project')
    const pic = id(w, 'guide-row-5-picture')
    expect(pic.classes()).toContain('guide-btn-picture')
    expect(pic.attributes('aria-hidden')).toBe('true')
  })

  it('the picture of a button is not a control: no button, no tab stop, a click does nothing', async () => {
    const { w } = await mountPane({ ...PROJECT, project_staged: { done: true, mode: 'subagent' } })
    for (const n of [6]) {
      const pic = id(w, `guide-row-${n}-picture`)
      expect(pic.exists()).toBe(true)
      expect(pic.element.tagName).toBe('SPAN')
      expect(pic.attributes('tabindex')).toBeUndefined()
      expect(pic.attributes('role')).toBeUndefined()
      expect(pic.attributes('aria-hidden')).toBe('true')
      expect(pic.findAll('button, a, [tabindex]')).toHaveLength(0)
      h.push.mockClear()
      await pic.trigger('click')
      expect(h.push).not.toHaveBeenCalled()
    }
    expect(id(w, 'guide-row-6-picture').text()).toBe('Implement')
    expect(id(w, 'guide-row-6-picture').html()).toContain('mdi-play')
    expect(id(w, 'guide-row-6-picture').html()).not.toContain('rocket')
    expect(id(w, 'guide-row-6-line').text()).toContain('Implement button')
  })

  it('row 5 requested: the prompt-copied line, no picture; row 5 done shows no link', async () => {
    const { w } = await mountPane({ ...PROJECT, project_staged: { requested: true } })
    expect(id(w, 'guide-row-5').attributes('data-state')).toBe('requested')
    expect(id(w, 'guide-row-5-line').text()).toBe('Prompt copied. Paste it in your AI tool. Your tool writes the plan.')
    expect(id(w, 'guide-row-5-picture').exists()).toBe(false)
    const done = await mountPane({ ...PROJECT, project_staged: { done: true, mode: 'subagent' } })
    expect(id(done.w, 'guide-row-5-goto').exists()).toBe(false)
  })

  it('"Go to Projects" is a plain text link on rows 5 and 6, away from Projects and Jobs', async () => {
    const { w } = await mountPane({ ...PROJECT, project_staged: { requested: true } })
    const link = id(w, 'guide-row-5-goto')
    expect(link.text()).toBe('Go to Projects')
    expect(link.classes()).not.toContain('gp-btn')
    await link.trigger('click')
    expect(h.push).toHaveBeenCalledWith({ name: 'Projects' })
  })

  it('on the Projects page or the Jobs page the link is not shown', async () => {
    for (const name of ['Projects', 'JobsViewport']) {
      h.routeName = name
      const { w } = await mountPane({ ...PROJECT, project_staged: { requested: true } })
      expect(id(w, 'guide-row-5-goto').exists()).toBe(false)
      expect(id(w, 'guide-row-5-line').exists()).toBe(true)
    }
    h.routeName = undefined
  })

  it('with no project rows 5 and 6 have no link, no picture and no button', async () => {
    const { w } = await mountPane()
    for (const n of [5, 6]) {
      expect(id(w, `guide-row-${n}-action`).exists()).toBe(false)
      expect(id(w, `guide-row-${n}-goto`).exists()).toBe(false)
      expect(id(w, `guide-row-${n}-picture`).exists()).toBe(false)
    }
  })

  it('row 6 walks todo, in progress, awaiting review (green Review project picture), done', async () => {
    const staged = { ...PROJECT, project_staged: { done: true, mode: 'multi_terminal' } }
    const idle = await mountPane(staged)
    expect(id(idle.w, 'guide-row-5-line').text()).toBe('Staged (multi-terminal mode). The plan waits for your go.')
    expect(id(idle.w, 'guide-row-6').attributes('data-state')).toBe('todo')
    expect(id(idle.w, 'guide-row-6-line').text()).toBe('Press the Implement button on your project card.')
    const running = await mountPane({ ...staged, project_built: { in_progress: true } })
    expect(id(running.w, 'guide-row-6').attributes('data-state')).toBe('in_progress')
    expect(id(running.w, 'guide-row-6-line').text()).toBe('In progress.')
    const review = await mountPane({ ...staged, project_built: { awaiting_review: true } })
    expect(id(review.w, 'guide-row-6').attributes('data-state')).toBe('awaiting_review')
    expect(id(review.w, 'guide-row-6-line').text()).toBe(
      'Your agents are done. Press Review project on the card to see their work.',
    )
    expect(id(review.w, 'guide-row-6-picture').classes()).toContain('guide-btn-picture--review')
    expect(id(review.w, 'guide-row-6-picture').text()).toBe('Review project')
    expect(id(review.w, 'guide-row-6-picture').html()).not.toContain('icon=')
    expect(id(review.w, 'guide-pane-count').text()).toBe('5 of 6')
    const done = await mountPane({ ...staged, project_built: { done: true } })
    await useGuideStore().turnOn()
    await flushPromises()
    expect(id(done.w, 'guide-row-6').attributes('data-state')).toBe('done')
    expect(id(done.w, 'guide-row-6-line').text()).toBe('First project finished and reviewed.')
  })
})

describe('GuidePane: videos', () => {
  beforeEach(() => {
    mem.clear()
    window.innerWidth = 1280
    Object.values(h).forEach((v) => v?.mockReset?.())
    h.patch.mockImplementation(async (p) => ({ data: p }))
  })

  it('every row has a "Watch how (m:ss)" button with the real length; it opens that row\'s video, closable', async () => {
    const { w } = await mountPane(CONNECTED)
    const len = (v) => `${Math.floor(Math.round(v.seconds) / 60)}:${String(Math.round(v.seconds) % 60).padStart(2, '0')}`
    for (let n = 1; n <= 6; n += 1) {
      const link = id(w, `guide-row-${n}-play`)
      expect(link.element.tagName).toBe('BUTTON')
      expect(link.text()).toMatch(/Watch how \(\d+:\d\d\)$/)
      expect(link.attributes('aria-label')).toMatch(/^Watch how: .+ \(\d+:\d\d\)$/)
      expect(link.classes()).toContain('gp-btn')
    }
    expect(id(w, 'guide-row-1-play').text()).toBe(`Watch how (${len(ONBOARDING_INTRO_VIDEO)})`)
    expect(id(w, 'guide-row-3-play').text()).toBe(`Watch how (${len(ONBOARDING_LESSONS[0])})`)
    const dlg = () => w.findComponent(IntroVideoDialog)
    expect(dlg().props('modelValue')).toBe(false)
    await id(w, 'guide-row-1-play').trigger('click')
    expect(dlg().props('modelValue')).toBe(true)
    expect(dlg().props('video').id).toBe(ONBOARDING_INTRO_VIDEO.id)
    expect(dlg().props('gated')).toBe(false)
    dlg().vm.$emit('close')
    await nextTick()
    expect(dlg().props('modelValue')).toBe(false)
    await id(w, 'guide-row-4-play').trigger('click')
    expect(dlg().props('video').id).toBe(ONBOARDING_LESSONS[1].id)
  })

  it('the button sits in the row\'s centred button group, after the action, and the icon-only control beside the title is gone', async () => {
    const { w } = await mountPane(CONNECTED)
    const row = id(w, 'guide-row-2')
    expect(row.find('.gp-title-row button').exists()).toBe(false)
    const group = id(w, 'guide-row-2-buttons')
    expect(group.classes()).toContain('gp-actions')
    const ids = [...group.element.children].map((k) => k.getAttribute('data-testid'))
    expect(ids).toEqual(['guide-row-2-action', 'guide-row-2-play'])
  })

  it('a row with no action has the button alone in the group, under its help line', async () => {
    const { w } = await mountPane(CONNECTED)
    const ids = [...id(w, 'guide-row-1-buttons').element.children].map((k) => k.getAttribute('data-testid'))
    expect(ids).toEqual(['guide-row-1-action'].filter(() => false).concat(['guide-row-1-play']))
    const kids = [...id(w, 'guide-row-1').find('.gp-main').element.children].map((k) => k.getAttribute('data-testid'))
    expect(kids.indexOf('guide-row-1-buttons')).toBeGreaterThan(kids.indexOf('guide-row-1-line'))
  })

  it('the button has the play icon, is outlined (not the filled primary), and a done row\'s is quieter', async () => {
    const { w } = await mountPane(CONNECTED)
    const open = id(w, 'guide-row-2-play')
    expect(open.html()).toContain('mdi-play-circle-outline')
    expect(open.classes()).not.toContain('gp-btn--primary')
    expect(open.classes()).not.toContain('gp-btn--quiet')
    expect(id(w, 'guide-row-1-play').classes()).toContain('gp-btn--quiet')
  })

  it('Watch how is yellow in both states: the button carries gp-btn--watch (current and done) and the rule is in the component', async () => {
    const { w } = await mountPane(CONNECTED)
    expect(id(w, 'guide-row-2-play').classes()).toContain('gp-btn--watch')
    expect(id(w, 'guide-row-1-play').classes()).toContain('gp-btn--watch')
    expect(id(w, 'guide-row-1-play').classes()).toContain('gp-btn--quiet')
    const src = readFileSync(resolve(__dirname, 'GuidePane.vue'), 'utf8')
    expect(src).toMatch(/\.gp-btn--watch \{[^}]*color: \$color-brand-yellow;/)
    expect(src).toMatch(/\.gp-btn--watch\.gp-btn--quiet \{[^}]*color: rgba\(\$color-brand-yellow/)
  })

  it('rows 5 and 6: Watch how is the main button, under the instruction and the picture', async () => {
    const { w } = await mountPane({ ...PROJECT, project_staged: { done: true, mode: 'subagent' } })
    const kids = [...id(w, 'guide-row-6').find('.gp-main').element.children].map((k) => k.getAttribute('data-testid'))
    expect(kids.indexOf('guide-row-6-buttons')).toBeGreaterThan(kids.indexOf('guide-row-6-picture'))
    expect(id(w, 'guide-row-6-action').exists()).toBe(false)
  })

  it('in the folded rail nothing changes: dots only, no video links', async () => {
    const { w } = await mountPane(SETUP, { folded: true })
    expect(w.findAll('[data-testid$="-play"]')).toHaveLength(0)
  })
})

describe('GuidePane: fold, rail and close', () => {
  beforeEach(() => {
    mem.clear()
    window.innerWidth = 1280
    Object.values(h).forEach((v) => v?.mockReset?.())
    h.patch.mockImplementation(async (p) => ({ data: p }))
  })

  it('the fold control puts it in rail mode: six dots, no words', async () => {
    const { w, guide } = await mountPane(SETUP)
    await id(w, 'guide-pane-fold').trigger('click')
    expect(guide.folded).toBe(true)
    expect(id(w, 'guide-pane').attributes('rail')).toBe('true')
    expect(w.findAll('[data-testid^="guide-dot-"]')).toHaveLength(6)
    expect(w.text()).not.toContain('Getting started')
    expect(w.text()).not.toContain('Connect your AI tool')
  })

  it('rail dots: a tick when done, the current one marked, each with an accessible name', async () => {
    const { w } = await mountPane(SETUP, { folded: true })
    expect(id(w, 'guide-dot-1').attributes('data-state')).toBe('done')
    expect(id(w, 'guide-dot-1').attributes('aria-label')).toBe('Step 1: Connect your AI tool, done')
    expect(id(w, 'guide-dot-3').attributes('data-state')).toBe('current')
    expect(id(w, 'guide-dot-3').attributes('aria-label')).toBe('Step 3: Add your product, current step')
    expect(id(w, 'guide-dot-5').attributes('aria-label')).toBe('Step 5: Stage your project, not done')
  })

  it('pressing a dot opens the pane', async () => {
    const { w, guide } = await mountPane(SETUP, { folded: true })
    await id(w, 'guide-dot-2').trigger('click')
    expect(guide.folded).toBe(false)
    expect(id(w, 'guide-pane').attributes('rail')).not.toBe('true')
  })

  it('close saves guide_closed and the pane goes away', async () => {
    const { w } = await mountPane(SETUP)
    await id(w, 'guide-pane-close').trigger('click')
    await flushPromises()
    expect(h.patch).toHaveBeenCalledWith({ guide_closed: true })
    expect(id(w, 'guide-pane').exists()).toBe(false)
  })

  it('all six done: the finished pane has its two lines and a Close guide button that does what the X does', async () => {
    const { w } = await mountPane(ALL_DONE.rows, { user: {} })
    await useGuideStore().turnOn()
    await flushPromises()
    expect(id(w, 'guide-pane-finished-line').text()).toBe('Congratulations. You are set up and ran your first project.')
    expect(id(w, 'guide-pane-finished-again').text()).toBe('You can open this guide again in Tools > Learning.')
    expect(id(w, 'guide-pane-count').text()).toBe('6 of 6')
    h.patch.mockClear()
    await id(w, 'guide-pane-finished-close').trigger('click')
    await flushPromises()
    expect(h.patch).toHaveBeenCalledWith({ guide_closed: true })
    expect(id(w, 'guide-pane').exists()).toBe(false)
  })

  it('"You are set" only when row 6 is done: five done plus awaiting review is not finished', async () => {
    const { w } = await mountPane(
      { ...ALL_DONE.rows, project_built: { done: false, awaiting_review: true } },
      { user: {} },
    )
    await useGuideStore().turnOn()
    await flushPromises()
    expect(id(w, 'guide-pane-finished').exists()).toBe(false)
    expect(id(w, 'guide-pane-count').text()).toBe('5 of 6')
  })

  it('in the mobile drawer a close control is also there', async () => {
    window.innerWidth = 700
    const { w } = await mountPane(SETUP)
    expect(id(w, 'guide-pane-close').exists()).toBe(true)
  })
})

describe('GuidePane: room kept beside the connect pop-up', () => {
  beforeEach(() => {
    mem.clear()
    window.innerWidth = 1280
    Object.values(h).forEach((v) => v?.mockReset?.())
    h.patch.mockImplementation(async (p) => ({ data: p }))
  })

  it('an open pane reserves 320 px, a folded one 56 px', async () => {
    const { w, guide } = await mountPane(SETUP)
    expect(guide.reservedWidth).toBe(320)
    await id(w, 'guide-pane-fold').trigger('click')
    expect(guide.reservedWidth).toBe(56)
  })

  it('a closed pane reserves nothing', async () => {
    const { w, guide } = await mountPane(SETUP)
    await id(w, 'guide-pane-close').trigger('click')
    await flushPromises()
    expect(guide.reservedWidth).toBe(0)
  })

  it('on a phone the pane is a drawer that takes no room: nothing is reserved, the pop-up covers the screen', async () => {
    window.innerWidth = 700
    const { guide } = await mountPane(SETUP)
    expect(guide.reservedWidth).toBe(0)
  })

  it('leaving the page gives the room back', async () => {
    const { w, guide } = await mountPane(SETUP)
    w.unmount()
    expect(guide.reservedWidth).toBe(0)
  })
})
