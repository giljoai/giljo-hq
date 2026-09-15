import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref, nextTick } from 'vue'
import { useDeferredHomeData } from './useDeferredHomeData'

vi.mock('@/services/api', () => {
  const apiObj = {
    templates: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      activeCount: vi.fn(() => Promise.resolve({ data: { max_slots: 16 } })),
    },
    assignments: {
      list: vi.fn(() => Promise.resolve({ data: { assignments: [], count: 0 } })),
    },
  }
  return { api: apiObj, default: apiObj }
})
vi.mock('@/composables/useIntegrationStatus', () => ({
  useIntegrationStatus: () => ({ gitEnabled: ref(false), serenaEnabled: ref(false), refresh: vi.fn() }),
}))

import api from '@/services/api'

const PRODUCT = 'prod-home'

function setup({ productId = PRODUCT, onboarded = true } = {}) {
  const templates = ref([])
  const totalSlots = ref(16)
  useDeferredHomeData({
    onboardingComplete: ref(onboarded),
    showIntegReminder: ref(false),
    templates,
    totalSlots,
    productId: ref(productId),
  })
  return { templates, totalSlots }
}

describe('useDeferredHomeData — the crew read is product-scoped', () => {
  beforeEach(() => vi.clearAllMocks())

  it('names the product on both calls the server requires it for', async () => {
    setup()
    await nextTick()
    await Promise.resolve()

    expect(api.templates.list).toHaveBeenCalledWith(PRODUCT)
    expect(api.templates.activeCount).toHaveBeenCalledWith(PRODUCT)
  })

  it('asks for nothing when there is no product', async () => {
    const { templates } = setup({ productId: null })
    await nextTick()
    await Promise.resolve()

    expect(api.templates.list).not.toHaveBeenCalled()
    expect(api.templates.activeCount).not.toHaveBeenCalled()
    expect(templates.value).toEqual([])
  })

  it('overlays the per-product switch state onto the crew', async () => {
    api.templates.list.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }] })
    api.assignments.list.mockResolvedValue({
      data: { assignments: [{ template_id: 1, is_active: true }], count: 1 },
    })

    const { templates } = setup()
    await nextTick()
    await new Promise((r) => setTimeout(r, 0))

    expect(templates.value.map((t) => t.product_active)).toEqual([true, false])
  })

  it('survives the api layer throwing synchronously, without an unhandled error', async () => {
    api.templates.list.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }] })
    api.assignments.list.mockImplementation(() => {
      throw new TypeError('Cannot read properties of undefined')
    })

    const { templates } = setup()
    await nextTick()
    await new Promise((r) => setTimeout(r, 0))

    expect(templates.value.map((t) => t.id)).toEqual([1, 2])
    expect(templates.value.every((t) => t.product_active === false)).toBe(true)
  })

  it('still reports the slot cap from the server rather than a hardcoded default', async () => {
    api.templates.activeCount.mockResolvedValue({ data: { max_slots: 21 } })

    const { totalSlots } = setup()
    await nextTick()
    await new Promise((r) => setTimeout(r, 0))

    expect(totalSlots.value).toBe(21)
  })
})
