/**
 * RoadmapCard.vue — FE-6165f (locked "In chain" checkbox merge), updated
 * FE-9568 (2026-09-02, operator ruling — scope reversal).
 *
 * FE-6165f merged the "In chain" pill with a locked link-mode checkbox
 * (inChain force-ticks + disables it) and the FE-6165a election-fade on the
 * per-card Activate button. FE-9568 removed the link-mode checkbox and the
 * Activate/Deactivate buttons entirely — /roadmap only orders work now. This
 * file is kept (not deleted) to record that reversal and assert the checkbox
 * + election-fade mechanism is genuinely gone; the "In chain" pill itself
 * SURVIVES as a plain read-only badge, so its render/non-render tests stay.
 *
 * Edition Scope: CE
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import RoadmapCard from '@/components/RoadmapCard.vue'

// Reuse the same minimal stubs as the existing RoadmapCard.spec.js.
const stubs = {
  'v-btn': {
    template: '<button class="v-btn" v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
  },
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-tooltip': {
    props: ['text'],
    template: '<div class="v-tooltip" :data-text="text"><slot name="activator" :props="{}" /></div>',
  },
}

const PROJECT_ITEM = {
  id: 'rmi-1',
  item_type: 'project',
  project_id: 'p-1',
  task_id: null,
  title: 'Core database schema',
  taxonomy_alias: 'BE-0001',
  status: 'inactive',
  priority: 0,
  risk: 'low',
  complexity: 'heavy',
}

function mountCard(extraProps = {}) {
  return mount(RoadmapCard, {
    props: { item: PROJECT_ITEM, rank: 1, ...extraProps },
    global: { stubs },
  })
}

describe('RoadmapCard.vue — FE-6165f inChain prop (checkbox mechanism REMOVED by FE-9568)', () => {
  it('never renders a select checkbox, in-chain or not, even if legacy link-mode props are passed', () => {
    const w = mountCard({ linkMode: true, inChain: true, lockedInChain: true })
    expect(w.find('[data-testid="roadmap-select-checkbox-rmi-1"]').exists()).toBe(false)
  })

  it('renders the "In chain" pill when inChain=true', () => {
    const w = mountCard({ inChain: true })
    const pill = w.find('[data-testid="roadmap-in-chain-pill"]')
    expect(pill.exists()).toBe(true)
    expect(pill.text()).toBe('In chain')
  })

  it('does NOT render the pill when inChain=false (default)', () => {
    const w = mountCard({ inChain: false })
    expect(w.find('[data-testid="roadmap-in-chain-pill"]').exists()).toBe(false)
  })

  it('chain member shows the In-chain badge with no Activate button behind it (FE-6170)', () => {
    // FE-6170: for a chain member the action-rail Activate button was REPLACED
    // by the "In chain" badge. FE-9568 then removed Activate entirely, so there
    // is no Activate button for ANY project state, faded or otherwise.
    const w = mountCard({ inChain: true, electionActive: true })
    expect(w.find('[data-testid="roadmap-in-chain-pill"]').exists()).toBe(true)
    expect(w.find('.rm-primary-btn--election-faded').exists()).toBe(false)
    expect(w.find('.rm-primary-btn').exists()).toBe(false)
  })

  it('election-fade no longer applies to anything — the Activate button it faded is gone (FE-6170/FE-9568)', () => {
    const w = mountCard({ inChain: false, electionActive: true })
    expect(w.find('.rm-primary-btn--election-faded').exists()).toBe(false)
    expect(w.find('.rm-primary-btn').exists()).toBe(false)
  })
})
