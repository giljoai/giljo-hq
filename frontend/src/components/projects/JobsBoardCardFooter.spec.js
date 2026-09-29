import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const h = vi.hoisted(() => ({
  staging: vi.fn(),
  launchProject: vi.fn(),
  launchImplementation: vi.fn(),
  implementation: vi.fn(),
  restage: vi.fn(),
  unstage: vi.fn(),
  update: vi.fn(),
  getOrchestrator: vi.fn(),
  copy: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const api = {
    prompts: { staging: (...a) => h.staging(...a), implementation: (...a) => h.implementation(...a) },
    orchestrator: { launchProject: (...a) => h.launchProject(...a) },
    projects: {
      launchImplementation: (...a) => h.launchImplementation(...a),
      restage: (...a) => h.restage(...a),
      unstage: (...a) => h.unstage(...a),
      update: (...a) => h.update(...a),
      getOrchestrator: (...a) => h.getOrchestrator(...a),
    },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: h.copy }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.toast }) }))

import JobsBoardCardFooter from './JobsBoardCardFooter.vue'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/projects/:projectId', name: 'ProjectLaunch', component: { template: '<div />' } },
  ],
})

const READY = {
  id: 'p-ready',
  taxonomy_alias: 'FE-0101',
  name: 'Ready project',
  status: 'active',
  staging_status: null,
  implementation_launched_at: null,
  execution_mode: null,
  mission: '',
}
const STAGED = {
  ...READY,
  id: 'p-staged',
  taxonomy_alias: 'FE-0102',
  staging_status: 'staging_complete',
  execution_mode: 'subagent',
  mission: 'Build the control row.\nThen test it.',
}
const IMPLEMENTING = {
  ...STAGED,
  id: 'p-impl',
  taxonomy_alias: 'FE-0103',
  implementation_launched_at: '2026-09-24T20:00:00Z',
}

const tooltipStub = {
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

let pinia
function mountFooter(project, sectionLabel, extra = {}) {
  return mount(JobsBoardCardFooter, {
    props: { project, sectionLabel, ...extra },
    global: { plugins: [pinia, router], stubs: { 'v-tooltip': tooltipStub } },
  })
}

const has = (wrapper, id) => wrapper.find(`[data-testid="${id}"]`).exists()

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  h.getOrchestrator.mockResolvedValue({ data: { orchestrator: { detected_harness: 'claude-code' } } })
  h.staging.mockResolvedValue({ data: { prompt: 'STAGING PROMPT' } })
  h.launchProject.mockResolvedValue({})
  h.launchImplementation.mockResolvedValue({})
  h.implementation.mockResolvedValue({ data: { prompt: 'IMPL PROMPT', agent_count: 1 } })
  h.restage.mockResolvedValue({})
  h.unstage.mockResolvedValue({})
  h.update.mockResolvedValue({ data: { ...READY, execution_mode: 'multi_terminal' } })
  h.copy.mockResolvedValue(true)
})

describe('JobsBoardCardFooter: ready, not staged', () => {
  it('shows the Run-as chips, the detected harness, a filled Stage and no Open; no Implement', async () => {
    const wrapper = mountFooter(READY, JOBS_SECTION_LABELS.ACTIVATED)
    await flushPromises()
    expect(wrapper.attributes('data-footer-state')).toBe('ready')
    expect(wrapper.find('[data-testid="jbf-run-as"]').text()).toMatch(/run as/i)
    expect(wrapper.find('.execution-mode-pills').exists()).toBe(false)
    expect(wrapper.find('[data-testid="radio-multi-terminal"]').attributes('aria-pressed')).toBe('false')
    expect(wrapper.find('[data-testid="radio-subagent"]').attributes('aria-pressed')).toBe('false')
    expect(wrapper.find('[data-testid="harness-chip"]').text()).toContain('Claude Code')
    expect(wrapper.find('[data-testid="jbf-stage"]').text()).toBe('Stage')
    expect(wrapper.find('[data-testid="jbf-stage"]').classes()).toContain('jb-btn-primary')
    expect(has(wrapper, 'jb-btn-open')).toBe(false)
    expect(has(wrapper, 'jbf-implement')).toBe(false)
    expect(has(wrapper, 'jb-btn-review')).toBe(false)
  })

  it('Stage with no mode refuses visibly and sends nothing; picking a mode clears it and stages', async () => {
    const wrapper = mountFooter(READY, JOBS_SECTION_LABELS.ACTIVATED)
    await flushPromises()
    expect(wrapper.find('[data-testid="jbf-stage"]').attributes('disabled')).toBeUndefined()
    expect(has(wrapper, 'jbf-mode-refusal')).toBe(false)

    await wrapper.find('[data-testid="jbf-stage"]').trigger('click')
    await flushPromises()
    expect(h.staging).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="jbf-mode-refusal"]').text()).toMatch(/Pick a mode before staging/)
    expect(wrapper.find('[data-testid="jbf-mode-row"]').classes()).toContain('jbf-mode-row--refused')

    await wrapper.find('[data-testid="radio-multi-terminal"]').trigger('click')
    await flushPromises()
    expect(h.update).toHaveBeenCalledWith('p-ready', { execution_mode: 'multi_terminal' })
    expect(has(wrapper, 'jbf-mode-refusal')).toBe(false)

    await wrapper.find('[data-testid="jbf-stage"]').trigger('click')
    await flushPromises()
    expect(h.staging).toHaveBeenCalledWith('p-ready', { tool: 'claude-code', execution_mode: 'multi_terminal' })
    expect(h.copy).toHaveBeenCalledWith('STAGING PROMPT')
    expect(wrapper.emitted('changed')).toBeTruthy()
    expect(wrapper.find('[data-testid="jbf-stage"]').text()).toBe('Unstage')
  })

  it('a row mode on a never-staged project is not pre-selected (the sloppy-stage incident)', async () => {
    const wrapper = mountFooter({ ...READY, id: 'p-row-mode', execution_mode: 'multi_terminal', mission: 'written at creation' }, JOBS_SECTION_LABELS.ACTIVATED)
    await flushPromises()
    expect(wrapper.find('[data-testid="radio-multi-terminal"]').classes()).not.toContain('active')
    expect(wrapper.find('[data-testid="radio-subagent"]').classes()).not.toContain('active')
  })
})

describe('JobsBoardCardFooter: staged, waiting for the go', () => {
  it('shows the locked mode tag, Implement, Re-Stage and no Open; no mode chips, no Mission button', async () => {
    const wrapper = mountFooter(STAGED, JOBS_SECTION_LABELS.STAGED)
    await flushPromises()
    expect(wrapper.attributes('data-footer-state')).toBe('staged')
    expect(wrapper.find('[data-testid="jbf-mode-tag"]').text()).toContain('Subagent')
    expect(has(wrapper, 'radio-multi-terminal')).toBe(false)
    expect(wrapper.find('[data-testid="jbf-implement"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[data-testid="jbf-implement"]').classes()).toContain('jb-btn-primary')
    expect(wrapper.find('[data-testid="jbf-stage"]').text()).toBe('Re-Stage')
    expect(wrapper.find('[data-testid="jbf-stage"]').classes()).toContain('jb-btn-secondary')
    expect(has(wrapper, 'jbf-mission')).toBe(false)
    expect(has(wrapper, 'jb-btn-open')).toBe(false)
    expect(h.getOrchestrator).not.toHaveBeenCalled()
  })

  it('FE-9670d: Implement stamps the gate, then copies the prompt, and reports the change', async () => {
    const wrapper = mountFooter(STAGED, JOBS_SECTION_LABELS.STAGED)
    await flushPromises()
    await wrapper.find('[data-testid="jbf-implement"]').trigger('click')
    await flushPromises()
    expect(h.launchImplementation).toHaveBeenCalledWith('p-staged')
    expect(h.launchImplementation.mock.invocationCallOrder[0]).toBeLessThan(h.implementation.mock.invocationCallOrder[0])
    expect(h.copy).toHaveBeenCalledWith('IMPL PROMPT')
    expect(h.launchProject).toHaveBeenCalledWith({ project_id: 'p-staged' })
    expect(useProjectStateStore().getProjectState('p-staged').isLaunched).toBe(true)
    expect(wrapper.emitted('changed')).toBeTruthy()
    expect(wrapper.attributes('data-footer-state')).toBe('implementing')
  })

  it('Re-Stage goes through the project state store writer', async () => {
    const wrapper = mountFooter(STAGED, JOBS_SECTION_LABELS.STAGED)
    await flushPromises()
    const spy = vi.spyOn(useProjectStateStore(), 'restageProject')
    await wrapper.find('[data-testid="jbf-stage"]').trigger('click')
    await flushPromises()
    expect(spy).toHaveBeenCalledWith('p-staged')
    expect(h.restage).toHaveBeenCalledWith('p-staged')
  })
})

describe('JobsBoardCardFooter: implementing and review', () => {
  it('implementing: Open, Jobs detail and the Hub link; no staging buttons', async () => {
    const wrapper = mountFooter(IMPLEMENTING, JOBS_SECTION_LABELS.IMPLEMENTING)
    await flushPromises()
    expect(wrapper.attributes('data-footer-state')).toBe('implementing')
    expect(has(wrapper, 'jb-btn-open')).toBe(false)
    expect(has(wrapper, 'jb-btn-detail')).toBe(true)
    expect(has(wrapper, 'jb-btn-hub')).toBe(true)
    for (const id of ['jbf-stage', 'jbf-implement', 'jbf-mode-row', 'jbf-mode-tag']) {
      expect(has(wrapper, id)).toBe(false)
    }
  })

  it('a Needs Input card that has launched keeps the implementing row', async () => {
    const wrapper = mountFooter(IMPLEMENTING, JOBS_SECTION_LABELS.NEEDS_INPUT)
    await flushPromises()
    expect(wrapper.attributes('data-footer-state')).toBe('implementing')
  })

  it('review: Review project asks the board to open the closeout; no Open anywhere (the board is the page)', async () => {
    const wrapper = mountFooter(IMPLEMENTING, JOBS_SECTION_LABELS.REVIEW)
    await flushPromises()
    expect(wrapper.attributes('data-footer-state')).toBe('review')
    const review = wrapper.find('[data-testid="jb-btn-review"]')
    expect(review.text()).toBe('Review project')
    expect(review.attributes('href')).toBeUndefined()
    await review.trigger('click')
    expect(wrapper.emitted('review')?.[0]?.[0]).toEqual(IMPLEMENTING)
    expect(has(wrapper, 'jb-btn-open')).toBe(false)
  })

  it('Jobs detail and Hub emit to the board', async () => {
    const wrapper = mountFooter(IMPLEMENTING, JOBS_SECTION_LABELS.IMPLEMENTING)
    await wrapper.find('[data-testid="jb-btn-detail"]').trigger('click')
    await wrapper.find('[data-testid="jb-btn-hub"]').trigger('click')
    expect(wrapper.emitted('open-detail')[0][0].id).toBe('p-impl')
    expect(wrapper.emitted('open-hub')[0][0].id).toBe('p-impl')
  })
})

describe('JobsBoardCardFooter: showStaging=false (a chain member card)', () => {
  it('drops the mode chips and every staging button', async () => {
    const ready = mountFooter(READY, JOBS_SECTION_LABELS.ACTIVATED, { showStaging: false })
    const staged = mountFooter(STAGED, JOBS_SECTION_LABELS.STAGED, { showStaging: false })
    await flushPromises()
    for (const wrapper of [ready, staged]) {
      for (const id of ['jbf-stage', 'jbf-implement', 'jbf-mode-row']) {
        expect(has(wrapper, id)).toBe(false)
      }
      expect(has(wrapper, 'jb-btn-open')).toBe(false)
    }
    expect(has(staged, 'jbf-mission')).toBe(false)
    expect(h.getOrchestrator).not.toHaveBeenCalled()
  })
})
