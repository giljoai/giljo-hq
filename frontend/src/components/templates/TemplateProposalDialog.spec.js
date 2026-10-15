import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  list: vi.fn(),
  count: vi.fn(),
  apply: vi.fn(),
  reject: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const apiObj = {
    templateProposals: { list: h.list, count: h.count, apply: h.apply, reject: h.reject },
  }
  return { default: apiObj, api: apiObj }
})

import TemplateProposalDialog from './TemplateProposalDialog.vue'

function proposal(overrides = {}) {
  return {
    id: 'p-1',
    target_kind: 'agent_template',
    template_id: 't-1',
    template_name: 'implementer',
    product_id: 'prod-a',
    product_name: 'Atlas',
    rung: null,
    current_text: 'line one\nline two\nline three',
    proposed_text: 'line one\nline TWO\nline three\nline four',
    reason: 'Rule two is stale',
    proposed_by: 'reviewer',
    created_at: '2026-10-08T14:00:00Z',
    replaced_note: null,
    ...overrides,
  }
}

function mountDialog(p = proposal()) {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(TemplateProposalDialog, { props: { proposal: p }, global: { plugins: [pinia] } })
}

beforeEach(() => {
  h.list.mockReset().mockResolvedValue({ data: { count: 0, proposals: [] } })
  h.count.mockReset().mockResolvedValue({ data: { count: 0 } })
  h.apply.mockReset().mockResolvedValue({
    data: {
      applied: true,
      target_kind: 'agent_template',
      template_id: 't-1',
      applied_by: 'patrik',
    },
  })
  h.reject.mockReset().mockResolvedValue({ data: { rejected: true } })
})

describe('TemplateProposalDialog — what it shows', () => {
  it('renders nothing without a proposal', () => {
    const pinia = createPinia()
    const w = mount(TemplateProposalDialog, {
      props: { proposal: null },
      global: { plugins: [pinia] },
    })
    expect(w.find('[data-testid="template-proposal-dialog"]').exists()).toBe(false)
  })

  it('names the target, product, reason, proposer and date', () => {
    const w = mountDialog()
    expect(w.get('[data-testid="proposal-target"]').text()).toBe('implementer')
    expect(w.get('[data-testid="proposal-product"]').text()).toBe('Atlas')
    expect(w.get('[data-testid="proposal-reason"]').text()).toBe('Rule two is stale')
    const by = w.get('[data-testid="proposal-by"]').text()
    expect(by).toContain('reviewer')
    expect(by).toContain('2026')
  })

  it('names an orchestrator additions rung and an all-products target', () => {
    const w = mountDialog(
      proposal({
        target_kind: 'orchestrator_additions',
        template_id: null,
        template_name: null,
        product_id: null,
        product_name: null,
        rung: 'tenant',
      }),
    )
    expect(w.get('[data-testid="proposal-target"]').text()).toBe('Orchestrator prompt additions')
    expect(w.get('[data-testid="proposal-product"]').text()).toBe('All products')
  })

  it('shows "Replaced an earlier proposal" only when there was one', () => {
    expect(mountDialog().find('[data-testid="proposal-replaced"]').exists()).toBe(false)
    const w = mountDialog(
      proposal({ replaced_note: { saved_at: '2026-10-07T09:00:00Z', reason: 'older idea' } }),
    )
    const note = w.get('[data-testid="proposal-replaced"]').text()
    expect(note).toContain('Replaced an earlier proposal')
    expect(note).toContain('older idea')
  })

  it('renders the full diff with removed and added lines marked - and +', () => {
    const w = mountDialog()
    const rows = w.findAll('[data-testid="diff-row"]')
    const shape = rows.map(
      (r) => `${r.get('.diff-marker').text() || ' '}|${r.get('.diff-text').text()}`,
    )
    expect(shape).toEqual([' |line one', '-|line two', '+|line TWO', ' |line three', '+|line four'])
    expect(w.get('[data-testid="diff-summary"]').text()).toBe('+2 -1')
  })
})

describe('TemplateProposalDialog — live-check wording fixes (BE-9755)', () => {
  it('shows the server replaced_note sentence as-is, without a second prefix', () => {
    const note = 'Replaced a proposal saved 2026-10-09 05:16 UTC: Proposal one.'
    const w = mountDialog(proposal({ replaced_note: note }))
    expect(w.get('[data-testid="proposal-replaced"]').text()).toBe(note)
  })

  it('words the Apply confirmation in customer voice for a template', async () => {
    const w = mountDialog(proposal({ template_name: 'implementer-7' }))
    await w.get('[data-testid="proposal-apply"]').trigger('click')
    expect(w.get('[data-testid="proposal-confirm-text"]').text()).toBe(
      "Apply this change? The implementer-7 template's instructions will be replaced by the proposed text.",
    )
  })

  it('words the Apply confirmation for the orchestrator additions', async () => {
    const w = mountDialog(
      proposal({
        target_kind: 'orchestrator_additions',
        template_id: null,
        template_name: null,
        rung: 'tenant',
      }),
    )
    await w.get('[data-testid="proposal-apply"]').trigger('click')
    expect(w.get('[data-testid="proposal-confirm-text"]').text()).toBe(
      'Apply this change? Your orchestrator prompt additions will be replaced by the proposed text.',
    )
  })
})

describe('TemplateProposalDialog — Apply and Reject', () => {
  it('Apply asks first; the confirmed click POSTs apply, re-reads, and emits decided', async () => {
    const w = mountDialog()
    await w.get('[data-testid="proposal-apply"]').trigger('click')
    expect(h.apply).not.toHaveBeenCalled()
    expect(w.get('[data-testid="proposal-confirm-text"]').text()).toMatch(/Apply/)

    await w.get('[data-testid="proposal-confirm"]').trigger('click')
    await flushPromises()
    expect(h.apply).toHaveBeenCalledWith('p-1')
    expect(h.reject).not.toHaveBeenCalled()
    expect(h.list).toHaveBeenCalled()
    expect(w.emitted('decided')[0][0]).toMatchObject({ action: 'apply' })
  })

  it('Reject asks first; the confirmed click POSTs reject, re-reads, and emits decided', async () => {
    const w = mountDialog()
    await w.get('[data-testid="proposal-reject"]').trigger('click')
    expect(h.reject).not.toHaveBeenCalled()
    await w.get('[data-testid="proposal-confirm"]').trigger('click')
    await flushPromises()
    expect(h.reject).toHaveBeenCalledWith('p-1')
    expect(h.apply).not.toHaveBeenCalled()
    expect(h.list).toHaveBeenCalled()
    expect(w.emitted('decided')[0][0]).toMatchObject({ action: 'reject' })
  })

  it('Back from the confirmation calls nothing', async () => {
    const w = mountDialog()
    await w.get('[data-testid="proposal-apply"]').trigger('click')
    await w.get('[data-testid="proposal-confirm-cancel"]').trigger('click')
    expect(w.find('[data-testid="proposal-confirm"]').exists()).toBe(false)
    expect(h.apply).not.toHaveBeenCalled()
  })

  it('a failed Apply stays open and says why, emitting nothing', async () => {
    h.apply.mockRejectedValue({
      response: { status: 404, data: { error_code: 'HTTP_ERROR', message: 'Proposal not found' } },
    })
    const w = mountDialog()
    await w.get('[data-testid="proposal-apply"]').trigger('click')
    await w.get('[data-testid="proposal-confirm"]').trigger('click')
    await flushPromises()
    expect(w.get('[data-testid="proposal-error"]').text()).toContain('Proposal not found')
    expect(w.emitted('decided')).toBeUndefined()
  })
})

describe('templateProposalsStore — the count the banner reads moves on a decision', () => {
  it('drops the decided proposal and its count even when the re-read fails', async () => {
    const { useTemplateProposalsStore } = await import('@/stores/templateProposalsStore')
    h.list.mockResolvedValueOnce({
      data: { count: 2, proposals: [proposal(), proposal({ id: 'p-2', template_id: 't-2' })] },
    })
    const w = mountDialog()
    const store = useTemplateProposalsStore()
    await store.fetchAll()
    expect(store.count).toBe(2)

    h.list.mockRejectedValue(new Error('offline'))
    await w.get('[data-testid="proposal-apply"]').trigger('click')
    await w.get('[data-testid="proposal-confirm"]').trigger('click')
    await flushPromises()

    expect(store.count).toBe(1)
    expect(Object.keys(store.byTemplateId)).toEqual(['t-2'])
  })
})


describe('TemplateProposalDialog — built-in diff mode (BE-9785)', () => {
  const builtinDiff = (overrides = {}) => ({
    template_name: 'tester-2',
    current_text: 'line one\nline two',
    builtin_text: 'line one\nline TWO\nline three',
    builtin_version: '1.2.0',
    ...overrides,
  })

  function mountBuiltin(props = {}) {
    const pinia = createPinia()
    setActivePinia(pinia)
    return mount(TemplateProposalDialog, {
      props: { proposal: null, builtinDiff: builtinDiff(), ...props },
      global: { plugins: [pinia] },
    })
  }

  it('opens on builtinDiff alone and names the agent and the built-in version', () => {
    const w = mountBuiltin()
    const card = w.get('[data-testid="template-proposal-dialog"]')
    expect(card.attributes('data-mode')).toBe('builtin')
    expect(card.text()).toContain('Built-in updated')
    expect(w.get('[data-testid="builtin-target"]').text()).toBe('tester-2')
    expect(w.get('[data-testid="builtin-version"]').text()).toBe('1.2.0')
    expect(w.find('[data-testid="proposal-target"]').exists()).toBe(false)
  })

  it('diffs the row text against the current built-in, row on the left', () => {
    const w = mountBuiltin()
    const shape = w
      .findAll('[data-testid="diff-row"]')
      .map((r) => `${r.get('.diff-marker').text() || ' '}|${r.get('.diff-text').text()}`)
    expect(shape).toEqual([' |line one', '-|line two', '+|line TWO', '+|line three'])
  })

  it('offers exactly one action, "Use the new built-in", and emits it without writing', async () => {
    const w = mountBuiltin()
    expect(w.find('[data-testid="proposal-apply"]').exists()).toBe(false)
    expect(w.find('[data-testid="proposal-reject"]').exists()).toBe(false)
    await w.get('[data-testid="use-builtin"]').trigger('click')
    expect(w.emitted('use-builtin')).toHaveLength(1)
    expect(h.apply).not.toHaveBeenCalled()
    expect(h.reject).not.toHaveBeenCalled()
  })

  it('a waiting proposal wins over a built-in diff when both are passed', () => {
    const w = mountBuiltin({ proposal: proposal() })
    expect(w.get('[data-testid="template-proposal-dialog"]').attributes('data-mode')).toBe('proposal')
    expect(w.find('[data-testid="use-builtin"]').exists()).toBe(false)
    expect(w.find('[data-testid="proposal-apply"]').exists()).toBe(true)
  })
})
