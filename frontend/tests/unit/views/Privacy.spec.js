/**
 * Privacy.vue regression spec (CE render).
 *
 * Locks in:
 *   - Vendor-neutral CE copy: the billing provider is described by role
 *     (Merchant of Record), never by name. The vendor-naming copy lives in
 *     saas/ components and is asserted by
 *     frontend/tests/unit/saas/views/policyPagesSaas.spec.js, which the CE
 *     export strips (FE-9374b; the export gate greps CE-shipped source,
 *     this spec included, for provider names).
 *   - Billing data class enumerated (joint-controller framing).
 *   - Auto-cancel deletion rule (BE-9040d prod flip).
 *
 * Edition: ships in CE.
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import Privacy from '@/views/Privacy.vue'

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: async () => ({}),
    getGiljoMode: () => 'ce',
  },
}))

function mountPrivacy() {
  return mount(Privacy, {
    global: {
      stubs: {
        'v-container': { template: '<div><slot /></div>' },
        'v-card': { template: '<div><slot /></div>' },
        'router-link': { template: '<a><slot /></a>' },
      },
    },
  })
}

describe('Privacy.vue', () => {
  it('describes the billing provider by role, vendor-neutral in CE (FE-9374b)', () => {
    const wrapper = mountPrivacy()
    expect(wrapper.text()).toContain('Merchant of Record')
    expect(wrapper.text().toLowerCase()).toContain('billing provider')
  })

  it('enumerates the billing-data class collected by the provider', () => {
    const wrapper = mountPrivacy()
    expect(wrapper.text()).toContain('Billing data')
    expect(wrapper.text()).toMatch(/billing address/i)
    expect(wrapper.text()).toMatch(/tax ID/i)
    expect(wrapper.text()).toMatch(/never card numbers/i)
  })

  it('states the auto-cancel deletion rule (BE-9040d prod flip)', () => {
    // Whitespace-normalized so word-pair regexes are robust to template
    // line wrapping.
    const text = mountPrivacy().text().replace(/\s+/g, ' ')
    // Post-BE-9040d live behavior: the cancel-first interlock is gone;
    // confirming deletion auto-cancels an active subscription. Copy must
    // match the canonical Privacy Policy — deletion cancels the
    // subscription, access ends, no further charges, remaining paid time
    // forfeited.
    expect(text).toMatch(/confirming deletion cancels it/i)
    expect(text).toMatch(/no further charges occur/i)
    expect(text).toMatch(/forfeited/i)
    // Choose-the-pace flow from BE-9040c.
    expect(text).toMatch(/immediate deletion/i)
    expect(text).toMatch(/30-day grace/i)
    // Retired wordings must be gone: the cancel-first interlock and the
    // old fixed 37-day window (canonical uses immediate-or-grace).
    expect(text).not.toMatch(/must first cancel it in Billing/i)
    expect(text).not.toMatch(/within 37 days/i)
  })

  it('uses only operator mailboxes from the CLAUDE.md allowlist', () => {
    const wrapper = mountPrivacy()
    const html = wrapper.html()
    // Privacy/legal queries route to admin@ per CLAUDE.md.
    expect(html).toContain('admin@giljo.ai')
    // patrik@ is banned in any file regardless of context.
    expect(html).not.toContain(`patrik@${'giljo.ai'}`)
    // info@ is not in the operator allowlist (the alias is infoteam@).
    expect(html).not.toContain(`mailto:info@${'giljo.ai'}`)
  })
})
