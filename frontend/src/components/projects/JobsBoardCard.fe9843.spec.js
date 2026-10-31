import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
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

const staged = {
  id: 'p-2',
  taxonomy_alias: 'FE-9843',
  name: 'A2',
  status: 'active',
  staging_status: 'staged',
  implementation_launched_at: null,
  created_at: '2026-10-28T06:57:00Z',
}

describe('JobsBoardCard staged chain member (FE-9843 rework)', () => {
  it('standalone staged card with headless off still shows the gate note', () => {
    const w = mountCard({ project: staged, headlessAllowed: false })
    expect(w.find('[data-testid="jb-gate-note"]').exists()).toBe(true)
    expect(w.text()).toContain('awaiting your go')
  })

  it('chain member: no gate note and no "awaiting your go"', () => {
    const w = mountCard({ project: staged, headlessAllowed: false, chainCtx: { runId: 'r1' } })
    expect(w.find('[data-testid="jb-gate-note"]').exists()).toBe(false)
    expect(w.text()).not.toContain('awaiting your go')
    expect(w.text()).not.toContain('Your launch required')
  })
})
