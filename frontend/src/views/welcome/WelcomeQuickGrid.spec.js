import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WelcomeQuickGrid from './WelcomeQuickGrid.vue'

const globalStubs = {
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
}

describe('WelcomeQuickGrid', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  const sampleCards = [
    {
      id: 'card-1',
      title: 'Dashboard',
      description: 'View stats',
      icon: 'mdi-view-dashboard',
      iconBg: 'rgba(109,179,228,0.12)',
      iconColor: '#6db3e4',
      accent: '#6db3e4',
    },
    {
      id: 'card-2',
      templateId: 'tmpl-a',
      isTemplate: true,
      title: 'Template A',
      description: 'A starter template',
      icon: 'mdi-plus',
      iconBg: 'rgba(109,179,228,0.12)',
      iconColor: '#6db3e4',
      accent: '#6db3e4',
    },
  ]

  function mountGrid(cards = sampleCards) {
    return mount(WelcomeQuickGrid, {
      props: { cards },
      global: { stubs: globalStubs },
    })
  }

  it('renders one card per entry', () => {
    const wrapper = mountGrid()
    expect(wrapper.findAll('.quick-card')).toHaveLength(2)
  })

  it('sets data-template-id on template cards', () => {
    const wrapper = mountGrid()
    const tmplCard = wrapper.find('[data-template-id="tmpl-a"]')
    expect(tmplCard.exists()).toBe(true)
  })

  it('does not set data-template-id on non-template cards', () => {
    const wrapper = mountGrid()
    const firstCard = wrapper.findAll('.quick-card')[0]
    expect(firstCard.attributes('data-template-id')).toBeFalsy()
  })

  it('emits card-click when a card is clicked', async () => {
    const wrapper = mountGrid()
    await wrapper.findAll('.quick-card')[0].trigger('click')
    expect(wrapper.emitted('card-click')).toBeTruthy()
    expect(wrapper.emitted('card-click')[0][0]).toMatchObject({ id: 'card-1' })
  })

  it('adds quick-card--attention class for attention cards', () => {
    const attentionCards = [{ ...sampleCards[0], attention: true }]
    const wrapper = mountGrid(attentionCards)
    expect(wrapper.find('.quick-card--attention').exists()).toBe(true)
  })

  it('adds quick-card--busy class and shows busy label', () => {
    const busyCards = [{ ...sampleCards[0], busy: true }]
    const wrapper = mountGrid(busyCards)
    expect(wrapper.find('.quick-card--busy').exists()).toBe(true)
    expect(wrapper.find('.quick-card-busy-label').exists()).toBe(true)
  })

  it('shows badge text when provided', () => {
    const cardsWithBadge = [{ ...sampleCards[0], badge: '/giljo' }]
    const wrapper = mountGrid(cardsWithBadge)
    expect(wrapper.find('.quick-card-badge').text()).toBe('/giljo')
  })
})
