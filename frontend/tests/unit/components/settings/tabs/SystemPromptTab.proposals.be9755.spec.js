/**
 * SystemPromptTab.proposals.be9755.spec.js — BE-9755 lane B
 *
 * A proposal for the orchestrator prompt ADDITIONS shows for the product it
 * targets, through the same proposal view the worker templates use. Pins:
 *  - a proposal shows for the selected product only, never for another's;
 *  - Review opens the proposal view; a confirmed Apply re-reads the prompt, so
 *    the additions field shows the applied text.
 *
 * Edition Scope: Both
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { reactive } from 'vue'

const productStoreMock = reactive({
  products: [
    { id: 'prod-a', name: 'Atlas' },
    { id: 'prod-other', name: 'Borealis' },
  ],
  effectiveProductId: 'prod-a',
  fetchProducts: vi.fn(),
})
vi.mock('@/stores/products', () => ({ useProductStore: () => productStoreMock }))

vi.mock('@/services/api', () => ({
  default: {
    system: {
      getOrchestratorPrompt: vi.fn(),
      updateOrchestratorPrompt: vi.fn(),
      resetOrchestratorPrompt: vi.fn(),
    },
    templateProposals: { list: vi.fn(), count: vi.fn(), apply: vi.fn(), reject: vi.fn() },
  },
}))

import api from '@/services/api'
import SystemPromptTab from '@/components/settings/tabs/SystemPromptTab.vue'

const P = 'prod-a'

function additionsProposal(overrides = {}) {
  return {
    id: 'p-9',
    target_kind: 'orchestrator_additions',
    template_id: null,
    template_name: null,
    product_id: 'prod-a',
    product_name: 'Atlas',
    rung: 'product',
    current_text: '',
    proposed_text: 'Always run the linter.',
    reason: 'Lint drift',
    proposed_by: 'orchestrator',
    created_at: '2026-10-08T14:00:00Z',
    replaced_note: null,
    ...overrides,
  }
}

async function mountTab() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const w = mount(SystemPromptTab, { global: { plugins: [pinia] } })
  await flushPromises()
  return w
}

const notice = (w) => w.find('[data-test="additions-proposal-notice"]')

beforeEach(() => {
  vi.clearAllMocks()
  productStoreMock.effectiveProductId = P
  api.system.getOrchestratorPrompt.mockResolvedValue({
    data: { mode: null, is_override: false, scope: 'default', default_content: 'built-in', additions: null },
  })
  api.templateProposals.apply.mockResolvedValue({ data: { applied: true, rung: 'tenant' } })
})

describe('SystemPromptTab — additions proposals (BE-9755)', () => {
  it('shows a proposal for the selected product', async () => {
    api.templateProposals.list.mockResolvedValue({
      data: { count: 1, proposals: [additionsProposal()] },
    })
    const w = await mountTab()
    expect(notice(w).exists()).toBe(true)
    expect(notice(w).text()).toContain('orchestrator')
  })

  it('a proposal for another product does not show', async () => {
    api.templateProposals.list.mockResolvedValue({
      data: {
        count: 1,
        proposals: [additionsProposal({ rung: 'product', product_id: 'prod-other' })],
      },
    })
    const w = await mountTab()
    expect(notice(w).exists()).toBe(false)
  })

  it('Review opens the proposal view; a confirmed Apply re-reads the prompt', async () => {
    api.templateProposals.list.mockResolvedValue({
      data: { count: 1, proposals: [additionsProposal()] },
    })
    const w = await mountTab()
    const promptReads = api.system.getOrchestratorPrompt.mock.calls.length

    await w.get('[data-test="additions-proposal-review"]').trigger('click')
    expect(w.find('[data-testid="template-proposal-dialog"]').exists()).toBe(true)

    api.templateProposals.list.mockResolvedValue({ data: { count: 0, proposals: [] } })
    await w.get('[data-testid="proposal-apply"]').trigger('click')
    await w.get('[data-testid="proposal-confirm"]').trigger('click')
    await flushPromises()

    expect(api.templateProposals.apply).toHaveBeenCalledWith('p-9')
    expect(api.system.getOrchestratorPrompt.mock.calls.length).toBeGreaterThan(promptReads)
    expect(api.system.getOrchestratorPrompt).toHaveBeenLastCalledWith(P)
    expect(notice(w).exists()).toBe(false)
  })

  it('capitalises the sentence whatever proposed_by starts with', async () => {
    api.templateProposals.list.mockResolvedValue({
      data: { count: 1, proposals: [additionsProposal({ proposed_by: 'agent' })] },
    })
    const w = await mountTab()
    expect(notice(w).text()).toMatch(
      /^Agent proposed a change to these orchestrator additions: Lint drift/,
    )
  })
})
