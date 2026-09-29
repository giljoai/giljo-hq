import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { computed, defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ProjectStatusBanner from './ProjectStatusBanner.vue'
import { useProjectCloseout } from '@/composables/useProjectCloseout'

vi.mock('@/services/api', () => {
  const apiObj = {
    products: {
      getMemoryEntries: vi.fn(() => Promise.resolve({ data: { entries: [] } })),
    },
    projects: {
      closeoutWithoutSummary: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
  }
  return { default: apiObj, api: apiObj }
})

vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({ clearForProject: vi.fn() }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

const globalStubs = {
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-chip': {
    template: '<div class="v-chip" v-bind="$attrs"><slot name="prepend" /><slot /></div>',
  },
  'v-btn': { template: '<button class="v-btn" v-bind="$attrs"><slot /></button>' },
  'v-progress-circular': { template: '<div class="v-progress-circular" />' },
  'v-dialog': {
    props: ['modelValue'],
    template: '<div v-if="modelValue" class="v-dialog"><slot /></div>',
  },
  'v-card': { template: '<div class="v-card" v-bind="$attrs"><slot /></div>' },
  'v-card-text': { template: '<div class="v-card-text"><slot /></div>' },
  'v-textarea': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template:
      '<textarea v-bind="$attrs" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'v-spacer': { template: '<span />' },
}

const DECOMMISSIONED_JOBS = [
  { agent_display_name: 'orchestrator', status: 'decommissioned' },
  { agent_display_name: 'implementer', status: 'decommissioned' },
  { agent_display_name: 'tester', status: 'decommissioned' },
]

function mountHost({ status = 'active', jobs = DECOMMISSIONED_JOBS } = {}) {
  const project = ref({ id: 'proj-1', project_id: 'proj-1', product_id: 'prod-1', status })
  let closeout
  const Host = defineComponent({
    setup() {
      closeout = useProjectCloseout({
        project,
        projectId: computed(() => 'proj-1'),
        sortedJobs: computed(() => jobs),
      })
      return () =>
        h(ProjectStatusBanner, {
          projectDoneStatus: closeout.projectDoneStatus.value,
          showCloseoutButton: closeout.showCloseoutButton.value,
          showMemoryPending: closeout.showMemoryPending.value,
          allJobsTerminal: closeout.allJobsTerminal.value,
          memoryPollTimedOut: closeout.memoryPollTimedOut.value,
          memoryPollError: closeout.memoryPollError.value,
          closingWithoutSummary: closeout.closingWithoutSummary.value,
          onCloseWithoutSummary: (reason) => closeout.closeWithoutSummary(reason),
        })
    },
  })
  const wrapper = mount(Host, { global: { stubs: globalStubs } })
  return { wrapper, project, closeout: () => closeout }
}

async function flush() {
  for (let i = 0; i < 4; i += 1) await nextTick()
}

describe('FE-9651: stopped project with no closeout', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.useFakeTimers()
    const api = (await import('@/services/api')).default
    api.products.getMemoryEntries.mockResolvedValue({ data: { entries: [] } })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows the saving spinner while the memory poll is still waiting', async () => {
    const { wrapper } = mountHost()
    await flush()
    expect(wrapper.find('[data-testid="memory-pending-chip"]').exists()).toBe(true)
  })

  it('leaves the spinner after the timeout and offers Close without agent summary', async () => {
    const { wrapper } = mountHost()
    await flush()

    vi.advanceTimersByTime(30_000)
    await flush()

    expect(wrapper.find('[data-testid="memory-pending-chip"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="memory-poll-error-chip"]').exists()).toBe(true)
    const closeBtn = wrapper.find('[data-testid="close-without-summary-btn"]')
    expect(closeBtn.exists()).toBe(true)
    expect(closeBtn.text()).toBe('Close without agent summary')
  })

  it('the close action confirms, writes the closeout through the API, then lands on Review project', async () => {
    const api = (await import('@/services/api')).default
    const { wrapper } = mountHost()
    await flush()
    vi.advanceTimersByTime(30_000)
    await flush()

    api.products.getMemoryEntries.mockResolvedValue({ data: { entries: [{ id: 'm1' }] } })
    await wrapper.find('[data-testid="close-without-summary-btn"]').trigger('click')
    await flush()
    expect(api.projects.closeoutWithoutSummary).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="close-without-summary-dialog"]').exists()).toBe(true)
    await wrapper
      .find('[data-testid="close-without-summary-reason"]')
      .setValue('Work finished elsewhere')
    await wrapper.find('[data-testid="close-without-summary-confirm"]').trigger('click')
    await flush()

    expect(api.projects.closeoutWithoutSummary).toHaveBeenCalledTimes(1)
    expect(api.projects.closeoutWithoutSummary).toHaveBeenCalledWith(
      'proj-1',
      'Work finished elsewhere',
    )
    expect(wrapper.find('[data-testid="memory-poll-error-chip"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="close-project-btn"]').exists()).toBe(true)
  })

  it('memory written and project still active reads Ready for review, never closed', async () => {
    const api = (await import('@/services/api')).default
    api.products.getMemoryEntries.mockResolvedValue({ data: { entries: [{ id: 'm1' }] } })
    const { wrapper } = mountHost({ status: 'active' })
    await flush()

    expect(wrapper.find('[data-testid="close-project-btn"]').exists()).toBe(true)
    const chip = wrapper.find('[data-testid="ready-for-review-chip"]')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('Ready for review')
    expect(wrapper.text()).not.toMatch(/closed/i)
  })
})
