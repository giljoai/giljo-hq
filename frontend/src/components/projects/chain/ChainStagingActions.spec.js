import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import ChainStagingActions from './ChainStagingActions.vue'

const vuetify = createVuetify()

function mountActions(props = {}) {
  return mount(ChainStagingActions, {
    props: { stageText: 'Stage Chain', ...props },
    global: { plugins: [vuetify] },
  })
}

describe('ChainStagingActions (FE-9682 V5)', () => {
  it('Stage chain is the outlined secondary and Implement the filled primary with a play glyph', () => {
    const wrapper = mountActions({ implementReady: true })
    const stage = wrapper.find('[data-testid="stage-chain-btn"]')
    const implement = wrapper.find('[data-testid="implement-chain-btn"]')
    expect(stage.classes()).toContain('jb-btn-secondary')
    expect(implement.classes()).toContain('jb-btn-primary')
    expect(implement.find('.v-icon').text()).toBe('mdi-play')
    expect(implement.attributes('disabled')).toBeUndefined()
  })

  it('Implement stays the primary, just disabled, until the chain is ready', () => {
    const wrapper = mountActions({ implementReady: false })
    const implement = wrapper.find('[data-testid="implement-chain-btn"]')
    expect(implement.classes()).toContain('jb-btn-primary')
    expect(implement.attributes('disabled')).toBeDefined()
  })

  it('emits stage and implement', async () => {
    const wrapper = mountActions({ implementReady: true })
    await wrapper.find('[data-testid="stage-chain-btn"]').trigger('click')
    await wrapper.find('[data-testid="implement-chain-btn"]').trigger('click')
    expect(wrapper.emitted('stage')).toHaveLength(1)
    expect(wrapper.emitted('implement')).toHaveLength(1)
  })
})
