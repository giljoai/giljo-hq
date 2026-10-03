/**
 * Unit tests for useTutorialState (FE-9200) — the onboarding tutorial's state
 * machine and persistence, per CODE_GUIDANCE §7: transitions (next/back/pick/
 * skip), beat-5 label swap, back-from-prompt returns to router, persistence
 * (learning_complete on done; learning_beat/router_choice feature detection),
 * resume clamping (stale beat=6 re-entry lands on the router, not a crash).
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

const mockUpdateSetupState = vi.fn(async (payload) => ({ ...payload }))
let mockCurrentUser = {}

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    get currentUser() {
      return mockCurrentUser
    },
    updateSetupState: mockUpdateSetupState,
  }),
}))

// Product store — only touched by the abandoned-draft exit hatch (fix 4).
const mockFetchProductById = vi.fn()
const mockDeleteProduct = vi.fn(async () => {})

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    fetchProductById: mockFetchProductById,
    deleteProduct: mockDeleteProduct,
  }),
}))

import {
  useTutorialState,
  TUTORIAL_STOPS,
  armActivateBreadcrumb,
  clearActivateBreadcrumb,
  isActivateBreadcrumbArmed,
} from '@/composables/useTutorialState'

/** A completely untouched pre-created draft, as the detail endpoint returns it. */
function emptyDraftRow(overrides = {}) {
  return {
    id: 'draft-1',
    name: '',
    description: null,
    project_path: null,
    core_features: null,
    brand_guidelines: null,
    consolidated_vision_light: null,
    consolidated_vision_medium: null,
    vision_analysis_complete: false,
    has_vision: false,
    vision_documents_count: 0,
    tech_stack: null,
    architecture: null,
    test_config: null,
    is_active: false,
    ...overrides,
  }
}

describe('useTutorialState', () => {
  beforeEach(() => {
    mockCurrentUser = {}
    mockUpdateSetupState.mockClear()
    mockUpdateSetupState.mockImplementation(async (payload) => ({ ...payload }))
    mockFetchProductById.mockReset()
    mockFetchProductById.mockImplementation(async () => emptyDraftRow())
    mockDeleteProduct.mockReset()
    mockDeleteProduct.mockImplementation(async () => {})
  })

  describe('rail metadata', () => {
    it('exposes exactly 6 stops with the approved labels', () => {
      expect(TUTORIAL_STOPS).toHaveLength(6)
      expect(TUTORIAL_STOPS[0]).toBe('How it works')
      expect(TUTORIAL_STOPS[5]).toBe('Get started')
    })
  })

  describe('transitions', () => {
    it('starts at beat 1 on the beats screen', () => {
      const t = useTutorialState()
      expect(t.s.beat).toBe(1)
      expect(t.s.screen).toBe('beats')
      expect(t.railStop.value).toBe(1)
    })

    it('next advances through beats and stops at 6', () => {
      const t = useTutorialState()
      for (let i = 0; i < 10; i++) t.next()
      expect(t.s.beat).toBe(6)
    })

    it('back decrements and stops at 1', () => {
      const t = useTutorialState()
      t.next()
      t.back()
      t.back()
      expect(t.s.beat).toBe(1)
    })

    it('goTo jumps to any stop (rail click-to-jump)', () => {
      const t = useTutorialState()
      t.goTo(4)
      expect(t.s.beat).toBe(4)
      expect(t.s.screen).toBe('beats')
    })

    it('pick D and B go to the prompt screen', () => {
      for (const path of ['D', 'B']) {
        const t = useTutorialState()
        t.pick(path)
        expect(t.s.screen).toBe('prompt')
        expect(t.s.path).toBe(path)
      }
    })

    it('pick A goes to the upload screen', () => {
      const t = useTutorialState()
      t.pick('A')
      expect(t.s.screen).toBe('upload')
    })

    it('pick rejects an unknown door', () => {
      const t = useTutorialState()
      t.pick('X')
      expect(t.s.screen).toBe('beats')
      expect(t.s.path).toBeNull()
    })

    it('back from the prompt screen returns to the router (beat 6)', () => {
      const t = useTutorialState()
      t.pick('D')
      t.back()
      expect(t.s.screen).toBe('beats')
      expect(t.s.beat).toBe(6)
    })

    it('back from the upload screen returns to the router (beat 6)', () => {
      const t = useTutorialState()
      t.pick('A')
      t.back()
      expect(t.s.screen).toBe('beats')
      expect(t.s.beat).toBe(6)
    })

    it('sub-screens map to rail stop 6', () => {
      const t = useTutorialState()
      t.pick('D')
      expect(t.railStop.value).toBe(6)
      t.goToReview()
      expect(t.railStop.value).toBe(6)
    })

    it('goToUpload / goToReview / finishToDone walk the B-D flow', () => {
      const t = useTutorialState()
      t.pick('B')
      t.goToUpload()
      expect(t.s.screen).toBe('upload')
      t.goToReview()
      expect(t.s.screen).toBe('review')
      t.finishToDone()
      expect(t.s.screen).toBe('done')
    })
  })

  describe('footer state', () => {
    it('hides Back on beat 1 and shows it from beat 2', () => {
      const t = useTutorialState()
      expect(t.showBack.value).toBe(false)
      t.next()
      expect(t.showBack.value).toBe(true)
    })

    it('swaps the Next label to "Choose your start" on beat 5', () => {
      const t = useTutorialState()
      t.goTo(5)
      expect(t.nextLabel.value).toBe('Choose your start')
      t.goTo(4)
      expect(t.nextLabel.value).toBe('Next')
    })

    it('hides Next on beat 6 and on sub-screens', () => {
      const t = useTutorialState()
      t.goTo(6)
      expect(t.showNext.value).toBe(false)
      t.pick('D')
      expect(t.showNext.value).toBe(false)
    })
  })

  describe('persistence', () => {
    it('persists learning_beat on next, WITHOUT router_choice before a pick', () => {
      const t = useTutorialState()
      t.next()
      expect(mockUpdateSetupState).toHaveBeenCalledWith({ learning_beat: 2 })
      const payload = mockUpdateSetupState.mock.calls[0][0]
      expect('router_choice' in payload).toBe(false)
    })

    it('includes router_choice once a door is picked', () => {
      const t = useTutorialState()
      t.goTo(6)
      t.pick('D')
      const payload = mockUpdateSetupState.mock.calls.at(-1)[0]
      expect(payload.router_choice).toBe('D')
    })

    it('keeps sending beat fields when the backend echoes them', async () => {
      const t = useTutorialState()
      t.next()
      await vi.waitFor(() => expect(mockUpdateSetupState).toHaveBeenCalledTimes(1))
      t.next()
      expect(mockUpdateSetupState).toHaveBeenCalledTimes(2)
    })

    it('finishToDone sets learning_complete', async () => {
      const t = useTutorialState()
      t.finishToDone()
      await vi.waitFor(() =>
        expect(mockUpdateSetupState).toHaveBeenCalledWith({ learning_complete: true }),
      )
    })

    it('markComplete survives a failing PATCH (skip stays non-fatal)', async () => {
      mockUpdateSetupState.mockRejectedValue(new Error('offline'))
      const t = useTutorialState()
      await expect(t.markComplete()).resolves.toBeUndefined()
    })
  })

  describe('resume (BE-9201 schema, tolerated absent)', () => {
    it('resumes at a persisted beat', () => {
      mockCurrentUser = { learning_beat: 3, router_choice: 'B' }
      const t = useTutorialState()
      expect(t.s.beat).toBe(3)
      expect(t.s.path).toBe('B')
    })

    it('a stale persisted beat=6 re-entry lands on the router (boundary contract)', () => {
      mockCurrentUser = { learning_beat: 6 }
      const t = useTutorialState()
      expect(t.s.beat).toBe(6)
      expect(t.s.screen).toBe('beats')
      expect(t.railStop.value).toBe(6)
    })

    it('clamps out-of-range or garbage beats and ignores invalid router_choice', () => {
      mockCurrentUser = { learning_beat: 99, router_choice: 'Z' }
      let t = useTutorialState()
      expect(t.s.beat).toBe(6)
      expect(t.s.path).toBeNull()

      mockCurrentUser = { learning_beat: 'garbage' }
      t = useTutorialState()
      expect(t.s.beat).toBe(1)
    })

    it('starts fresh when the fields are absent (backend not shipped)', () => {
      mockCurrentUser = {}
      const t = useTutorialState()
      expect(t.s.beat).toBe(1)
      expect(t.s.path).toBeNull()
    })
  })

  describe('run-owned product threading (audit F1/F3)', () => {
    it('starts with no product and records one via setProduct', () => {
      const t = useTutorialState()
      expect(t.s.productId).toBeNull()
      t.setProduct('draft-1')
      expect(t.s.productId).toBe('draft-1')
    })

    it('keeps the product across A→back→A re-entry (no duplicate creates)', () => {
      const t = useTutorialState()
      t.goTo(6)
      t.pick('A')
      t.setProduct('draft-1')
      t.back()
      expect(t.s.screen).toBe('beats')
      t.pick('A')
      expect(t.s.screen).toBe('upload')
      expect(t.s.productId).toBe('draft-1')
    })

    it('keeps the product across an A→back→D door switch', () => {
      const t = useTutorialState()
      t.pick('A')
      t.setProduct('draft-1')
      t.back()
      t.pick('D')
      expect(t.s.productId).toBe('draft-1')
    })

    it('setProduct normalizes falsy ids to null', () => {
      const t = useTutorialState()
      t.setProduct('')
      expect(t.s.productId).toBeNull()
    })
  })

  describe('abandoned-draft exit hatch (walkthrough fix 4)', () => {
    it('deletes an untouched, inactive run-owned draft and clears the state', async () => {
      const t = useTutorialState()
      t.setProduct('draft-1')

      await expect(t.releaseAbandonedDraft()).resolves.toBe(true)

      expect(mockFetchProductById).toHaveBeenCalledWith('draft-1')
      expect(mockDeleteProduct).toHaveBeenCalledWith('draft-1')
      expect(t.s.productId).toBeNull()
    })

    it.each([
      ['a name', { name: 'Alpha' }],
      ['a description', { description: 'An agent wrote this.' }],
      ['a project path', { project_path: '/repo' }],
      ['core features', { core_features: 'search' }],
      ['tech stack content', { tech_stack: { programming_languages: 'Python' } }],
      ['architecture content', { architecture: { primary_pattern: 'monolith' } }],
      ['testing content', { test_config: { test_strategy: 'tdd' } }],
      ['a vision document', { vision_documents_count: 1 }],
      ['a consolidated vision', { consolidated_vision_light: 'vision' }],
      ['completed vision analysis', { vision_analysis_complete: true }],
    ])('keeps the product when the fresh row has %s', async (_label, overrides) => {
      mockFetchProductById.mockImplementation(async () => emptyDraftRow(overrides))
      const t = useTutorialState()
      t.setProduct('draft-1')

      await expect(t.releaseAbandonedDraft()).resolves.toBe(false)

      expect(mockDeleteProduct).not.toHaveBeenCalled()
      expect(t.s.productId).toBe('draft-1')
    })

    /**
     * FE-9566: this case used to read "never deletes an ACTIVE product, even an
     * empty one", asserting that `emptyDraftRow({ is_active: true })` must be
     * kept. It was written when `is_active` meant "THE active product", where an
     * active row really was the user's. FE-9524/D1 redefined `is_active` as
     * "shown as a tab", and ProductService.create_product sets it True for every
     * product — so the row that assertion protected became precisely the
     * nameless door-D draft this hatch exists to clean up, and the tour leaked a
     * product on every abandoned run.
     *
     * It was amended rather than deleted because the behaviour it MEANT to
     * protect is real and still is: never delete something that is the user's.
     * What identifies "the user's" is the NAME, not the shown flag — a
     * user-created product always carries one, and the only way to get a
     * nameless row at all is the tour's own silent create. So the case is
     * re-pointed at a named product, shown and hidden alike.
     *
     * Amended as a
     * stale-invariant fix, NOT a re-baseline: the old fixture shape
     * (is_active:false on a fresh draft) is one create_product no longer
     * produces. See tests/integration/test_fe9566_door_d_draft_create_contract.py.
     */
    it.each([
      ['shown', true],
      ['hidden', false],
    ])('never deletes a NAMED product, %s and empty of everything else', async (_label, isActive) => {
      mockFetchProductById.mockImplementation(async () =>
        emptyDraftRow({ name: 'My Real Product', is_active: isActive }),
      )
      const t = useTutorialState()
      t.setProduct('draft-1')

      await expect(t.releaseAbandonedDraft()).resolves.toBe(false)
      expect(mockDeleteProduct).not.toHaveBeenCalled()
    })

    it('DOES release an untouched nameless draft that is merely SHOWN', async () => {
      // The shape create_product actually produces since FE-9524/D1. Before
      // FE-9566 this row was skipped and leaked; it is the whole point of the
      // hatch that it is now collected.
      mockFetchProductById.mockImplementation(async () => emptyDraftRow({ is_active: true }))
      const t = useTutorialState()
      t.setProduct('draft-1')

      await expect(t.releaseAbandonedDraft()).resolves.toBe(true)
      expect(mockDeleteProduct).toHaveBeenCalledWith('draft-1')
    })

    it('no-ops when the run owns no product', async () => {
      const t = useTutorialState()

      await expect(t.releaseAbandonedDraft()).resolves.toBe(false)

      expect(mockFetchProductById).not.toHaveBeenCalled()
      expect(mockDeleteProduct).not.toHaveBeenCalled()
    })

    it('keeps the draft when emptiness cannot be verified (fetch fails)', async () => {
      mockFetchProductById.mockRejectedValue(new Error('offline'))
      const t = useTutorialState()
      t.setProduct('draft-1')

      await expect(t.releaseAbandonedDraft()).resolves.toBe(false)

      expect(mockDeleteProduct).not.toHaveBeenCalled()
      expect(t.s.productId).toBe('draft-1')
    })

    it('keeps the id when the delete itself fails', async () => {
      mockDeleteProduct.mockRejectedValue(new Error('409'))
      const t = useTutorialState()
      t.setProduct('draft-1')

      await expect(t.releaseAbandonedDraft()).resolves.toBe(false)
      expect(t.s.productId).toBe('draft-1')
    })

    it('back-navigation between tutorial screens never deletes', async () => {
      const t = useTutorialState()
      t.goTo(6)
      t.pick('D')
      t.setProduct('draft-1')
      t.back()
      t.pick('A')
      t.back()

      expect(mockFetchProductById).not.toHaveBeenCalled()
      expect(mockDeleteProduct).not.toHaveBeenCalled()
      expect(t.s.productId).toBe('draft-1')
    })

    it('emptiness ignores numeric defaults and whitespace, but arrays count as content', async () => {
      // coverage_target defaults to 80 on an untouched test_config row, and a
      // whitespace-only name is not content — both still delete.
      mockFetchProductById.mockImplementation(async () =>
        emptyDraftRow({ name: '   ', test_config: { coverage_target: 80 } }),
      )
      let t = useTutorialState()
      t.setProduct('draft-1')
      await expect(t.releaseAbandonedDraft()).resolves.toBe(true)

      // A populated array (e.g. design_patterns) is content — keep.
      mockDeleteProduct.mockClear()
      mockFetchProductById.mockImplementation(async () =>
        emptyDraftRow({ architecture: { design_patterns: ['cqrs'] } }),
      )
      t = useTutorialState()
      t.setProduct('draft-1')
      await expect(t.releaseAbandonedDraft()).resolves.toBe(false)
      expect(mockDeleteProduct).not.toHaveBeenCalled()
    })
  })

  describe('activate breadcrumb helpers (path C)', () => {
    it('arm / check / clear round-trip through localStorage', () => {
      window.localStorage.getItem.mockReturnValue('1')
      armActivateBreadcrumb()
      expect(window.localStorage.setItem).toHaveBeenCalledWith(
        'giljo_tutorial_activate_breadcrumb',
        '1',
      )
      expect(isActivateBreadcrumbArmed()).toBe(true)

      window.localStorage.getItem.mockReturnValue(null)
      clearActivateBreadcrumb()
      expect(window.localStorage.removeItem).toHaveBeenCalledWith(
        'giljo_tutorial_activate_breadcrumb',
      )
      expect(isActivateBreadcrumbArmed()).toBe(false)
    })
  })
})
