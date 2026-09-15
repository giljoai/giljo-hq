import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import NavLogMenu from './NavLogMenu.vue'

const globalStubs = {
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-menu': { template: '<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
  'v-list': { template: '<ul class="v-list"><slot /></ul>' },
  'v-list-item': { props: ['title', 'disabled', 'prependIcon'], template: '<li class="v-list-item" v-bind="$attrs" :title="title">{{ title }}<slot /></li>' },
  'v-list-item-title': { template: '<div class="v-list-item-title"><slot /></div>' },
  'v-list-item-subtitle': { template: '<div class="v-list-item-subtitle"><slot /></div>' },
  'v-list-subheader': { template: '<div class="v-list-subheader"><slot /></div>' },
  'v-divider': { template: '<hr class="v-divider" />' },
  'v-card': { template: '<div class="v-card"><slot /></div>' },
  'v-progress-linear': { template: '<div class="v-progress-linear" />' },
}

describe('NavLogMenu', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  function mountMenu(props = {}) {
    return mount(NavLogMenu, {
      props: {
        logArchives: [],
        logArchivesLoading: false,
        ...props,
      },
      global: { stubs: globalStubs },
    })
  }

  it('renders the logs orb trigger', () => {
    const wrapper = mountMenu()
    expect(wrapper.find('.nav-orb--logs').exists()).toBe(true)
  })

  it('shows "No archives available" when archives list is empty and not loading', () => {
    const wrapper = mountMenu({ logArchives: [], logArchivesLoading: false })
    expect(wrapper.text()).toContain('No archives available')
  })

  it('shows archive entries when archives list has items', () => {
    const wrapper = mountMenu({
      logArchives: [{ filename: 'log-2024-01-01.gz', date: '2024-01-01', size_kb: 42 }],
      logArchivesLoading: false,
    })
    expect(wrapper.find('.v-list-item-title').exists()).toBe(true)
  })

  it('shows the rotation index for size-rotated archives', () => {
    const wrapper = mountMenu({
      logArchives: [
        { filename: 'giljo_mcp.log.1', date: '2026-08-02', rotation_index: 1, size_kb: 10240 },
        { filename: 'giljo_mcp.log.2', date: '2026-08-02', rotation_index: 2, size_kb: 10240 },
      ],
      logArchivesLoading: false,
    })
    const titles = wrapper.findAll('.v-list-item-title').map((t) => t.text())
    expect(titles[0]).toContain('#1')
    expect(titles[1]).toContain('#2')
    expect(titles[0]).toContain('Aug 2, 2026')
    expect(titles[0]).not.toBe(titles[1])
  })

  it('shows a legacy date-named archive without a rotation index', () => {
    const wrapper = mountMenu({
      logArchives: [
        { filename: 'giljo_mcp.log.2026-04-12', date: '2026-04-12', rotation_index: null, size_kb: 512 },
      ],
      logArchivesLoading: false,
    })
    const title = wrapper.find('.v-list-item-title').text()
    expect(title).toContain('Apr 12, 2026')
    expect(title).not.toContain('#')
  })

  it('emits download-current when Download Current Log is clicked', async () => {
    const wrapper = mountMenu()
    const items = wrapper.findAll('.v-list-item')
    await items[0].trigger('click')
    expect(wrapper.emitted('download-current')).toBeTruthy()
  })

  it('emits menu-toggle with open=true when menu opens', async () => {
    const wrapper = mountMenu()
    expect(wrapper.emitted('menu-toggle')).toBeUndefined()
  })
})
