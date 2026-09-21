import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import RoadmapCard from './RoadmapCard.vue'

const vBtnStub = {
  template: '<button class="v-btn" :disabled="disabled" v-bind="$attrs"><slot /></button>',
  props: ['disabled'],
}

const stubs = {
  'v-btn': vBtnStub,
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-tooltip': { template: '<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>' },
}

const inactiveProject = {
  item_type: 'project',
  status: 'inactive',
  title: 'Fix login',
  taxonomy_alias: 'BE-0001',
  project_id: 'proj-1',
  id: 'rm-item-pk',
}

const pendingTask = {
  item_type: 'task',
  status: 'pending',
  title: 'Write onboarding copy',
  taxonomy_alias: '',
  task_id: 'task-1',
  id: 'rm-item-pk-2',
}

function mountCard(props = {}) {
  return mount(RoadmapCard, {
    props: { item: inactiveProject, rank: 1, ...props },
    global: { stubs },
  })
}

describe('RoadmapCard — launch/selection controls REMOVED (FE-9568, 2026-09-02)', () => {
  it('never renders a selection checkbox — link mode no longer exists', () => {
    const wrapper = mountCard()
    expect(wrapper.find('[data-testid^="roadmap-select-checkbox"]').exists()).toBe(false)
  })

  it('never renders an Activate button for an inactive project', () => {
    const wrapper = mountCard()
    expect(wrapper.find('.rm-primary-btn').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Activate')
  })

  it('never renders a Deactivate button for an activated project', () => {
    const wrapper = mountCard({ item: { ...inactiveProject, status: 'active' } })
    expect(wrapper.text()).not.toContain('Deactivate')
  })

  it('does not emit activate, deactivate, or toggle-select — those events no longer exist on the component', () => {
    const wrapper = mountCard({ inChain: true })
    expect(wrapper.emitted('activate')).toBeFalsy()
    expect(wrapper.emitted('deactivate')).toBeFalsy()
    expect(wrapper.emitted('toggle-select')).toBeFalsy()
  })

  it('ignores the retired selected/electionActive/linkMode/lockedInChain props (no crash, no residual UI)', () => {
    const wrapper = mountCard({
      selected: true,
      electionActive: true,
      linkMode: true,
      lockedInChain: true,
    })
    expect(wrapper.find('[data-testid^="roadmap-select-checkbox"]').exists()).toBe(false)
    expect(wrapper.find('.rm-primary-btn').exists()).toBe(false)
  })
})

describe('RoadmapCard — "In chain" pill is a read-only badge (FE-9568 kept membership indicator)', () => {
  it('shows the pill for an in-chain project with no click handler wired', async () => {
    const wrapper = mountCard({ inChain: true })
    const pill = wrapper.find('[data-testid="roadmap-in-chain-pill"]')
    expect(pill.exists()).toBe(true)
    await pill.trigger('click')
    expect(wrapper.emitted('open-chain')).toBeFalsy()
  })

  it('does not render the pill when not in a chain', () => {
    const wrapper = mountCard({ inChain: false })
    expect(wrapper.find('[data-testid="roadmap-in-chain-pill"]').exists()).toBe(false)
  })

  it('does not render the pill for a task even if in-chain is somehow set', () => {
    const wrapper = mountCard({ item: pendingTask, inChain: true })
    expect(wrapper.find('[data-testid="roadmap-in-chain-pill"]').exists()).toBe(false)
  })

  it('FE-9628: a completed in-chain project shows ONE chip — COMPLETED, not COMPLETED + In chain', () => {
    const wrapper = mountCard({ item: { ...inactiveProject, status: 'completed' }, inChain: true })
    expect(wrapper.find('[data-testid="roadmap-in-chain-pill"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('COMPLETED')
    expect(wrapper.text()).not.toContain('In chain')
  })

  it('FE-9628: an activated in-chain project shows ONE chip — ACTIVATED, not ACTIVATED + In chain', () => {
    const wrapper = mountCard({ item: { ...inactiveProject, status: 'active' }, inChain: true })
    expect(wrapper.find('[data-testid="roadmap-in-chain-pill"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('ACTIVATED')
    expect(wrapper.text()).not.toContain('In chain')
  })
})

describe('RoadmapCard — kept controls (Convert / Open / Demote / Remove)', () => {
  it('renders Convert to Project for a task and emits convert on click', async () => {
    const wrapper = mountCard({ item: pendingTask })
    const convertBtn = wrapper.find('.rm-convert-btn')
    expect(convertBtn.exists()).toBe(true)
    await convertBtn.trigger('click')
    expect(wrapper.emitted('convert')).toBeTruthy()
    expect(wrapper.emitted('convert')[0][0]).toMatchObject({ task_id: 'task-1' })
  })

  it('never renders Convert to Project for a project', () => {
    const wrapper = mountCard()
    expect(wrapper.find('.rm-convert-btn').exists()).toBe(false)
  })

  it('emits open, demote, and remove for the icon action row', async () => {
    const wrapper = mountCard()
    await wrapper.find('[aria-label="Open project"]').trigger('click')
    await wrapper.find('[aria-label="Demote to bottom"]').trigger('click')
    await wrapper.find('[aria-label="Remove Fix login from the roadmap"]').trigger('click')
    expect(wrapper.emitted('open')).toBeTruthy()
    expect(wrapper.emitted('demote')).toBeTruthy()
    expect(wrapper.emitted('remove')).toBeTruthy()
  })
})
