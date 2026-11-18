import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/services/api', () => {
  const api = {
    prompts: { staging: vi.fn(), implementation: vi.fn() },
    orchestrator: { launchProject: vi.fn() },
    projects: { launchImplementation: vi.fn(), restage: vi.fn(), unstage: vi.fn(), update: vi.fn() },
    settings: { getExecutionModeDefault: vi.fn().mockResolvedValue({ data: { execution_mode_default: 'ask' } }) },
  }
  return { default: api, api }
})

import JobsBoardCard from './JobsBoardCard.vue'

const vuetify = createVuetify()
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
  ],
})
const tooltipStub = { template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>` }

function mountCard(props) {
  setActivePinia(createPinia())
  return mount(JobsBoardCard, {
    props: { now: Date.parse('2026-10-28T08:00:00Z'), agents: [], ...props },
    global: { plugins: [vuetify, router], stubs: { 'v-tooltip': tooltipStub } },
  })
}

const base = {
  id: 'p-1',
  taxonomy_alias: 'FE-1',
  name: 'Walk fixes',
  status: 'active',
  implementation_launched_at: null,
  created_at: '2026-10-28T06:57:00Z',
  mission: '',
}
const promptCopied = { ...base, id: 'p-copied', staging_status: 'staged', execution_mode: 'multi_terminal' }
const stagedComplete = { ...base, id: 'p-done', staging_status: 'staging_complete', execution_mode: 'subagent', mission: 'Do it' }
const fresh = { ...base, id: 'p-fresh', staging_status: null, execution_mode: null }

describe('JobsBoardCard after Stage was pressed and before the plan exists', () => {
  it('says to paste the prompt, with no gate note and no "awaiting your go"', () => {
    const w = mountCard({ project: promptCopied, headlessAllowed: false })
    expect(w.text()).toContain('Prompt copied. Paste it in your AI tool. Your tool writes the plan.')
    expect(w.find('[data-testid="jb-gate-note"]').exists()).toBe(false)
    expect(w.text()).not.toContain('awaiting your go')
    expect(w.text()).not.toContain('Your launch required')
    expect(w.attributes('data-lifecycle')).toBe('Planning')
  })
})

describe('JobsBoardCard staging gate note', () => {
  it('uses the three lines and names agent self-advance', () => {
    const w = mountCard({ project: stagedComplete, headlessAllowed: false })
    const note = w.find('[data-testid="jb-gate-note"]')
    expect(note.text()).toContain('Your go is needed')
    expect(note.text()).toContain('Agents stop here and wait for you. This is the staging gate.')
    expect(note.text()).toContain(
      'To let a trusted agent go on its own later, turn on agent self-advance in Tools → Agents.',
    )
    expect(note.text()).not.toContain('Headless')
    expect(w.find('[data-testid="jb-gate-note-link"]').exists()).toBe(true)
  })
})

describe('JobsBoardCard next-press pulse', () => {
  const pulsing = (w) => w.findAll('.next-press-pulse')

  it('focused card, no mode: exactly one element pulses (the mode box)', async () => {
    const w = mountCard({ project: fresh, focused: true })
    await flushPromises()
    expect(pulsing(w)).toHaveLength(1)
    expect(pulsing(w)[0].attributes('data-testid')).toBe('jbf-run-as')
  })

  it('focused, staged and waiting: exactly one element pulses (Implement)', async () => {
    const w = mountCard({ project: stagedComplete, focused: true, headlessAllowed: true })
    await flushPromises()
    expect(pulsing(w)).toHaveLength(1)
    expect(pulsing(w)[0].attributes('data-testid')).toBe('jbf-implement')
  })

  it('focused, prompt copied: nothing pulses', async () => {
    const w = mountCard({ project: promptCopied, focused: true })
    await flushPromises()
    expect(pulsing(w)).toHaveLength(0)
  })

  it('a board of ten staged cards pulses nowhere when none is in focus', async () => {
    const cards = Array.from({ length: 10 }, (_, i) => mountCard({ project: { ...stagedComplete, id: `s${i}` } }))
    await flushPromises()
    expect(cards.flatMap((w) => w.findAll('.next-press-pulse'))).toHaveLength(0)
  })

  it('a chain member never pulses even when focused', async () => {
    const w = mountCard({ project: fresh, focused: true, chainCtx: { runId: 'r1' } })
    await flushPromises()
    expect(pulsing(w)).toHaveLength(0)
  })
})
