import { describe, it, expect, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import AgentJobModal from '@/components/projects/AgentJobModal.vue'

const vuetify = createVuetify({ components, directives })

const mountModal = (agent) =>
  mount(AgentJobModal, {
    props: { show: true, agent },
    global: { plugins: [vuetify] },
    attachTo: document.body,
  })

describe('AgentJobModal labels the agent job as a job, not a mission', () => {
  let wrapper

  afterEach(() => {
    wrapper?.unmount()
    document.body.innerHTML = ''
  })

  it('names the first tab "Job", because "Mission" is the orchestrator project mission elsewhere', async () => {
    wrapper = mountModal({
      job_id: 'job-1',
      agent_id: 'agent-1',
      agent_name: 'implementer',
      mission: 'Do X',
      todo_items: [],
    })
    await wrapper.vm.$nextTick()
    const tab = document.body.querySelector('[data-test="job-tab-mission"]')
    expect(tab).not.toBeNull()
    const label = tab.textContent.replace('mdi-text-box-outline', '').trim()
    expect(label).toBe('Job')
  })

  it('says "No job assigned yet." when the job has no text', async () => {
    wrapper = mountModal({
      job_id: 'job-2',
      agent_id: 'agent-2',
      agent_name: 'implementer',
      mission: '',
      todo_items: [],
    })
    await wrapper.vm.$nextTick()
    const text = document.body.querySelector('.mission-text')
    expect(text.textContent.trim()).toBe('No job assigned yet.')
  })
})
