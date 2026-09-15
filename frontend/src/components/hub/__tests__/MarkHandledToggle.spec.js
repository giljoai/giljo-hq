import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import MarkHandledToggle from '@/components/hub/MarkHandledToggle.vue'

const btn = (wrapper) => wrapper.get('button.v-btn')

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

  it('exposes state via aria-pressed and always carries an aria-label', async () => {
    const wrapper = mount(MarkHandledToggle, { props: { active: true } })

    expect(btn(wrapper).attributes('aria-pressed')).toBe('true')
    expect(btn(wrapper).attributes('aria-label')).toBeTruthy()
    expect(btn(wrapper).attributes('aria-label')).toContain('Mark handled')
    expect(btn(wrapper).attributes('title')).toBe(btn(wrapper).attributes('aria-label'))

    await wrapper.setProps({ active: false })

    expect(btn(wrapper).attributes('aria-pressed')).toBe('false')
    expect(btn(wrapper).attributes('aria-label')).toBe('Nothing is waiting on you in this thread')
  })

  it('emits click when pressed', async () => {
    const wrapper = mount(MarkHandledToggle, { props: { active: true } })

    await btn(wrapper).trigger('click')

    expect(wrapper.emitted('click')).toHaveLength(1)
  })

  it('is inert when nothing is waiting', () => {
    const wrapper = mount(MarkHandledToggle, { props: { active: false } })

    expect(btn(wrapper).attributes('disabled')).toBeDefined()
  })

  it('is inert while a clear is in flight', () => {
    const wrapper = mount(MarkHandledToggle, { props: { active: true, disabled: true } })

    expect(btn(wrapper).attributes('disabled')).toBeDefined()
  })

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
