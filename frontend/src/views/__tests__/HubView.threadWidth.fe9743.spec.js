import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import viewSource from '@/views/HubView.vue?raw'

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/websocketEventRouter', () => ({ registerReconnectResync: () => () => {} }))

import HubView from '@/views/HubView.vue'
import { useCommHubStore } from '@/stores/commHubStore'

const stubs = {
  ThreadList: { template: '<div class="stub-thread-list" />' },
  ThreadTimeline: { props: ['search'], template: '<div class="stub-timeline" />' },
  HubComposer: { template: '<div class="stub-composer" />' },
  AgentPill: { template: '<span />' },
  NewThreadDialog: { template: '<div />' },
  ThreadCreatedDialog: { template: '<div />' },
  ThreadDeletedDialog: { template: '<div />' },
}

async function mountHub(open) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(HubView, { global: { plugins: [pinia], stubs } })
  if (open) {
    const store = useCommHubStore()
    store._testSeedThread({ thread_id: 'thr-1', chat_id: 'CHT-0001', subject: 'Test' })
    store.selectThread('thr-1')
  }
  await flushPromises()
  return wrapper
}

describe('HubView thread view max-width (FE-9743)', () => {
  it('3: the toolbar, header frames, timeline and composer all sit inside the one capped wrapper', async () => {
    const wrapper = await mountHub(true)
    const root = wrapper.get('.hub-view__thread')
    expect(root.attributes('data-testid')).toBe('hub-thread-view')
    expect(root.find('.hub-thread-toolbar').exists()).toBe(true)
    expect(root.find('[data-testid="thread-header"]').exists()).toBe(true)
    expect(root.find('.stub-timeline').exists()).toBe(true)
    expect(root.find('.stub-composer').exists()).toBe(true)
  })

  it('3: the list view does not render the thread wrapper', async () => {
    const wrapper = await mountHub(false)
    expect(wrapper.find('.hub-view__thread').exists()).toBe(false)
  })

  it('3: the cap is one SCSS variable, applied once, with no auto margin that would centre it', () => {
    expect(viewSource.match(/\$hub-thread-max-width:\s*1200px/g)).toHaveLength(1)
    const rule = viewSource.match(/&__thread\s*\{([^}]*)\}/)
    expect(rule).not.toBeNull()
    expect(rule[1]).toMatch(/max-width:\s*\$hub-thread-max-width/)
    expect(rule[1]).not.toMatch(/margin-inline:\s*auto|margin:\s*0 auto/)
    expect(viewSource.match(/1200px/g)).toHaveLength(1)
  })
})
