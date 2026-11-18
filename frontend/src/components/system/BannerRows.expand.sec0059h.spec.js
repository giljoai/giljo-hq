import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { installBannerGeometry } from '../../../tests/helpers/bannerGeometry'

import YourTurnBannerRow from './YourTurnBannerRow.vue'
import ApprovalBannerRow from './ApprovalBannerRow.vue'
import ThreadPostBannerRow from './ThreadPostBannerRow.vue'
import LifecycleBannerRow from './LifecycleBannerRow.vue'
import TemplateProposalsBannerRow from './TemplateProposalsBannerRow.vue'
import OnboardingNudgeRow from './OnboardingNudgeRow.vue'

const geo = installBannerGeometry()
let pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

const TOGGLE = '[data-testid="banner-expand-toggle"]'

const OPEN_ROWS = [
  {
    name: 'YourTurnBannerRow',
    component: YourTurnBannerRow,
    props: { threads: [{ id: 't1', title: 'Release plan', last_message: { author: 'Alice' } }] },
    text: '[data-testid="your-turn-banner-text"]',
    cta: '[data-testid="your-turn-cta"]',
  },
  {
    name: 'ApprovalBannerRow',
    component: ApprovalBannerRow,
    props: { approvals: [{ id: 'a1', banner_state: 'awaiting_user', taxonomy_alias: 'BE-1' }] },
    text: '[data-testid="approval-banner-text"]',
    cta: '[data-testid="approval-cta"]',
  },
  {
    name: 'ThreadPostBannerRow',
    component: ThreadPostBannerRow,
    props: {
      mentions: [{ thread_id: 't1', chat_id: 'C-1', message_ids: ['m1'] }],
      directedAsks: [],
    },
    text: '[data-testid="thread-post-banner-text"]',
    cta: '[data-testid="thread-post-cta"]',
  },
  {
    name: 'LifecycleBannerRow',
    component: LifecycleBannerRow,
    props: {
      row: { id: 'l1', title: 'A long project title', moment: 'activated', taxonomyAlias: 'BE-1' },
    },
    text: '[data-testid="lifecycle-banner-text"]',
    cta: '[data-testid="lifecycle-banner-cta"]',
  },
  {
    name: 'TemplateProposalsBannerRow',
    component: TemplateProposalsBannerRow,
    props: { count: 2 },
    text: '[data-testid="template-proposals-banner-text"]',
    cta: '[data-testid="template-proposals-cta"]',
  },
]

async function mountRow(c) {
  const w = mount(c.component, { props: c.props, global: { plugins: [pinia] } })
  await nextTick()
  await nextTick()
  return w
}

describe.each(OPEN_ROWS)('SEC-0059h strip row: $name', (c) => {
  it('text fits: no control, and a click on the text still opens', async () => {
    geo.fits()
    const w = await mountRow(c)
    expect(w.find(TOGGLE).exists()).toBe(false)
    await w.find(c.text).trigger('click')
    expect(w.emitted('open')).toHaveLength(1)
    expect(w.find(c.text).classes()).not.toContain('is-expanded')
  })

  it('text cut: "More" before the CTA; text click toggles and never opens', async () => {
    geo.cut()
    const w = await mountRow(c)
    const toggle = w.find(TOGGLE)
    expect(toggle.text()).toBe('More')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(
      toggle.element.compareDocumentPosition(w.find(c.cta).element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()

    await w.find(c.text).trigger('click')
    expect(w.find(c.text).classes()).toContain('is-expanded')
    expect(w.find(TOGGLE).text()).toBe('Less')
    await w.find(c.text).trigger('click')
    expect(w.find(c.text).classes()).not.toContain('is-expanded')
    expect(w.emitted('open')).toBeUndefined()
  })

  it('text cut: "More" toggles and never opens', async () => {
    geo.cut()
    const w = await mountRow(c)
    await w.find(TOGGLE).trigger('click')
    expect(w.find(c.text).classes()).toContain('is-expanded')
    expect(w.find(TOGGLE).attributes('aria-expanded')).toBe('true')
    expect(w.find(TOGGLE).attributes('aria-label')).toBeUndefined()
    expect(w.find(TOGGLE).text()).toBe('Less')
    expect(w.find(c.text).attributes('id')).toBeTruthy()
    expect(w.find(TOGGLE).attributes('aria-controls')).toBe(w.find(c.text).attributes('id'))
    expect(w.emitted('open')).toBeUndefined()
  })

  it('text cut: the CTA opens and does not toggle', async () => {
    geo.cut()
    const w = await mountRow(c)
    await w.find(c.cta).trigger('click')
    expect(w.emitted('open')).toHaveLength(1)
    expect(w.find(c.text).classes()).not.toContain('is-expanded')
  })
})

describe('SEC-0059h strip row: OnboardingNudgeRow (no bar action of its own)', () => {
  const props = { rowTestid: 'r', ctaTestid: 'c', ctaLabel: 'Go to Tools', dismissTestid: 'd' }
  const slots = { default: 'Tune your agent templates and product context in Tools.' }
  const text = '.system-banner-alert__text'

  it('fits: no control, a bar click changes nothing', async () => {
    geo.fits()
    const w = mount(OnboardingNudgeRow, { props, slots })
    await nextTick()
    expect(w.find(TOGGLE).exists()).toBe(false)
    await w.find('[data-testid="r"]').trigger('click')
    expect(w.find(text).classes()).not.toContain('is-expanded')
  })

  it('cut: bar click toggles; CTA and dismiss keep their meaning', async () => {
    geo.cut()
    const w = mount(OnboardingNudgeRow, { props, slots })
    await nextTick()
    expect(w.find(TOGGLE).text()).toBe('More')

    await w.find('[data-testid="c"]').trigger('click')
    await w.find('[data-testid="d"]').trigger('click')
    expect(w.emitted('cta')).toHaveLength(1)
    expect(w.emitted('dismiss')).toHaveLength(1)
    expect(w.find(text).classes()).not.toContain('is-expanded')

    await w.find('[data-testid="r"]').trigger('click')
    expect(w.find(text).classes()).toContain('is-expanded')
  })
})
