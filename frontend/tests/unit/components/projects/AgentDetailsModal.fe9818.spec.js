/**
 * FE-9818: Agent Details shows the template the job is bound to.
 *
 * The incident: a job bound to "implementer-3" (product A) showed
 * "implementer-backend-yapper" (product B) because the window listed every
 * template on the account and took the first one whose ROLE matched.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import AgentDetailsModal from '@/components/projects/AgentDetailsModal.vue'
import api from '@/services/api'

vi.mock('@/config/agentColors', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, getAgentColor: () => ({ hex: '#4a90d9' }) }
})

const PRODUCT_A = 'product-a'
const PRODUCT_B = 'product-b'

// Same role, different products; the other product's template is listed FIRST,
// which is what an unordered account-wide read handed back in the incident.
const TEMPLATES = [
  {
    id: 'tpl-yapper',
    name: 'implementer-backend-yapper',
    role: 'implementer',
    product_id: PRODUCT_B,
  },
  { id: 'tpl-impl-3', name: 'implementer-3', role: 'implementer', product_id: PRODUCT_A },
]

const PREVIEWS = {
  'tpl-yapper': '# implementer-backend-yapper profile',
  'tpl-impl-3': '# implementer-3 profile',
}

function serveTemplates(templates = TEMPLATES) {
  // Behaves like the server: product_id narrows the list, omitting it returns the account.
  api.templates.list.mockImplementation((params = {}) =>
    Promise.resolve({
      data: params.product_id
        ? templates.filter((t) => t.product_id === params.product_id)
        : templates,
    }),
  )
  api.templates.preview.mockImplementation((id) =>
    PREVIEWS[id]
      ? Promise.resolve({ data: { preview: PREVIEWS[id] } })
      : Promise.reject({ response: { status: 404, data: { detail: 'Template not found' } } }),
  )
  api.projects.get.mockImplementation((id) =>
    Promise.resolve({ data: { id, product_id: id === 'project-a' ? PRODUCT_A : PRODUCT_B } }),
  )
}

function mountFor(agent) {
  return mount(AgentDetailsModal, {
    props: {
      modelValue: true,
      agent: {
        job_id: 'job-1',
        agent_id: 'agent-1',
        agent_display_name: 'implementer',
        agent_name: 'implementer-3',
        project_id: 'project-a',
        ...agent,
      },
    },
    global: {
      plugins: [createVuetify({ components, directives })],
      stubs: {
        'v-dialog': {
          template: '<div class="v-dialog" v-if="modelValue"><slot /></div>',
          props: ['modelValue'],
        },
      },
    },
  })
}

describe('AgentDetailsModal shows the bound template (FE-9818)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    serveTemplates()
  })

  it('a job row carrying template_id shows that template and never lists the account', async () => {
    const wrapper = mountFor({ template_id: 'tpl-impl-3' })
    await flushPromises()

    expect(api.templates.preview).toHaveBeenCalledWith('tpl-impl-3', {})
    expect(api.templates.list).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('# implementer-3 profile')
    expect(wrapper.text()).not.toContain('yapper')
  })

  it('without template_id, a same-role template on another product is never shown', async () => {
    const wrapper = mountFor({ template_id: null })
    await flushPromises()

    expect(wrapper.text()).not.toContain('yapper')
    expect(api.templates.preview).not.toHaveBeenCalledWith('tpl-yapper', {})
    expect(wrapper.text()).toContain('# implementer-3 profile')
    expect(api.templates.list).toHaveBeenCalledWith(
      expect.objectContaining({ product_id: PRODUCT_A }),
    )
  })

  it('without template_id and no exact name in the job product, says the template was not found', async () => {
    const wrapper = mountFor({ template_id: null, agent_name: 'implementer-9' })
    await flushPromises()

    expect(api.templates.preview).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('yapper')
    expect(wrapper.text()).toContain('Template not found')
  })

  it('a role-only or substring match is not a match', async () => {
    serveTemplates([
      {
        id: 'tpl-yapper',
        name: 'implementer-backend-yapper',
        role: 'implementer',
        product_id: PRODUCT_A,
      },
    ])
    const wrapper = mountFor({ template_id: null, agent_name: 'implementer' })
    await flushPromises()

    expect(api.templates.preview).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Template not found')
  })

  it('a bound template that no longer exists says not found, not an error and not another template', async () => {
    const wrapper = mountFor({ template_id: 'tpl-deleted' })
    await flushPromises()

    expect(api.templates.list).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Template not found')
    expect(wrapper.text()).not.toContain('Failed to load')
  })
})
