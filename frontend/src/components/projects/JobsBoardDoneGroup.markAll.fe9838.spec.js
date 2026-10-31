import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const markReviewedBulk = vi.hoisted(() => vi.fn())
const showToast = vi.hoisted(() => vi.fn())

vi.mock('@/services/api', () => {
  const api = { projects: { markReviewedBulk } }
  return { default: api, api }
})
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }))

import JobsBoardDoneGroup from './JobsBoardDoneGroup.vue'

const passthrough = { template: '<div><slot /></div>' }
const btnStub = { template: '<button><slot /></button>' }

function mountGroup(ids = ['a', 'b', 'c']) {
  return mount(JobsBoardDoneGroup, {
    props: { count: ids.length, projectIds: ids, productName: 'MCP_tests' },
    global: {
      stubs: {
        'v-dialog': passthrough,
        'v-card': passthrough,
        'v-card-text': passthrough,
        'v-divider': true,
        'v-spacer': true,
        'v-icon': true,
        'v-btn': btnStub,
        'v-tooltip': { template: '<div><slot name="activator" :props="{}" /></div>' },
      },
    },
  })
}

describe('JobsBoardDoneGroup mark all reviewed (FE-9838)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    markReviewedBulk.mockReset()
    showToast.mockReset()
  })

  it('shows the link on the header row and no confirm until pressed', () => {
    const w = mountGroup()
    const link = w.find('[data-testid="jobs-done-group-mark-all"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toBe('Mark all reviewed')
    expect(w.find('[data-testid="jobs-done-mark-all-confirm"]').exists()).toBe(false)
  })

  it('confirm names the count and the product', async () => {
    const w = mountGroup()
    await w.find('[data-testid="jobs-done-group-mark-all"]').trigger('click')
    const body = w.find('[data-testid="jobs-done-mark-all-body"]').text()
    expect(body).toBe('Mark 3 projects in MCP_tests as reviewed? They leave this list. Nothing is deleted.')
    expect(w.text()).toContain('Mark all reviewed?')
  })

  it('confirming sends ONE bulk request, toasts the count and asks the board to refresh', async () => {
    markReviewedBulk.mockResolvedValue({ data: { marked: 3, skipped: [] } })
    const w = mountGroup()
    await w.find('[data-testid="jobs-done-group-mark-all"]').trigger('click')
    await w.find('[data-testid="jobs-done-mark-all-submit"]').trigger('click')
    await flushPromises()
    expect(markReviewedBulk).toHaveBeenCalledTimes(1)
    expect(markReviewedBulk).toHaveBeenCalledWith(['a', 'b', 'c'])
    expect(showToast).toHaveBeenCalledWith({ message: '3 projects marked reviewed.', type: 'success' })
    expect(w.emitted('changed')).toHaveLength(1)
  })

  it('skipped projects are counted in the toast', async () => {
    markReviewedBulk.mockResolvedValue({ data: { marked: 2, skipped: [{ id: 'b', reason: 'chain' }] } })
    const w = mountGroup()
    await w.find('[data-testid="jobs-done-group-mark-all"]').trigger('click')
    await w.find('[data-testid="jobs-done-mark-all-submit"]').trigger('click')
    await flushPromises()
    expect(showToast).toHaveBeenCalledWith({ message: '2 projects marked reviewed. 1 skipped.', type: 'warning' })
    expect(w.emitted('changed')).toHaveLength(1)
  })

  it('a failed request toasts an error and leaves the list alone', async () => {
    markReviewedBulk.mockRejectedValue(new Error('boom'))
    const w = mountGroup()
    await w.find('[data-testid="jobs-done-group-mark-all"]').trigger('click')
    await w.find('[data-testid="jobs-done-mark-all-submit"]').trigger('click')
    await flushPromises()
    expect(showToast.mock.calls[0][0].type).toBe('error')
    expect(w.emitted('changed')).toBeUndefined()
  })

  it('cancel makes no call', async () => {
    const w = mountGroup()
    await w.find('[data-testid="jobs-done-group-mark-all"]').trigger('click')
    await w.find('[data-testid="jobs-done-mark-all-cancel"]').trigger('click')
    expect(markReviewedBulk).not.toHaveBeenCalled()
  })

  it('singular wording for one project', async () => {
    markReviewedBulk.mockResolvedValue({ data: { marked: 1, skipped: [] } })
    const w = mountGroup(['a'])
    await w.find('[data-testid="jobs-done-group-mark-all"]').trigger('click')
    expect(w.find('[data-testid="jobs-done-mark-all-body"]').text()).toContain('Mark 1 project in MCP_tests')
    await w.find('[data-testid="jobs-done-mark-all-submit"]').trigger('click')
    await flushPromises()
    expect(showToast).toHaveBeenCalledWith({ message: '1 project marked reviewed.', type: 'success' })
  })
})
