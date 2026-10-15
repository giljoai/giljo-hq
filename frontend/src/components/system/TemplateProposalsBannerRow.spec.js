import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import TemplateProposalsBannerRow from './TemplateProposalsBannerRow.vue'

const stubs = { 'v-icon': { template: '<i class="v-icon" />' } }
const mountRow = (count) =>
  mount(TemplateProposalsBannerRow, { props: { count }, global: { stubs } })

describe('TemplateProposalsBannerRow', () => {
  it('is absent at 0', () => {
    expect(mountRow(0).find('[data-testid="template-proposals-banner"]').exists()).toBe(false)
  })

  it('says the count, plural', () => {
    const text = mountRow(3).get('[data-testid="template-proposals-banner-text"]').text()
    expect(text).toBe('3 template changes waiting')
  })

  it('says the count, singular', () => {
    const text = mountRow(1).get('[data-testid="template-proposals-banner-text"]').text()
    expect(text).toBe('1 template change waiting')
  })

  it('emits open on the CTA and on the row, and offers no dismiss', async () => {
    const w = mountRow(2)
    await w.get('[data-testid="template-proposals-cta"]').trigger('click')
    expect(w.emitted('open')).toHaveLength(1)
    await w.get('[data-testid="template-proposals-banner"]').trigger('click')
    expect(w.emitted('open')).toHaveLength(2)
    expect(w.find('[aria-label="Dismiss"]').exists()).toBe(false)
  })
})
