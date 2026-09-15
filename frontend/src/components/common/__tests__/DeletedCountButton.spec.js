import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { mount } from '@vue/test-utils'

import DeletedCountButton from '@/components/common/DeletedCountButton.vue'
import { withRealVuetify } from '../../../../tests/helpers/realVuetify'

let vuetify
let restore

beforeAll(async () => {
  ;({ plugin: vuetify, restore } = await withRealVuetify(['VBadge', 'VBtn', 'VIcon']))
})

afterAll(() => restore())

function mountButton(props = {}) {
  return mount(DeletedCountButton, {
    props: { count: 0, entity: 'threads', ...props },
    global: { plugins: [vuetify] },
  })
}

describe('DeletedCountButton (FE-9368)', () => {
  it('renders the count on the badge when there is something deleted', () => {
    const wrapper = mountButton({ count: 8 })
    const badge = wrapper.find('.v-badge__badge')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('8')
  })

  it('hides the badge at zero', () => {
    const wrapper = mountButton({ count: 0 })
    expect(wrapper.find('.v-badge__badge').isVisible()).toBe(false)
  })

  it('disables the button at zero and enables it when a count arrives', async () => {
    const wrapper = mountButton({ count: 0 })
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()

    await wrapper.setProps({ count: 3 })
    expect(wrapper.find('button').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('.v-badge__badge').text()).toBe('3')
  })

  it('keeps the count readable in words, not only as a dot', () => {
    const btn = mountButton({ count: 2, entity: 'projects' }).find('button')
    expect(btn.attributes('title')).toBe('Deleted projects (2)')
    expect(btn.attributes('aria-label')).toBe('View deleted projects')
  })

  it('says so plainly when there is nothing to recover', () => {
    expect(mountButton({ count: 0 }).find('button').attributes('title')).toBe('No deleted threads')
  })

  it('emits click so the owning view opens its own recovery dialog', async () => {
    const wrapper = mountButton({ count: 1 })
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('click')).toHaveLength(1)
  })
})
