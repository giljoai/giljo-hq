import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { createRouter, createMemoryHistory } from 'vue-router'
import TemplateManager from '@/components/TemplateManager.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/tools', name: 'Tools', component: { template: '<div />' } }],
})

vi.mock('@/services/api', () => {
  const apiObj = {
    templates: {
      list: vi.fn(),
      activeCount: vi.fn(() =>
        Promise.resolve({ data: { active_count: 1, limit: 15, available: 14 } }),
      ),
      profileDownloadUrl: (id) => `/api/v1/templates/${id}/profile.md`,
    },
    assignments: { list: vi.fn(() => Promise.resolve({ data: { assignments: [], count: 0 } })) },
    products: { list: vi.fn(() => Promise.resolve({ data: [] })) },
    templateProposals: { list: vi.fn(), count: vi.fn(), apply: vi.fn(), reject: vi.fn() },
    system: { getOrchestratorPrompt: vi.fn(() => Promise.resolve({ data: { scope: 'default' } })) },
  }
  return { api: apiObj, default: apiObj }
})
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

import api from '@/services/api'

const dataTableStub = {
  props: ['items'],
  template: `<div class="v-data-table">
    <div v-for="item in (items || [])" :key="item.id"><slot name="item.name" :item="item" /></div>
  </div>`,
}

const A = 'prod-a'
const ROW = { id: 't-1', name: 'analyzer', role: 'analyzer', product_id: A, is_active: true }

function proposal(overrides = {}) {
  return {
    id: 'p-1',
    target_kind: 'agent_template',
    template_id: 't-1',
    template_name: 'analyzer',
    product_id: A,
    product_name: 'Atlas',
    rung: null,
    current_text: 'old',
    proposed_text: 'new',
    reason: 'drift',
    proposed_by: 'reviewer',
    created_at: '2026-10-08T14:00:00Z',
    replaced_note: null,
    ...overrides,
  }
}

const listed = (proposals) => ({ data: { count: proposals.length, proposals } })

async function mountManager() {
  await router.push('/tools')
  const w = mount(TemplateManager, {
    global: {
      plugins: [
        router,
        createTestingPinia({
          initialState: {
            user: { currentUser: { id: 1, username: 'u', role: 'admin', tenant_key: 'tk' } },
            products: {
              activeProduct: null,
              currentProductId: A,
              products: [{ id: A, name: 'Atlas', is_active: true }],
            },
          },
          stubActions: false,
        }),
      ],
      stubs: { 'v-data-table': dataTableStub, Teleport: true },
    },
  })
  await flushPromises()
  return w
}

beforeEach(() => {
  vi.clearAllMocks()
  api.templates.list.mockResolvedValue({ data: [ROW] })
  api.templateProposals.list.mockResolvedValue(listed([proposal()]))
  api.templateProposals.apply.mockResolvedValue({ data: { applied: true, applied_by: 'u' } })
  api.templateProposals.reject.mockResolvedValue({ data: { rejected: true } })
})

describe('TemplateManager — template proposals (BE-9755)', () => {
  it('reads the proposals on mount and badges the row', async () => {
    const w = await mountManager()
    expect(api.templateProposals.list).toHaveBeenCalled()
    expect(w.find('[data-testid="proposal-badge-t-1"]').exists()).toBe(true)
  })

  it('the badge opens the proposal view', async () => {
    const w = await mountManager()
    expect(w.find('[data-testid="template-proposal-dialog"]').exists()).toBe(false)
    await w.get('[data-testid="proposal-badge-t-1"]').trigger('click')
    expect(w.find('[data-testid="template-proposal-dialog"]').exists()).toBe(true)
    expect(w.get('[data-testid="proposal-reason"]').text()).toBe('drift')
  })

  it('a confirmed Apply POSTs apply, re-reads roster and proposals, and the badge goes', async () => {
    const w = await mountManager()
    const rosterReads = api.templates.list.mock.calls.length
    const proposalReads = api.templateProposals.list.mock.calls.length
    api.templateProposals.list.mockResolvedValue(listed([]))

    await w.get('[data-testid="proposal-badge-t-1"]').trigger('click')
    await w.get('[data-testid="proposal-apply"]').trigger('click')
    await w.get('[data-testid="proposal-confirm"]').trigger('click')
    await flushPromises()

    expect(api.templateProposals.apply).toHaveBeenCalledWith('p-1')
    expect(api.templates.list.mock.calls.length).toBeGreaterThan(rosterReads)
    expect(api.templateProposals.list.mock.calls.length).toBeGreaterThan(proposalReads)
    expect(w.find('[data-testid="proposal-badge-t-1"]').exists()).toBe(false)
    expect(w.find('[data-testid="template-proposal-dialog"]').exists()).toBe(false)
  })

  it('a confirmed Reject POSTs reject and the badge goes', async () => {
    const w = await mountManager()
    api.templateProposals.list.mockResolvedValue(listed([]))
    await w.get('[data-testid="proposal-badge-t-1"]').trigger('click')
    await w.get('[data-testid="proposal-reject"]').trigger('click')
    await w.get('[data-testid="proposal-confirm"]').trigger('click')
    await flushPromises()

    expect(api.templateProposals.reject).toHaveBeenCalledWith('p-1')
    expect(api.templateProposals.apply).not.toHaveBeenCalled()
    expect(w.find('[data-testid="proposal-badge-t-1"]').exists()).toBe(false)
  })

  it('announces proposals the roster cannot badge', async () => {
    api.templateProposals.list.mockResolvedValue(
      listed([
        proposal({
          id: 'p-2',
          template_id: 't-other',
          product_id: 'prod-b',
          product_name: 'Borealis',
        }),
        proposal({
          id: 'p-3',
          target_kind: 'orchestrator_additions',
          template_id: null,
          template_name: null,
          rung: 'tenant',
          product_id: null,
          product_name: null,
        }),
      ]),
    )
    const w = await mountManager()
    const notice = w.get('[data-testid="proposals-elsewhere"]')
    expect(notice.text()).toContain('2 template changes waiting outside this list')
    expect(w.find('[data-testid="proposals-show-all"]').exists()).toBe(true)
    expect(w.find('[data-testid="proposals-open-prompt"]').exists()).toBe(true)
  })

  it('a badgeable proposal raises no "outside this list" notice', async () => {
    const w = await mountManager()
    expect(w.find('[data-testid="proposals-elsewhere"]').exists()).toBe(false)
  })

  it('"Open orchestrator prompt" switches to the orchestrator prompt view', async () => {
    api.templateProposals.list.mockResolvedValue(
      listed([
        proposal({
          id: 'p-3',
          target_kind: 'orchestrator_additions',
          template_id: null,
          template_name: null,
          rung: 'product',
          product_id: A,
          product_name: 'Atlas',
        }),
      ]),
    )
    const w = await mountManager()
    expect(w.find('[data-test="prompt-warning"]').exists()).toBe(false)
    await w.get('[data-testid="proposals-open-prompt"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="prompt-warning"]').exists()).toBe(true)
  })
})
