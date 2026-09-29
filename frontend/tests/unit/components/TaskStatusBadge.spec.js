import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { createPinia, setActivePinia } from 'pinia'

import TaskStatusBadge from '@/components/TaskStatusBadge.vue'
import { useTaskStatusesStore } from '@/stores/taskStatusesStore'

// Canonical task statuses (FE-5041 Phase 1: backend `TaskStatus` enum; FE-9675
// added on_hold), plus the retired `converted` value.
// `expectedHex` mirrors the CSS custom properties in
// `frontend/src/styles/main.scss` which mirror SCSS tokens in
// `design-tokens.scss`. Hex values appear here only for assertion purposes —
// production code never embeds them outside the seed CSS injected below.
const STATUSES = [
  {
    value: 'pending',
    label: 'Pending',
    color_token: 'color-text-muted',
    expectedHex: '#9e9e9e',
    is_lifecycle_finished: false,
  },
  {
    value: 'in_progress',
    label: 'In Progress',
    color_token: 'color-agent-implementer',
    expectedHex: '#6db3e4',
    is_lifecycle_finished: false,
  },
  {
    value: 'on_hold',
    label: 'On hold',
    color_token: 'color-agent-reviewer',
    expectedHex: '#ac80cc',
    is_lifecycle_finished: false,
  },
  {
    value: 'completed',
    label: 'Completed',
    color_token: 'color-agent-researcher',
    expectedHex: '#5ec48e',
    is_lifecycle_finished: true,
  },
  {
    value: 'blocked',
    label: 'Blocked',
    color_token: 'color-agent-analyzer',
    expectedHex: '#e07872',
    is_lifecycle_finished: false,
  },
  {
    value: 'cancelled',
    label: 'Cancelled',
    color_token: 'color-text-muted',
    expectedHex: '#9e9e9e',
    is_lifecycle_finished: true,
  },
  {
    value: 'converted',
    label: 'Converted',
    color_token: 'color-agent-reviewer',
    expectedHex: '#ac80cc',
    is_lifecycle_finished: true,
  },
]

// Inject the CSS custom properties from main.scss into the jsdom document
// so `getComputedStyle(...).getPropertyValue('--color-...')` resolves.
// jsdom does not parse our SCSS, so we set them directly on :root.
function installStatusColorVars() {
  const styleEl = document.createElement('style')
  styleEl.dataset.testColors = 'task-statuses'
  styleEl.textContent = `:root {
    --color-text-muted: #9e9e9e;
    --color-agent-implementer: #6db3e4;
    --color-agent-researcher: #5ec48e;
    --color-agent-analyzer: #e07872;
    --color-agent-reviewer: #ac80cc;
  }`
  document.head.appendChild(styleEl)
  return styleEl
}

describe('TaskStatusBadge.vue', () => {
  let vuetify
  let pinia
  let cssEl

  beforeEach(() => {
    vuetify = createVuetify()
    pinia = createPinia()
    setActivePinia(pinia)
    // Seed the store synchronously so the badge has metadata at mount time
    // (no API call). Mirrors production boot — the store is loaded by
    // DefaultLayout.onMounted before any badge mounts.
    const store = useTaskStatusesStore()
    store.statuses = STATUSES.map(
      ({ expectedHex: _ignored, ...rest }) => rest, // store payload omits expectedHex
    )
    store.loaded = true
    cssEl = installStatusColorVars()
  })

  afterEach(() => {
    if (cssEl && cssEl.parentNode) {
      cssEl.parentNode.removeChild(cssEl)
    }
  })

  const createWrapper = (props) =>
    mount(TaskStatusBadge, {
      props: { status: 'pending', ...props },
      global: { plugins: [vuetify, pinia] },
    })

  describe('Rendering — parametrized across all 6 canonical statuses', () => {
    STATUSES.forEach(({ value, label }) => {
      it(`renders label "${label}" for status "${value}"`, () => {
        const wrapper = createWrapper({ status: value })
        expect(wrapper.text()).toContain(label)
        expect(wrapper.vm.statusLabel).toBe(label)
      })

      it(`uses border-radius 8px (square-cornered) for status "${value}"`, () => {
        const wrapper = createWrapper({ status: value })
        const style = wrapper.find('.task-status-badge').attributes('style')
        expect(style).toContain('border-radius: 8px')
      })

      it(`applies tinted background (rgba 0.15) for status "${value}"`, () => {
        const wrapper = createWrapper({ status: value })
        const style = wrapper.find('.task-status-badge').attributes('style')
        expect(style).toContain('rgba(')
        expect(style).toContain('0.15')
      })
    })
  })

  describe('Color resolution from store metadata + CSS custom properties', () => {
    STATUSES.forEach(({ value, expectedHex }) => {
      it(`resolves color_token to "${expectedHex}" for status "${value}"`, () => {
        const wrapper = createWrapper({ status: value })
        expect(wrapper.vm.colorHex.toLowerCase()).toBe(expectedHex.toLowerCase())
      })
    })
  })

  describe('Smooth border discipline', () => {
    it('applies the smooth-border class (no raw CSS border on rounded element)', () => {
      const wrapper = createWrapper({ status: 'pending' })
      expect(wrapper.find('.task-status-badge').classes()).toContain('smooth-border')
    })
  })

  describe('Accessibility — aria-label per status', () => {
    STATUSES.forEach(({ value, label }) => {
      it(`sets aria-label "Task status: ${label}" for status "${value}"`, () => {
        const wrapper = createWrapper({ status: value })
        expect(
          wrapper.find('.task-status-badge').attributes('aria-label'),
        ).toBe(`Task status: ${label}`)
      })
    })
  })

  describe('Fallback when status is unknown (orphan / pre-load)', () => {
    it('uses muted color and capitalized fallback label for unknown status', () => {
      const wrapper = createWrapper({ status: 'whatever_orphan_value' })
      expect(wrapper.vm.statusLabel).toBe('Whatever_orphan_value')
      expect(wrapper.vm.colorHex.toLowerCase()).toBe('#9e9e9e')
    })

    it('falls back gracefully when the store has no metadata yet', () => {
      const store = useTaskStatusesStore()
      store.reset()
      const wrapper = createWrapper({ status: 'in_progress' })
      expect(wrapper.vm.meta).toBeUndefined()
      expect(wrapper.vm.colorHex.toLowerCase()).toBe('#9e9e9e')
      expect(wrapper.vm.statusLabel).toBe('In_progress')
    })
  })
})
