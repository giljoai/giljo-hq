import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ProjectStatusBanner from './ProjectStatusBanner.vue'

const globalStubs = {
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-chip': { template: '<div class="v-chip"><slot /></div>' },
  'v-btn': { template: '<button class="v-btn" v-bind="$attrs"><slot /></button>' },
  'v-progress-circular': { template: '<div class="v-progress-circular" />' },
}

function mountBanner(props = {}) {
  return mount(ProjectStatusBanner, {
    props: {
      projectDoneStatus: null,
      orchestratorCloseoutBlocked: false,
      showOrchUnlockedBanner: false,
      showCloseoutButton: false,
      showMemoryPending: false,
      allJobsTerminal: false,
      memoryPollTimedOut: false,
      memoryPollError: false,
      isChainMember: false,
      ...props,
    },
    global: { stubs: globalStubs },
  })
}

describe('ProjectStatusBanner', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders nothing when all props are false/null', () => {
    const wrapper = mountBanner()
    expect(wrapper.find('[data-testid="project-done-banner"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="closeout-decision-banner"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="close-project-btn"]').exists()).toBe(false)
  })

  it('shows done banner when projectDoneStatus is "completed"', () => {
    const wrapper = mountBanner({ projectDoneStatus: 'completed' })
    expect(wrapper.find('[data-testid="project-done-banner"]').exists()).toBe(true)
  })

  it('shows done banner when projectDoneStatus is "terminated"', () => {
    const wrapper = mountBanner({ projectDoneStatus: 'terminated' })
    expect(wrapper.find('[data-testid="project-done-banner"]').exists()).toBe(true)
  })

  it('decision banner title reads "Needs decision"', () => {
    const wrapper = mountBanner({ orchestratorCloseoutBlocked: true })
    expect(wrapper.find('.closeout-decision-title').text()).toBe('Needs decision')
  })

  it('shows decision banner when orchestratorCloseoutBlocked is true', () => {
    const wrapper = mountBanner({ orchestratorCloseoutBlocked: true })
    expect(wrapper.find('[data-testid="closeout-decision-banner"]').exists()).toBe(true)
  })

  it('clicking decision banner emits open-decision-modal', async () => {
    const wrapper = mountBanner({ orchestratorCloseoutBlocked: true })
    await wrapper.find('[data-testid="closeout-decision-banner"]').trigger('click')
    expect(wrapper.emitted('open-decision-modal')).toBeTruthy()
  })

  it('shows unlocked banner when showOrchUnlockedBanner is true', () => {
    const wrapper = mountBanner({ showOrchUnlockedBanner: true })
    expect(wrapper.find('[data-testid="orchestrator-unlocked-banner"]').exists()).toBe(true)
  })

  it('clicking dismiss on unlocked banner emits dismiss-orch-unlocked', async () => {
    const wrapper = mountBanner({ showOrchUnlockedBanner: true })
    await wrapper.find('[data-testid="orchestrator-unlocked-dismiss"]').trigger('click')
    expect(wrapper.emitted('dismiss-orch-unlocked')).toBeTruthy()
  })

  it('shows closeout button when showCloseoutButton is true', () => {
    const wrapper = mountBanner({ showCloseoutButton: true })
    expect(wrapper.find('[data-testid="close-project-btn"]').exists()).toBe(true)
  })

  it('clicking closeout button emits open-closeout-modal', async () => {
    const wrapper = mountBanner({ showCloseoutButton: true })
    await wrapper.find('[data-testid="close-project-btn"]').trigger('click')
    expect(wrapper.emitted('open-closeout-modal')).toBeTruthy()
  })

  it('shows memory-pending chip when showMemoryPending is true', () => {
    const wrapper = mountBanner({ showMemoryPending: true })
    expect(wrapper.find('[data-testid="memory-pending-chip"]').exists()).toBe(true)
  })
})

describe('ProjectStatusBanner — FE-9191 Review project on the completed pill', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('shows the Review project button beside the done pill when projectDoneStatus is "completed"', () => {
    const wrapper = mountBanner({ projectDoneStatus: 'completed' })
    expect(wrapper.find('[data-testid="project-done-banner"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="review-completed-btn"]').exists()).toBe(true)
  })

  it('clicking Review project on the completed pill emits open-closeout-modal', async () => {
    const wrapper = mountBanner({ projectDoneStatus: 'completed' })
    await wrapper.find('[data-testid="review-completed-btn"]').trigger('click')
    expect(wrapper.emitted('open-closeout-modal')).toBeTruthy()
  })

  it('does NOT render the Review project button on an active project (no done status)', () => {
    const wrapper = mountBanner({ projectDoneStatus: null })
    expect(wrapper.find('[data-testid="review-completed-btn"]').exists()).toBe(false)
  })

  it('does NOT render the Review project button for terminated projects (pill only)', () => {
    const wrapper = mountBanner({ projectDoneStatus: 'terminated' })
    expect(wrapper.find('[data-testid="project-done-banner"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="review-completed-btn"]').exists()).toBe(false)
  })

  it('does NOT render the Review project button for cancelled projects (pill only)', () => {
    const wrapper = mountBanner({ projectDoneStatus: 'cancelled' })
    expect(wrapper.find('[data-testid="review-completed-btn"]').exists()).toBe(false)
  })
})

describe('ProjectStatusBanner — FE-9244 stacked layout + chain-mode gating', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('applies the stacked modifier class to State A only, not to State B', () => {
    const doneWrapper = mountBanner({ projectDoneStatus: 'completed' })
    expect(doneWrapper.find('[data-testid="project-done-banner"]').element.parentElement.classList.contains('action-buttons-row--stacked')).toBe(true)

    const closeoutWrapper = mountBanner({ showCloseoutButton: true })
    expect(closeoutWrapper.find('[data-testid="close-project-btn"]').element.parentElement.classList.contains('action-buttons-row--stacked')).toBe(false)
  })

  it('solo mode (isChainMember false, default): Review project button still renders when completed — byte-identical to prior behavior', () => {
    const wrapper = mountBanner({ projectDoneStatus: 'completed', isChainMember: false })
    expect(wrapper.find('[data-testid="project-done-banner"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="review-completed-btn"]').exists()).toBe(true)
  })

  it('chain mode (isChainMember true) + completed: hides the Review project button, pill still shows', () => {
    const wrapper = mountBanner({ projectDoneStatus: 'completed', isChainMember: true })
    expect(wrapper.find('[data-testid="project-done-banner"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="review-completed-btn"]').exists()).toBe(false)
  })
})
