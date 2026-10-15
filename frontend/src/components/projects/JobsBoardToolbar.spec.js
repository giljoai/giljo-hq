import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import JobsBoardToolbar from './JobsBoardToolbar.vue'
import { BOARD_DENSITIES } from '@/composables/useBoardDensity'
import { withRealVuetify } from '../../../tests/helpers/realVuetify'

let real

beforeEach(async () => {
  real = await withRealVuetify(['VSwitch', 'VSelectionControl', 'VLabel'])
})

afterEach(() => real.restore())

async function mountToolbar(isCompact) {
  const wrapper = mount(JobsBoardToolbar, {
    props: {
      side: 'implementation',
      sideCounts: { staging: 0, implementation: 2 },
      statusCounts: [],
      isCompact,
    },
    global: { plugins: [real.plugin] },
  })
  await flushPromises()
  return wrapper
}

describe('JobsBoardToolbar Compact view switch (FE-9745)', () => {
  it('shows one label and one switch, no Detailed | Compact segment', async () => {
    const w = await mountToolbar(true)
    expect(w.find('[data-testid="jobs-view-label"]').text()).toBe('Compact view')
    const toggle = w.find('[data-testid="jobs-compact-switch"] input')
    expect(toggle.attributes('aria-label')).toBe('Compact view')
    expect(toggle.attributes('type')).toBe('checkbox')
    expect(w.find('[data-testid="jobs-view-label"]').attributes('for')).toBe(toggle.attributes('id'))
    expect(w.find('[data-testid="jobs-density-detailed"]').exists()).toBe(false)
    expect(w.find('[data-testid="jobs-density-compact"]').exists()).toBe(false)
    expect(w.findAll('input[type="checkbox"]')).toHaveLength(1)
  })

  it('reflects the density: on when compact, off when detailed', async () => {
    expect((await mountToolbar(true)).find('[data-testid="jobs-compact-switch"] input').element.checked).toBe(true)
    expect((await mountToolbar(false)).find('[data-testid="jobs-compact-switch"] input').element.checked).toBe(false)
  })

  it('turning it off emits the detailed value; turning it on emits the compact value', async () => {
    const w = await mountToolbar(true)
    const toggle = w.find('[data-testid="jobs-compact-switch"] input')
    toggle.element.checked = false
    await toggle.trigger('input')
    expect(w.emitted('select-density')).toEqual([[BOARD_DENSITIES.DETAILED]])
    await w.setProps({ isCompact: false })
    toggle.element.checked = true
    await toggle.trigger('input')
    expect(w.emitted('select-density')[1]).toEqual([BOARD_DENSITIES.COMPACT])
    expect(BOARD_DENSITIES).toEqual({ DETAILED: 'detailed', COMPACT: 'compact' })
  })
})

describe('JobsBoardToolbar count colours (FE-9750)', () => {
  const statusCounts = [
    { value: 'needs-decision', label: 'Needs decision', count: 2 },
    { value: 'needs-attention', label: 'Needs attention', count: 0 },
    { value: 'implementing', label: 'Implementing', count: 1 },
    { value: 'review', label: 'Review', count: 3 },
  ]

  async function mountCounts(props = {}) {
    const wrapper = mount(JobsBoardToolbar, {
      props: {
        side: 'implementation',
        sideCounts: { staging: 0, implementation: 1 },
        statusCounts,
        isCompact: true,
        ...props,
      },
      global: { plugins: [real.plugin] },
    })
    await flushPromises()
    return wrapper
  }

  const pill = (w, testid) => w.find(`[data-testid="${testid}"] .jb-filter-n`)

  it('a status count of 0 stays gray', async () => {
    const n = pill(await mountCounts(), 'jobs-status-needs-attention')
    expect(n.text()).toBe('0')
    expect(n.classes()).not.toContain('jb-filter-n--on')
    expect(n.classes()).not.toContain('jb-filter-n--hot')
  })

  it('a status count above 0 is yellow', async () => {
    const w = await mountCounts()
    for (const id of ['jobs-status-implementing', 'jobs-status-review']) {
      expect(pill(w, id).classes()).toContain('jb-filter-n--on')
      expect(pill(w, id).classes()).not.toContain('jb-filter-n--hot')
    }
  })

  it('Needs decision above 0 is hot, not yellow', async () => {
    const n = pill(await mountCounts(), 'jobs-status-needs-decision')
    expect(n.classes()).toContain('jb-filter-n--hot')
    expect(n.classes()).not.toContain('jb-filter-n--on')
  })

  it('Needs decision at 0 is gray', async () => {
    const w = await mountCounts({
      statusCounts: [{ value: 'needs-decision', label: 'Needs decision', count: 0 }],
    })
    const n = pill(w, 'jobs-status-needs-decision')
    expect(n.classes()).not.toContain('jb-filter-n--hot')
    expect(n.classes()).not.toContain('jb-filter-n--on')
  })

  it('side counts follow the same rule, and the active tab keeps its active class', async () => {
    const w = await mountCounts({ sideCounts: { staging: 0, implementation: 1 } })
    const staging = w.find('[data-testid="jobs-side-staging"]')
    const impl = w.find('[data-testid="jobs-side-implementation"]')
    expect(staging.find('.jb-filter-n').classes()).not.toContain('jb-filter-n--on')
    expect(impl.find('.jb-filter-n').classes()).toContain('jb-filter-n--on')
    expect(impl.classes()).toContain('jb-filter--active')
    const w2 = await mountCounts({ side: 'staging', sideCounts: { staging: 4, implementation: 0 } })
    expect(w2.find('[data-testid="jobs-side-staging"] .jb-filter-n').classes()).toContain('jb-filter-n--on')
    expect(w2.find('[data-testid="jobs-side-implementation"] .jb-filter-n').classes()).not.toContain('jb-filter-n--on')
  })

  it('an active tab with a count of 0 is not yellow-pilled', async () => {
    const w = await mountCounts({ side: 'staging', sideCounts: { staging: 0, implementation: 3 } })
    expect(w.find('[data-testid="jobs-side-staging"] .jb-filter-n').classes()).not.toContain('jb-filter-n--on')
  })
})
