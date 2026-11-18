import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

import ThreadTimeline from '@/components/hub/ThreadTimeline.vue'
import { useCommHubStore } from '@/stores/commHubStore'

const vuetify = createVuetify()
const THREAD_ID = 'thr-sec0057'
const IMAGE_URL = 'https://collector.example/p.png?d=tenant-secret'

describe('ThreadTimeline agent post with a remote image (SEC-0057)', () => {
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    const store = useCommHubStore()
    store.selectedThreadId = THREAD_ID
    store.handleThreadMessage({
      thread_id: THREAD_ID,
      message_id: 'msg-img',
      from_agent_id: 'implementer',
      from_kind: 'agent',
      from_display_name: 'implementer',
      content: `Build is green. ![status](${IMAGE_URL})`,
      message_type: 'broadcast',
      created_at: '2026-11-10T06:00:00Z',
    })
  })

  it('renders no <img> pointing at the outside host, and shows the URL as a link', () => {
    const wrapper = mount(ThreadTimeline, { global: { plugins: [pinia, vuetify] } })
    const body = wrapper.find('[data-testid="timeline-message-msg-img"] [data-testid="message-content"]')
    expect(body.exists()).toBe(true)
    expect(body.find('img').exists()).toBe(false)
    const link = body.find('a')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe(IMAGE_URL)
    expect(link.text()).toBe(IMAGE_URL)
  })
})
