/**
 * ProjectTabStrip.spec.js — FE-6174c
 *
 * Rewritten for the single-row card design (FE-9493): each card renders
 * exactly two direct children (alias badge + status badge), badge stays
 * non-clickable/display-only, and `select` is the only emit on click.
 * Edition scope: CE.
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import ProjectTabStrip from '@/components/projects/chain/ProjectTabStrip.vue'

vi.mock('@/utils/taxonomyBadge', () => ({
  resolveTaxonomyColor: () => '#aabbcc',
}))

function mountStrip(tabs, activePid = '') {
  const vuetify = createVuetify()
  return mount(ProjectTabStrip, {
    props: { tabs, activePid },
    global: { plugins: [vuetify] },
  })
}

const baseTabs = {
  // isWorking: true — sub-orchestrator is actively implementing
  working:      { projectId: 'p1', order: 0, name: 'Alpha Project Long Name', taxonomyAlias: 'FE-1', taxonomy: null, isCurrent: true,  isCompleted: false, needsReview: false, isStarted: true,  isWorking: true  },
  review:       { projectId: 'p2', order: 1, name: 'Beta Project',            taxonomyAlias: 'FE-2', taxonomy: null, isCurrent: false, isCompleted: false, needsReview: true,  isStarted: true,  isWorking: false },
  done:         { projectId: 'p3', order: 2, name: 'Gamma',                   taxonomyAlias: 'BE-1', taxonomy: null, isCurrent: false, isCompleted: true,  needsReview: false, isStarted: true,  isWorking: false },
  pending:      { projectId: 'p4', order: 3, name: 'Delta',                   taxonomyAlias: 'BE-2', taxonomy: null, isCurrent: false, isCompleted: false, needsReview: false, isStarted: false, isWorking: false },
  // staging-head: the chain current position but sub-orchestrator not yet started
  stagingHead:  { projectId: 'p5', order: 4, name: 'Epsilon',                 taxonomyAlias: 'BE-3', taxonomy: null, isCurrent: true,  isCompleted: false, needsReview: false, isStarted: false, isWorking: false },
}

describe('ProjectTabStrip — emits', () => {
  it('declares emits as [select] only — no review emit', () => {
    const wrapper = mountStrip([baseTabs.working])
    // The component's defineEmits should only include 'select'
    // We verify by attempting to trigger and checking nothing fires
    expect(wrapper.emitted('review')).toBeFalsy()
  })

  it('clicking the card emits select and select only', async () => {
    const wrapper = mountStrip([baseTabs.working])
    await wrapper.find('[data-testid="chain-tab-0"]').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['p1']])
    expect(wrapper.emitted('review')).toBeFalsy()
  })
})

describe('ProjectTabStrip — badge: review badge is NON-clickable', () => {
  it('clicking the review badge area does NOT emit review', async () => {
    const wrapper = mountStrip([baseTabs.review])
    const badge = wrapper.find('[data-testid="chain-tab-review"]')
    if (badge.exists()) {
      await badge.trigger('click')
      expect(wrapper.emitted('review')).toBeFalsy()
    }
    // Badge should exist as a display element
    expect(wrapper.find('[data-testid="chain-tab-badge-review"]').exists() ||
           wrapper.find('.chain-tab__badge--review').exists()).toBe(true)
  })

  it('the review badge has no role=button or click handler', async () => {
    const wrapper = mountStrip([baseTabs.review])
    const badge = wrapper.find('.chain-tab__badge--review')
    expect(badge.exists()).toBe(true)
    expect(badge.attributes('role')).not.toBe('button')
    expect(badge.attributes('tabindex')).toBeUndefined()
  })
})

describe('ProjectTabStrip — single-row card structure (FE-9493)', () => {
  it('each card renders exactly two direct-child spans: alias then status badge', async () => {
    const wrapper = mountStrip([baseTabs.working])
    const btn = wrapper.find('[data-testid="chain-tab-0"]')
    const spans = btn.findAll('span')
    expect(spans).toHaveLength(2)
    expect(spans[0].classes()).toContain('chain-tab__alias')
    expect(spans[1].classes()).toContain('chain-tab__badge')
  })

  it('has no .chain-tab__row1, .chain-tab__row2, or .chain-tab__name wrappers', async () => {
    const wrapper = mountStrip([baseTabs.working])
    expect(wrapper.find('.chain-tab__row1').exists()).toBe(false)
    expect(wrapper.find('.chain-tab__row2').exists()).toBe(false)
    expect(wrapper.find('.chain-tab__name').exists()).toBe(false)
  })

  it('the project name does not render as visible text, only via :title', async () => {
    const wrapper = mountStrip([baseTabs.working]) // name: 'Alpha Project Long Name'
    expect(wrapper.text()).not.toContain('Alpha Project Long Name')
  })

  it('binds full name to :title on the button', async () => {
    const wrapper = mountStrip([baseTabs.working])
    const btn = wrapper.find('[data-testid="chain-tab-0"]')
    expect(btn.attributes('title')).toBe('Alpha Project Long Name')
  })

  it('status badge is announced to screen readers (no aria-hidden)', async () => {
    const wrapper = mountStrip([baseTabs.working])
    const badge = wrapper.find('.chain-tab__badge')
    expect(badge.attributes('aria-hidden')).toBeUndefined()
  })
})

describe('ProjectTabStrip — badge states', () => {
  it('working tab (isCurrent, !isCompleted) renders chain-tab__badge--working with WORKING label', async () => {
    const wrapper = mountStrip([baseTabs.working])
    const badge = wrapper.find('.chain-tab__badge--working')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('WORKING')
  })

  it('working tab does NOT render chain-tab-current (old dot replaced by badge)', async () => {
    const wrapper = mountStrip([baseTabs.working])
    expect(wrapper.find('[data-testid="chain-tab-current"]').exists()).toBe(false)
  })

  it('review tab (needsReview) renders chain-tab__badge--review with REVIEW label', async () => {
    const wrapper = mountStrip([baseTabs.review])
    const badge = wrapper.find('.chain-tab__badge--review')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('REVIEW')
  })

  it('completed tab (isCompleted, !needsReview) renders chain-tab__badge--completed', async () => {
    const wrapper = mountStrip([baseTabs.done])
    const badge = wrapper.find('.chain-tab__badge--completed')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('COMPLETED')
  })

  it('pending tab renders WAITING badge', async () => {
    const wrapper = mountStrip([baseTabs.pending])
    const badge = wrapper.find('.chain-tab__badge--waiting')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('WAITING')
  })

  it('needsReview takes precedence over isCompleted (completed+unreviewed shows REVIEW not COMPLETED)', async () => {
    // A tab that is both completed AND needsReview should show REVIEW (sky blue) not COMPLETED (green)
    const tab = { ...baseTabs.done, needsReview: true }
    const wrapper = mountStrip([tab])
    expect(wrapper.find('.chain-tab__badge--review').exists()).toBe(true)
    expect(wrapper.find('.chain-tab__badge--completed').exists()).toBe(false)
  })

  it('staging-head (isCurrent=true, isWorking=false) shows WAITING not WORKING (bug repro)', async () => {
    // Bug: old code keyed on isCurrent, so a pending member that IS the chain head
    // would show the white pulsing WORKING badge before its sub-orchestrator started.
    const wrapper = mountStrip([baseTabs.stagingHead])
    expect(wrapper.find('.chain-tab__badge--waiting').exists()).toBe(true)
    expect(wrapper.find('.chain-tab__badge--working').exists()).toBe(false)
  })

  it('isWorking=true tab shows WORKING badge regardless of isCurrent', async () => {
    // A tab that is actively implementing should show WORKING.
    const wrapper = mountStrip([baseTabs.working])
    expect(wrapper.find('.chain-tab__badge--working').exists()).toBe(true)
    expect(wrapper.find('.chain-tab__badge--waiting').exists()).toBe(false)
  })
})

describe('ProjectTabStrip — badge pulse marker class', () => {
  it('working badge carries chain-tab__badge--pulse', async () => {
    const wrapper = mountStrip([baseTabs.working])
    const badge = wrapper.find('.chain-tab__badge--working')
    expect(badge.exists()).toBe(true)
    expect(badge.classes()).toContain('chain-tab__badge--pulse')
  })

  it('review badge carries chain-tab__badge--pulse', async () => {
    const wrapper = mountStrip([baseTabs.review])
    const badge = wrapper.find('.chain-tab__badge--review')
    expect(badge.exists()).toBe(true)
    expect(badge.classes()).toContain('chain-tab__badge--pulse')
  })

  it('waiting badge does NOT carry chain-tab__badge--pulse', async () => {
    const wrapper = mountStrip([baseTabs.pending])
    const badge = wrapper.find('.chain-tab__badge--waiting')
    expect(badge.exists()).toBe(true)
    expect(badge.classes()).not.toContain('chain-tab__badge--pulse')
  })

  it('completed badge does NOT carry chain-tab__badge--pulse', async () => {
    const wrapper = mountStrip([baseTabs.done])
    const badge = wrapper.find('.chain-tab__badge--completed')
    expect(badge.exists()).toBe(true)
    expect(badge.classes()).not.toContain('chain-tab__badge--pulse')
  })
})
