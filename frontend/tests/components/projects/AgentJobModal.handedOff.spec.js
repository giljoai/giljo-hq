import { describe, it, expect, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import AgentJobModal from '@/components/projects/AgentJobModal.vue'

const vuetify = createVuetify({ components, directives })

const mountPlan = (todoItems) =>
  mount(AgentJobModal, {
    props: {
      show: true,
      initialTab: 'plan',
      agent: { job_id: 'job-1', agent_id: 'agent-1', agent_name: 'orchestrator', mission: 'M', todo_items: todoItems },
    },
    global: { plugins: [vuetify] },
    attachTo: document.body,
  })

const rows = () => Array.from(document.body.querySelectorAll('[data-test="todo-item-row"]'))
const counter = () => document.body.querySelector('[data-test="plan-counter"]')

describe('AgentJobModal shows a handed-off step as handed off, not as an empty box', () => {
  let wrapper

  afterEach(() => {
    wrapper?.unmount()
    document.body.innerHTML = ''
  })

  it('labels a skipped step "Handed off" with its own icon', async () => {
    wrapper = mountPlan([
      { content: 'Ship the fix', status: 'completed' },
      { content: 'HANDOFF TSK-0003: new token issued by the operator', status: 'skipped' },
    ])
    await wrapper.vm.$nextTick()
    const [done, handed] = rows()
    expect(done.querySelector('[data-test="todo-handed-off"]')).toBeNull()
    expect(handed.querySelector('[data-test="todo-handed-off"]').textContent.trim()).toBe('Handed off')
    expect(handed.innerHTML).toContain('mdi-account-arrow-right')
    expect(handed.innerHTML).not.toContain('mdi-checkbox-blank-outline')
  })

  it('counts done and handed-off steps separately', async () => {
    wrapper = mountPlan([
      { content: 'a', status: 'completed' },
      { content: 'b', status: 'completed' },
      { content: 'HANDOFF TSK-1: c', status: 'skipped' },
    ])
    await wrapper.vm.$nextTick()
    expect(counter().textContent.trim()).toBe('2 done, 1 handed off')
  })

  it('names the steps still to do when the plan is unfinished', async () => {
    wrapper = mountPlan([
      { content: 'a', status: 'completed' },
      { content: 'HANDOFF TSK-1: b', status: 'skipped' },
      { content: 'c', status: 'in_progress' },
      { content: 'd', status: 'pending' },
    ])
    await wrapper.vm.$nextTick()
    expect(counter().textContent.trim()).toBe('1 done, 1 handed off, 2 to do')
  })

  it('adds no counter to a plan with nothing handed off', async () => {
    wrapper = mountPlan([
      { content: 'a', status: 'completed' },
      { content: 'b', status: 'pending' },
    ])
    await wrapper.vm.$nextTick()
    expect(rows()).toHaveLength(2)
    expect(counter()).toBeNull()
  })
})
