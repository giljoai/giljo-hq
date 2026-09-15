import { describe, it, expect, beforeEach, vi } from 'vitest'

const h = vi.hoisted(() => ({
  row: null,
  fetchProductById: null,
  deleteProduct: null,
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    products: [],
    fetchProductById: h.fetchProductById,
    deleteProduct: h.deleteProduct,
  }),
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: null, updateSetupState: vi.fn(async () => ({})) }),
}))

import { useTutorialState } from './useTutorialState'

const UNTOUCHED_SHOWN_DRAFT = {
  id: 'draft-1',
  name: '',
  description: '',
  is_active: true,
  tech_stack: {},
  architecture: {},
  test_config: { coverage_target: 80 },
}

describe('releaseAbandonedDraft — the abandoned-draft hatch (FE-9566)', () => {
  beforeEach(() => {
    h.row = { ...UNTOUCHED_SHOWN_DRAFT }
    h.fetchProductById = vi.fn(async () => h.row)
    h.deleteProduct = vi.fn(async () => true)
  })

  it('releases an untouched draft even though create_product marks it SHOWN', async () => {
    const { setProduct, releaseAbandonedDraft } = useTutorialState()
    setProduct('draft-1')

    const released = await releaseAbandonedDraft()

    expect(h.deleteProduct).toHaveBeenCalledWith('draft-1')
    expect(released).toBe(true)
  })

  it('keeps a draft the agent has already written to', async () => {
    h.row = { ...UNTOUCHED_SHOWN_DRAFT, description: 'the agent got here first' }
    const { setProduct, releaseAbandonedDraft } = useTutorialState()
    setProduct('draft-1')

    expect(await releaseAbandonedDraft()).toBe(false)
    expect(h.deleteProduct).not.toHaveBeenCalled()
  })

  it('keeps a NAMED product — a named row is the user\'s, never a tour draft', async () => {
    h.row = { ...UNTOUCHED_SHOWN_DRAFT, name: 'My Real Product' }
    const { setProduct, releaseAbandonedDraft } = useTutorialState()
    setProduct('draft-1')

    expect(await releaseAbandonedDraft()).toBe(false)
    expect(h.deleteProduct).not.toHaveBeenCalled()
  })

  it('keeps anything it cannot verify — a failed fetch is not permission to delete', async () => {
    h.fetchProductById = vi.fn(async () => {
      throw new Error('offline')
    })
    const { setProduct, releaseAbandonedDraft } = useTutorialState()
    setProduct('draft-1')

    expect(await releaseAbandonedDraft()).toBe(false)
    expect(h.deleteProduct).not.toHaveBeenCalled()
  })

  it('does nothing when the run owns no product', async () => {
    const { releaseAbandonedDraft } = useTutorialState()

    expect(await releaseAbandonedDraft()).toBe(false)
    expect(h.fetchProductById).not.toHaveBeenCalled()
  })
})
