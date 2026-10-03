import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref, nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

const showToast = vi.hoisted(() => vi.fn())
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }))
vi.mock('@/services/api', () => {
  const apiObj = {
    products: { getDeletedProducts: vi.fn() },
    templates: { list: vi.fn(), activeCount: vi.fn() },
    assignments: { list: vi.fn() },
    approvals: { listPending: vi.fn(), decide: vi.fn() },
    visionDocuments: { get: vi.fn(), getDeletedByProduct: vi.fn(), restore: vi.fn() },
  }
  return { api: apiObj, default: apiObj }
})
vi.mock('@/composables/useIntegrationStatus', () => ({
  useIntegrationStatus: () => ({ gitEnabled: ref(false), refresh: vi.fn() }),
}))

import api from '@/services/api'
import { useProductSoftDelete } from './useProductSoftDelete'
import { useTemplateData } from './useTemplateData'
import { useDeferredHomeData } from './useDeferredHomeData'
import DecisionModal from '@/components/orchestration/DecisionModal.vue'
import ProductDetailsDialog from '@/components/products/ProductDetailsDialog.vue'

const serverError = (message, status = 500) =>
  Object.assign(new Error('Request failed'), {
    isAxiosError: true,
    response: { status, data: { error_code: 'DATABASEERROR', message } },
  })

const toastShown = () => showToast.mock.calls.map(([o]) => o)
const errorToastMentioning = (text) =>
  toastShown().some((o) => o.type === 'error' && String(o.message).includes(text))

describe('a failed read is shown to the user', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  it('trash: a failed list read is a toast, not an empty trash', async () => {
    api.products.getDeletedProducts.mockRejectedValue(serverError('trash is unavailable'))
    const { loadDeletedProducts, deletedProducts } = useProductSoftDelete(vi.fn())
    deletedProducts.value = [{ id: 'p1', name: 'Kept' }]

    await loadDeletedProducts()

    expect(errorToastMentioning('trash is unavailable')).toBe(true)
    expect(deletedProducts.value).toEqual([{ id: 'p1', name: 'Kept' }])
  })

  it('roster: a failed template read is a toast, not a stale list', async () => {
    api.templates.list.mockRejectedValue(serverError('roster is unavailable'))
    const { loadTemplates } = useTemplateData(ref(''), ref(null), ref(null), ref('prod-1'), ref(false))

    await loadTemplates()

    expect(errorToastMentioning('roster is unavailable')).toBe(true)
  })

  it('home team: a failed assignments read is a toast, not every agent switched off', async () => {
    api.templates.list.mockResolvedValue({ data: [{ id: 't1', name: 'tester' }] })
    api.templates.activeCount.mockResolvedValue({ data: { max_slots: 16 } })
    api.assignments.list.mockRejectedValue(serverError('assignments are unavailable'))
    const templates = ref([])
    useDeferredHomeData({
      onboardingComplete: ref(true),
      showIntegReminder: ref(false),
      templates,
      totalSlots: ref(16),
      productId: ref('prod-home'),
    })
    await nextTick()
    await flushPromises()

    expect(errorToastMentioning('assignments are unavailable')).toBe(true)
    expect(templates.value.some((t) => t.product_active === false)).toBe(false)
  })

  it('decision dialog: a failed pending read renders the store error in the body', async () => {
    api.approvals.listPending.mockRejectedValue(serverError('approvals are unavailable'))
    const wrapper = mount(DecisionModal, {
      props: { show: false, orchestratorJobId: 'job-1' },
      global: { directives: { draggable: {} } },
    })
    await wrapper.setProps({ show: true })
    await flushPromises()

    const err = wrapper.find('[data-testid="decision-modal-error"]')
    expect(err.exists()).toBe(true)
    expect(err.text()).toContain('approvals are unavailable')
  })

  it('vision context: a document that fails to load is a toast, not a blank section', async () => {
    api.visionDocuments.get.mockRejectedValue(serverError('document is unavailable'))
    const wrapper = mount(ProductDetailsDialog, {
      props: {
        modelValue: true,
        product: { id: 'prod-1', name: 'P' },
        visionDocuments: [{ id: 'doc-1', document_name: 'spec.md' }],
      },
      global: { directives: { draggable: {} } },
    })

    await wrapper.vm.showConsolidatedSummary('full')
    await flushPromises()

    expect(errorToastMentioning('Could not load full vision context')).toBe(true)
    expect(wrapper.vm.consolidatedSummaryDialog).toBe(false)
  })
})
