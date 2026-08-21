/**
 * Terms.vue regression spec (CE render).
 *
 * Locks in:
 *   - Vendor-neutral CE copy: the billing provider is described by role
 *     (Merchant of Record), never by name. The vendor-naming copy lives in
 *     saas/ components and is asserted by
 *     frontend/tests/unit/saas/views/policyPagesSaas.spec.js, which the CE
 *     export strips (FE-9374b; the export gate greps CE-shipped source,
 *     this spec included, for provider names).
 *   - Dedicated Billing/Refunds section (§7) references the Merchant of
 *     Record, statutory withdrawal rights, and the default non-refundable stance.
 *   - No Team SKU advertising (the tier was cancelled per ADR-009; see
 *     also the FE-9374 guard spec, which bans any capital-T "Team").
 *
 * Edition: ships in CE.
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import Terms from '@/views/Terms.vue'

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: async () => ({}),
    getGiljoMode: () => 'ce',
  },
}))

function mountTerms() {
  return mount(Terms, {
    global: {
      stubs: {
        'v-container': { template: '<div><slot /></div>' },
        'v-card': { template: '<div><slot /></div>' },
        'router-link': { template: '<a><slot /></a>' },
      },
    },
  })
}

describe('Terms.vue', () => {
  it('describes the billing provider by role, vendor-neutral in CE (FE-9374b)', () => {
    const wrapper = mountTerms()
    expect(wrapper.text()).toContain('Merchant of Record')
    expect(wrapper.text().toLowerCase()).toContain('billing provider')
  })

  it('has a dedicated Billing and refunds section', () => {
    const wrapper = mountTerms()
    expect(wrapper.text()).toMatch(/Billing and refunds/i)
    expect(wrapper.text()).toMatch(/invoicing/i)
    expect(wrapper.text()).toMatch(/taxes/i)
    expect(wrapper.text()).toMatch(/provider'?s refund policy/i)
  })

  it('preserves EU/UK statutory withdrawal rights language', () => {
    const wrapper = mountTerms()
    expect(wrapper.text()).toMatch(/EU\/UK customers retain\s+statutory withdrawal rights/i)
    expect(wrapper.text()).toMatch(/generally non-refundable/i)
  })

  it('routes refund exceptional cases through support@', () => {
    const wrapper = mountTerms()
    expect(wrapper.html()).toContain('mailto:support@giljo.ai')
  })

  it('does not advertise a Team SKU as if it exists today', () => {
    const wrapper = mountTerms()
    // Historical copy: "Solo / Team (SaaS)", later "Additional tiers
    // (e.g. Team) may be offered in the future". Current copy: "Solo
    // (SaaS)" with no future-tier promise at all (ADR-009 cancellation).
    expect(wrapper.text()).not.toMatch(/Solo \/ Team/i)
    expect(wrapper.text()).toMatch(/Solo \(SaaS\)/i)
  })

  it('states the auto-cancel deletion rule (BE-9040d prod flip)', () => {
    const text = mountTerms().text().replace(/\s+/g, ' ')
    // Post-BE-9040d: confirming deletion auto-cancels an active
    // subscription; access ends, no further charges. Consistent with
    // Privacy §6 and the canonical Terms of Service.
    expect(text).toMatch(/confirming deletion cancels it/i)
    expect(text).toMatch(/no further charges occur/i)
    expect(text).toMatch(/immediate deletion or an optional 30-day grace/i)
    expect(text).not.toMatch(/must first cancel it in Billing/i)
  })

  it('uses only operator mailboxes from the CLAUDE.md allowlist', () => {
    const wrapper = mountTerms()
    const html = wrapper.html()
    expect(html).toContain('admin@giljo.ai')
    expect(html).toContain('support@giljo.ai')
    expect(html).not.toContain(`patrik@${'giljo.ai'}`)
    expect(html).not.toContain(`mailto:info@${'giljo.ai'}`)
  })
})
