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
  getDefault: vi.fn(),
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
    },
    settings: { getExecutionModeDefault: (...a) => h.getDefault(...a) },
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
  h.getDefault.mockResolvedValue({ data: { execution_mode_default: 'ask' } })
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
  it('FE-9749: the shared control area: label, both modes unpicked, Stage disabled with its reason, grey Implement', async () => {
    const wrapper = mountFooter(READY, JOBS_SECTION_LABELS.ACTIVATED)
    await flushPromises()
    expect(wrapper.attributes('data-footer-state')).toBe('ready')
    expect(wrapper.find('[data-testid="staging-control-area"]').attributes('data-phase')).toBe('ready')
    expect(wrapper.find('[data-testid="sca-label"]').text()).toBe('Select execution mode')
    expect(wrapper.find('[data-testid="radio-multi-terminal"]').attributes('aria-pressed')).toBe('false')
    expect(wrapper.find('[data-testid="radio-subagent"]').attributes('aria-pressed')).toBe('false')
    const stage = wrapper.find('[data-testid="jbf-stage"]')
    expect(stage.text()).toBe('Stage')
    expect(stage.attributes('aria-disabled')).toBe('true')
    expect(wrapper.find('[data-testid="sca-mode-reason"]').text()).toBe('Pick a mode first')
    expect(wrapper.find('[data-testid="jbf-implement"]').attributes('disabled')).toBeDefined()
    expect(has(wrapper, 'jb-btn-detail')).toBe(true)
    expect(has(wrapper, 'jb-btn-hub')).toBe(true)
    expect(has(wrapper, 'jb-btn-review')).toBe(false)
  })

  it('a press with no mode sends nothing; picking a mode makes Stage the filled step, and it stages in that mode', async () => {
    const wrapper = mountFooter(READY, JOBS_SECTION_LABELS.ACTIVATED)
    await flushPromises()
    await wrapper.find('[data-testid="jbf-stage"]').trigger('click')
    await flushPromises()
    expect(h.staging).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="staging-control-area"]').classes()).toContain('sca--pulse')

    await wrapper.find('[data-testid="radio-multi-terminal"]').trigger('click')
    await flushPromises()
    expect(h.update).toHaveBeenCalledWith('p-ready', { execution_mode: 'multi_terminal' })
    expect(has(wrapper, 'sca-mode-reason')).toBe(false)
    expect(wrapper.find('[data-testid="jbf-stage"]').classes()).toContain('jb-btn-primary')

    await wrapper.find('[data-testid="jbf-stage"]').trigger('click')
    await flushPromises()
    expect(h.staging).toHaveBeenCalledWith('p-ready', { tool: 'claude-code', execution_mode: 'multi_terminal' })
    expect(h.copy).toHaveBeenCalledWith('STAGING PROMPT')
    expect(wrapper.emitted('changed')).toBeTruthy()
    expect(wrapper.find('[data-testid="jbf-stage"]').text()).toBe('Unstage')
    expect(wrapper.find('[data-testid="jbf-stage"]').classes()).toContain('jb-btn-ghost')
  })

  it('FE-9749: a real-mode account default is preselected; "Ask every time" is not', async () => {
    h.getDefault.mockResolvedValue({ data: { execution_mode_default: 'subagent' } })
    const wrapper = mountFooter(READY, JOBS_SECTION_LABELS.ACTIVATED)
    await flushPromises()
    expect(wrapper.find('[data-testid="radio-subagent"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('[data-testid="jbf-stage"]').classes()).toContain('jb-btn-primary')
    expect(h.update).not.toHaveBeenCalled()
  })

  it('a row mode on a never-staged project is not pre-selected (the sloppy-stage incident)', async () => {
    const wrapper = mountFooter({ ...READY, id: 'p-row-mode', execution_mode: 'multi_terminal', mission: 'written at creation' }, JOBS_SECTION_LABELS.ACTIVATED)
    await flushPromises()
    expect(wrapper.find('[data-testid="radio-multi-terminal"]').attributes('aria-pressed')).toBe('false')
    expect(wrapper.find('[data-testid="radio-subagent"]').attributes('aria-pressed')).toBe('false')
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

const orchestratorAs = (status) => ({ agent_id: 'a-or', job_id: 'j-or', agent_display_name: 'orchestrator', status })

describe('JobsBoardCardFooter: implementing and review', () => {
  it('running: today\'s compact row, Jobs detail and the Hub link; no control area, no filled button', async () => {
    const wrapper = mountFooter(IMPLEMENTING, JOBS_SECTION_LABELS.IMPLEMENTING, { agents: [orchestratorAs('working')] })
    await flushPromises()
    expect(wrapper.attributes('data-footer-state')).toBe('implementing')
    expect(wrapper.attributes('data-run-state')).toBe('running')
    expect(has(wrapper, 'jb-btn-open')).toBe(false)
    expect(has(wrapper, 'jb-btn-detail')).toBe(true)
    expect(has(wrapper, 'jb-btn-hub')).toBe(true)
    for (const id of ['staging-control-area', 'jbf-stage', 'jbf-implement', 'jbf-mode-tag', 'sca-copy-prompt']) {
      expect(has(wrapper, id)).toBe(false)
    }
    expect(wrapper.findAll('.jb-btn-primary')).toHaveLength(0)
  })

  it('FE-9749 waiting for pickup: one filled Copy prompt with the hint; it copies without stamping', async () => {
    const wrapper = mountFooter(IMPLEMENTING, JOBS_SECTION_LABELS.IMPLEMENTING, { agents: [orchestratorAs('waiting')] })
    await flushPromises()
    expect(wrapper.attributes('data-run-state')).toBe('pickup')
    expect(wrapper.find('[data-testid="sca-pickup-hint"]').text()).toBe('No agent has picked this up yet')
    expect(wrapper.findAll('.jb-btn-primary')).toHaveLength(1)
    await wrapper.find('[data-testid="sca-copy-prompt"]').trigger('click')
    await flushPromises()
    expect(h.implementation).toHaveBeenCalledWith('p-impl')
    expect(h.copy).toHaveBeenCalledWith('IMPL PROMPT')
    expect(h.launchImplementation).not.toHaveBeenCalled()
  })

  it('FE-9749 waiting for pickup, folded: the Copy prompt stays as the one control', async () => {
    const wrapper = mountFooter(IMPLEMENTING, JOBS_SECTION_LABELS.IMPLEMENTING, { agents: [orchestratorAs('waiting')], compact: true })
    await flushPromises()
    expect(has(wrapper, 'sca-copy-prompt')).toBe(true)
    expect(has(wrapper, 'jb-btn-detail')).toBe(false)
  })

  it('FE-9749 quiet: a silent orchestrator shows only the grey Quiet chip, no re-copy button', async () => {
    const silent = { ...orchestratorAs('working'), orchestrator_state: { state: 'silent' } }
    const wrapper = mountFooter(IMPLEMENTING, 'Needs attention', { agents: [silent] })
    await flushPromises()
    expect(wrapper.attributes('data-run-state')).toBe('quiet')
    expect(wrapper.find('[data-testid="jbf-quiet-chip"]').text()).toBe('Quiet')
    expect(has(wrapper, 'sca-copy-prompt')).toBe(false)
    expect(wrapper.findAll('.jb-btn-primary')).toHaveLength(0)
  })

  it('a Needs attention card that has launched keeps the implementing row', async () => {
    const wrapper = mountFooter(IMPLEMENTING, 'Needs attention')
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
      for (const id of ['staging-control-area', 'jbf-stage', 'jbf-implement']) {
        expect(has(wrapper, id)).toBe(false)
      }
      expect(has(wrapper, 'jb-btn-open')).toBe(false)
    }
    expect(has(staged, 'jbf-mission')).toBe(false)
  })
})
