/**
 * TutorialReviewScreen.full-proposal.spec.js
 *
 * The review screen is the approval moment: "Activating makes it the brief
 * every agent reads." Two defects made that approval partially blind:
 *
 *  1. The description was hard-sliced at 220 chars in code (the old
 *     descriptionExcerpt computed) — the full text never reached the DOM, so
 *     there was nothing to scroll and no way to read the rest.
 *  2. Only name + a few tech chips were rendered. Architecture, standards,
 *     testing, infra/dev-tools/platforms — most of what the agent proposes —
 *     were activated sight-unseen.
 *
 * This spec pins the fix: the FULL description renders, every category section
 * is present (accordion rows with honest one-line summaries), and an empty
 * field shows a muted "Not provided" instead of disappearing — a thin proposal
 * must look thin at the approval moment.
 *
 * Edition scope: Both (shared frontend/src).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({
  row: null,
  updateProduct: vi.fn(async () => ({})),
  toggleProductActivation: vi.fn(async () => {}),
}))

// FE-9569: a REAL Vue ref, so the component's `computed(() =>
// productStore.getProductById(id))` tracks it the same way it tracks the
// genuine store's own computed-of-function getter (stores/products.js:55).
const cache = ref({})

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    fetchProductById: vi.fn(async () => {
      if (h.row) cache.value = { ...cache.value, [h.row.id]: h.row }
      return h.row
    }),
    fetchProducts: vi.fn(async () => []),
    updateProduct: h.updateProduct,
    getProductById: (id) => (id ? cache.value[id] || null : null),
    activeProduct: null,
  }),
}))

vi.mock('@/composables/useProductActivation', () => ({
  useProductActivation: () => ({
    toggleProductActivation: h.toggleProductActivation,
  }),
}))

import TutorialReviewScreen from './TutorialReviewScreen.vue'

const stubs = {
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': {
    template: '<button v-bind="$attrs" :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>',
    props: ['disabled'],
    emits: ['click'],
  },
}

// 400+ chars: comfortably past the old 220-char slice, so a regression to any
// excerpt length in that range turns this red.
const LONG_DESCRIPTION =
  'TrailKit is a trip-planning workspace for hiking clubs: members propose routes, ' +
  'attach GPX tracks and photos, and the club votes on the next outing. ' +
  'The agent read the uploaded repo and found a Vue 3 single-page app over a FastAPI backend, ' +
  'with PostgreSQL storing routes, RSVPs, and member profiles. ' +
  'It proposes organizing work around three surfaces and flags the payments flow for a later milestone. ' +
  'THE-FINAL-SENTINEL-PAST-220.'

function fullRow() {
  return {
    id: 'p-1',
    name: 'TrailKit',
    description: LONG_DESCRIPTION,
    is_active: false,
    vision_analysis_complete: true,
    brand_guidelines: '',
    target_platforms: ['web', 'linux'],
    tech_stack: {
      programming_languages: 'Python 3.12, TypeScript',
      frontend_frameworks: 'Vue 3, Vuetify 3, Vite',
      backend_frameworks: 'FastAPI',
      databases_storage: 'PostgreSQL 18',
      infrastructure: '',
      dev_tools: 'Ruff, Pytest',
    },
    architecture: {
      primary_pattern: 'Modular monolith',
      api_style: 'REST + WebSocket',
      design_patterns: 'Repository, service layer',
      architecture_notes: '',
      coding_conventions: 'PEP 8 + Ruff strict',
    },
    test_config: {
      test_strategy: 'TDD',
      testing_frameworks: 'pytest, Vitest',
      coverage_target: 80,
      quality_standards: 'No function over 200 lines',
    },
  }
}

async function mountScreen(row) {
  h.row = row
  const wrapper = mount(TutorialReviewScreen, {
    props: { productId: 'p-1' },
    global: { stubs },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  h.row = null
  cache.value = {}
  vi.clearAllMocks()
})

describe('full description (the truncation fix)', () => {
  it('renders the ENTIRE description — text past the old 220-char slice is in the DOM', async () => {
    const wrapper = await mountScreen(fullRow())
    const desc = wrapper.find('[data-testid="tutorial-review-description"]')
    expect(desc.text()).toContain('THE-FINAL-SENTINEL-PAST-220.')
    expect(desc.text()).not.toContain('…')
    expect(desc.text().length).toBeGreaterThan(220)
  })

  it('an empty description says "Not provided" rather than rendering nothing', async () => {
    const row = fullRow()
    row.description = ''
    const wrapper = await mountScreen(row)
    expect(wrapper.find('[data-testid="tutorial-review-description"]').text()).toBe('Not provided')
  })
})

describe('category sections (the sight-unseen fix)', () => {
  it('renders all four category sections', async () => {
    const wrapper = await mountScreen(fullRow())
    for (const key of ['tech', 'architecture', 'standards', 'testing']) {
      expect(wrapper.find(`[data-testid="tutorial-section-${key}"]`).exists()).toBe(true)
    }
  })

  it('tech stack opens by default; the others start collapsed behind summaries', async () => {
    const wrapper = await mountScreen(fullRow())
    expect(wrapper.find('[data-testid="tutorial-section-fields-tech"]').exists()).toBe(true)
    for (const key of ['architecture', 'standards', 'testing']) {
      expect(wrapper.find(`[data-testid="tutorial-section-fields-${key}"]`).exists()).toBe(false)
    }
  })

  it('a collapsed section expands on click and shows its fields', async () => {
    const wrapper = await mountScreen(fullRow())
    await wrapper.find('[data-testid="tutorial-section-toggle-architecture"]').trigger('click')
    const fields = wrapper.find('[data-testid="tutorial-section-fields-architecture"]')
    expect(fields.exists()).toBe(true)
    expect(fields.text()).toContain('Modular monolith')
    expect(fields.text()).toContain('REST + WebSocket')
    expect(fields.text()).toContain('Repository, service layer')
  })

  it('summaries are honest one-liners built from the real data', async () => {
    const wrapper = await mountScreen(fullRow())
    expect(wrapper.find('[data-testid="tutorial-section-toggle-architecture"]').text()).toContain(
      'Modular monolith · REST + WebSocket'
    )
    expect(wrapper.find('[data-testid="tutorial-section-toggle-testing"]').text()).toContain(
      'TDD · pytest, Vitest · 80% coverage target'
    )
    // 6 non-empty groups (languages, frontend, backend, databases, dev tools,
    // platforms) — infrastructure is empty and does not count. 2+3+1+1+2+2 = 11.
    expect(wrapper.find('[data-testid="tutorial-section-toggle-tech"]').text()).toContain('6 groups · 11 entries')
  })

  it('an empty field renders a muted "Not provided" instead of disappearing', async () => {
    const wrapper = await mountScreen(fullRow())
    await wrapper.find('[data-testid="tutorial-section-toggle-architecture"]').trigger('click')
    const fields = wrapper.find('[data-testid="tutorial-section-fields-architecture"]')
    // architecture_notes is empty in the fixture
    expect(fields.text()).toContain('Not provided')
  })

  it('a section with no data at all summarises as "Not provided"', async () => {
    const row = fullRow()
    row.architecture = null
    const wrapper = await mountScreen(row)
    expect(wrapper.find('[data-testid="tutorial-section-toggle-architecture"]').text()).toContain('Not provided')
  })
})

describe('activation is unchanged', () => {
  it('Activate still calls toggleProductActivation and emits activated', async () => {
    const wrapper = await mountScreen(fullRow())
    await wrapper.find('[data-testid="tutorial-activate"]').trigger('click')
    await flushPromises()
    expect(h.toggleProductActivation).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('activated')).toBeTruthy()
  })
})
