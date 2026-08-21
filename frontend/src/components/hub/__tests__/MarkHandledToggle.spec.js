/**
 * MarkHandledToggle.spec.js — FE-9439
 *
 * The shared hand toggle: the ONE control rendered in two places (beside the thread
 * search bar, and in the composer). These pin the three things that make it a control
 * rather than a decoration — that its state is visible to a screen reader and not only
 * to the eye, that the pulse is an attention aid rather than a requirement, and that
 * clearing stays one-way.
 *
 * The state assertions are made in the SAME mounted component, flipping the prop, rather
 * than in two separate mounts. Two mounts would pass even if the component read `active`
 * once and cached it, which is the failure a toggle actually has.
 *
 * Edition scope: Both
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import MarkHandledToggle from '@/components/hub/MarkHandledToggle.vue'

const btn = (wrapper) => wrapper.get('button.v-btn')

/**
 * tests/setup.js installs a matchMedia stub that answers `matches: false` to everything,
 * so the ordinary (animated) case needs no arrangement. Only the reduced-motion case
 * overrides it, and it restores afterwards so it cannot leak into a sibling test.
 */
const realMatchMedia = window.matchMedia
function prefersReducedMotion(reduce) {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: reduce && query === '(prefers-reduced-motion: reduce)',
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
}

describe('MarkHandledToggle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    window.matchMedia = realMatchMedia
  })

  // DoD 1 — ON when the baton points at the operator, OFF once handled.
  it('renders filled/warning when ON and outlined when OFF, in one mounted component', async () => {
    const wrapper = mount(MarkHandledToggle, { props: { active: true } })

    expect(btn(wrapper).attributes('color')).toBe('warning')
    expect(btn(wrapper).attributes('variant')).toBe('flat')
    expect(btn(wrapper).attributes('icon')).toBe('mdi-hand-back-right')

    await wrapper.setProps({ active: false })

    expect(btn(wrapper).attributes('color')).toBeUndefined()
    expect(btn(wrapper).attributes('variant')).toBe('outlined')
    expect(btn(wrapper).attributes('icon')).toBe('mdi-hand-back-right-outline')
  })

  // DoD 4 — state is exposed to assistive tech, never by colour alone.
  it('exposes state via aria-pressed and always carries an aria-label', async () => {
    const wrapper = mount(MarkHandledToggle, { props: { active: true } })

    expect(btn(wrapper).attributes('aria-pressed')).toBe('true')
    expect(btn(wrapper).attributes('aria-label')).toBeTruthy()
    // The label says what the control DOES, not just what it is.
    expect(btn(wrapper).attributes('aria-label')).toContain('Mark handled')
    expect(btn(wrapper).attributes('title')).toBe(btn(wrapper).attributes('aria-label'))

    await wrapper.setProps({ active: false })

    expect(btn(wrapper).attributes('aria-pressed')).toBe('false')
    // OFF is not unlabelled — it explains why there is nothing to do.
    expect(btn(wrapper).attributes('aria-label')).toBe('Nothing is waiting on you in this thread')
  })

  it('emits click when pressed', async () => {
    const wrapper = mount(MarkHandledToggle, { props: { active: true } })

    await btn(wrapper).trigger('click')

    expect(wrapper.emitted('click')).toHaveLength(1)
  })

  // Clearing is one-way by design — there is no "un-handle", so OFF is inert.
  it('is inert when nothing is waiting', () => {
    const wrapper = mount(MarkHandledToggle, { props: { active: false } })

    expect(btn(wrapper).attributes('disabled')).toBeDefined()
  })

  it('is inert while a clear is in flight', () => {
    const wrapper = mount(MarkHandledToggle, { props: { active: true, disabled: true } })

    expect(btn(wrapper).attributes('disabled')).toBeDefined()
  })

  // DoD 5 — the pulse.
  it('pulses while it is the operator turn', () => {
    prefersReducedMotion(false)
    const wrapper = mount(MarkHandledToggle, { props: { active: true, pulse: true } })

    expect(btn(wrapper).classes()).toContain('mark-handled-toggle--pulse')
  })

  it('does not pulse when nothing is waiting, even if asked to', () => {
    prefersReducedMotion(false)
    const wrapper = mount(MarkHandledToggle, { props: { active: false, pulse: true } })

    expect(btn(wrapper).classes()).not.toContain('mark-handled-toggle--pulse')
  })

  /**
   * The pulse is an attention aid and never a requirement for operating the control:
   * with motion suppressed the button is still there, still ON, still labelled, still
   * clickable. Asserting only the absent class would leave that unproven.
   */
  it('suppresses the pulse under prefers-reduced-motion, without disabling the control', async () => {
    prefersReducedMotion(true)
    const wrapper = mount(MarkHandledToggle, { props: { active: true, pulse: true } })

    expect(btn(wrapper).classes()).not.toContain('mark-handled-toggle--pulse')

    expect(btn(wrapper).attributes('color')).toBe('warning')
    expect(btn(wrapper).attributes('aria-pressed')).toBe('true')
    expect(btn(wrapper).attributes('disabled')).toBeUndefined()
    await btn(wrapper).trigger('click')
    expect(wrapper.emitted('click')).toHaveLength(1)
  })

  it('renders smaller in the search-bar row than in the composer', () => {
    const small = mount(MarkHandledToggle, { props: { active: true, size: 'sm' } })
    const standard = mount(MarkHandledToggle, { props: { active: true } })

    expect(btn(small).attributes('size')).toBe('x-small')
    expect(btn(standard).attributes('size')).toBe('small')
    expect(btn(small).classes()).toContain('mark-handled-toggle--sm')
  })
})
