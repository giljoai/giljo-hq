import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import Privacy from '@/views/Privacy.vue'
import Terms from '@/views/Terms.vue'

// FE-9374: anti-drift guard for the in-app policy pages. These documents were
// found stale (a cancelled tier advertised, subprocessors missing) after
// PR #748 made them reachable logged-out. A content hash would be too brittle;
// this asserts the semantic invariants that must not regress.
//
// FE-9374b: this spec ships to CE, so it asserts the CE render only and must
// itself stay vendor-free: the export gate greps CE-shipped source (comments
// and test literals included) for billing-provider names. The hosted-edition
// render, and the no-vendor-names-in-CE-render invariant, are asserted in
// frontend/tests/unit/saas/views/policyPagesSaas.spec.js, which the CE export
// strips.

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: async () => ({}),
    getGiljoMode: () => 'ce',
  },
}))

const mountOptions = {
  global: {
    stubs: {
      RouterLink: { template: '<a><slot /></a>' },
    },
  },
}

function renderedText(component) {
  return mount(component, mountOptions).text()
}

describe('FE-9374 policy page content guards (CE render)', () => {
  it('never mentions a Team tier (cancelled per ADR-009)', () => {
    // Case-sensitive on purpose: "your team" (lowercase) is legitimate CE
    // language; a capital-T "Team" is the cancelled tier resurfacing.
    expect(renderedText(Terms)).not.toMatch(/\bTeam\b/)
    expect(renderedText(Privacy)).not.toMatch(/\bTeam\b/)
  })

  it('keeps the neutral billing-provider wording in both pages', () => {
    // CE renders complete, truthful policy pages: a billing provider acting
    // as Merchant of Record, described by role rather than by name.
    expect(renderedText(Privacy)).toContain('Merchant of Record')
    expect(renderedText(Privacy).toLowerCase()).toContain('billing provider')
    expect(renderedText(Terms)).toContain('Merchant of Record')
    expect(renderedText(Terms).toLowerCase()).toContain('billing provider')
  })

  it('uses no em dashes in customer-facing policy text', () => {
    expect(renderedText(Privacy)).not.toContain('—')
    expect(renderedText(Terms)).not.toContain('—')
  })
})
