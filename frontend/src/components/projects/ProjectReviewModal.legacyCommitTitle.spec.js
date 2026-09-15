import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import ProjectReviewModal from '@/components/projects/ProjectReviewModal.vue'
import api from '@/services/api'

const vuetify = createVuetify()

const hubRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/hub', name: 'Hub', component: { template: '<div />' } },
  ],
})
const PROJECT_ID = 'proj-be9256'

function makeReviewResponse(commits) {
  return {
    data: {
      project: {
        id: PROJECT_ID,
        project_id: PROJECT_ID,
        name: 'BE-9256 Test Project',
        execution_mode: 'subagent',
        status: 'completed',
        agents: [],
      },
      agent_jobs: [],
      memory_entries: [
        {
          id: 'm1',
          git_commits: commits,
        },
      ],
    },
  }
}

async function mountModal() {
  const pinia = createPinia()
  setActivePinia(pinia)

  const wrapper = mount(ProjectReviewModal, {
    props: { show: false, projectId: PROJECT_ID },
    global: { plugins: [pinia, vuetify, hubRouter] },
  })

  await wrapper.setProps({ show: true })
  await flushPromises()

  return wrapper
}

describe('ProjectReviewModal.vue — legacy titleless commit-row floor (BE-9256)', () => {
  beforeEach(() => {
    api.threads = {
      list: vi.fn().mockResolvedValue({ data: { threads: [] } }),
      history: vi.fn().mockResolvedValue({ data: { thread: null, messages: [] } }),
      create: vi.fn(),
    }
  })

  it('renders the short SHA for a legacy empty-message commit row, never blank', async () => {
    api.projects.review = vi.fn().mockResolvedValue(
      makeReviewResponse([
        { sha: '569905bd0abcdef1234567890', message: '' },
      ])
    )
    const wrapper = await mountModal()

    const rows = wrapper.findAll('.commit-row')
    expect(rows.length).toBe(1)
    const text = rows[0].find('.text-body-medium').text()
    expect(text).not.toBe('')
    expect(text).toBe('569905bd')
  })

  it('renders the real message unchanged for a titled commit row', async () => {
    api.projects.review = vi.fn().mockResolvedValue(
      makeReviewResponse([{ sha: 'aaa1112223334445556667778', message: 'BE-9256: fail-closed validator' }])
    )
    const wrapper = await mountModal()

    const rows = wrapper.findAll('.commit-row')
    expect(rows[0].find('.text-body-medium').text()).toBe('BE-9256: fail-closed validator')
  })

  it('keeps the existing "No commits recorded" placeholder when there are none', async () => {
    api.projects.review = vi.fn().mockResolvedValue(makeReviewResponse([]))
    const wrapper = await mountModal()

    expect(wrapper.text()).toContain('No commits recorded')
    expect(wrapper.findAll('.commit-row').length).toBe(0)
  })
})
