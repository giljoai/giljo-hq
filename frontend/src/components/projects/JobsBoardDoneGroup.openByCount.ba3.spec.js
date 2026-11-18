import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import JobsBoardDoneGroup from './JobsBoardDoneGroup.vue'

function mountGroup(count) {
  setActivePinia(createPinia())
  const ids = Array.from({ length: count }, (_, i) => `p${i}`)
  return mount(JobsBoardDoneGroup, {
    props: { count, projectIds: ids },
    slots: { default: '<div data-testid="slotted">cards</div>' },
    global: { stubs: { 'v-dialog': true, 'v-icon': true, 'v-tooltip': { template: '<div><slot name="activator" :props="{}" /></div>' } } },
  })
}
const body = (w) => w.find('[data-testid="jobs-done-group-cards"]').exists()
const toggle = (w) => w.find('[data-testid="jobs-done-group-toggle"]')

describe('JobsBoardDoneGroup open by count', () => {
  it.each([1, 2, 3])('%i project(s): open by itself', (n) => {
    const w = mountGroup(n)
    expect(body(w)).toBe(true)
    expect(toggle(w).attributes('aria-expanded')).toBe('true')
  })

  it('four projects: folded', () => {
    expect(body(mountGroup(4))).toBe(false)
  })

  it('a small group the person folds stays folded, even as the count changes', async () => {
    const w = mountGroup(2)
    await toggle(w).trigger('click')
    expect(body(w)).toBe(false)
    await w.setProps({ count: 3 })
    expect(body(w)).toBe(false)
  })

  it('a big group the person opens stays open when the count shrinks to three', async () => {
    const w = mountGroup(5)
    await toggle(w).trigger('click')
    expect(body(w)).toBe(true)
    await w.setProps({ count: 3 })
    expect(body(w)).toBe(true)
  })

  it('an untouched group follows the count: 4 folded, then 3 open', async () => {
    const w = mountGroup(4)
    expect(body(w)).toBe(false)
    await w.setProps({ count: 3 })
    expect(body(w)).toBe(true)
  })
})
