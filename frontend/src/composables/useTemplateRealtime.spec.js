/**
 * useTemplateRealtime.spec.js — FE-9385c
 *
 * Coverage for the realtime composable extracted from TemplateManager.vue.
 *
 * This file exists to discharge a debt. The extraction shipped verified by
 * hand-trace rather than by test — nothing in the suite dispatched any of the
 * three window events, so the whole composable could have been deleted and
 * every spec would still have passed. These assertions are what make that
 * false.
 *
 * Two house patterns combined, neither invented here:
 *   - a minimal host component, because onMounted/onUnmounted/inject need a
 *     live component context (the useProjectTabsLifecycle.spec.js shape)
 *   - window CustomEvent dispatch (the useHubNotifications.spec.js shape)
 *
 * The unmount test asserts BEHAVIOUR, not that removeEventListener was called:
 * a spy on the call proves the line ran, while a handler removed with a
 * different function reference would satisfy that spy and leak anyway.
 *
 * Edition scope: CE
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref, defineComponent } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { useTemplateRealtime } from '@/composables/useTemplateRealtime'

const TENANT = 'tk_test'
const OTHER_TENANT = 'tk_someone_else'

// The composable's only store dependency is one field, so it is mocked rather
// than stood up through Pinia. tests/setup.js already installs a global pinia
// via config.global.plugins, and adding a second one here would double-provide
// the injection key and warn on every mount for no gain.
let signedInUser = null

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    get currentUser() {
      return signedInUser
    },
  }),
}))

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeTemplates() {
  return [
    {
      id: 1,
      name: 'Analyzer',
      is_active: true,
      may_be_stale: true,
      user_managed_export: true,
      last_exported_at: null,
    },
    {
      id: 2,
      name: 'Reviewer',
      is_active: false,
      may_be_stale: true,
      user_managed_export: true,
      last_exported_at: null,
    },
  ]
}

/**
 * Mount a host component that does nothing but run the composable in setup.
 * Returns the wrapper plus the reactive rows and spies the test asserts on.
 */
function mountHost({ tenantKey = TENANT } = {}) {
  signedInUser = tenantKey === null ? null : { id: 1, username: 'testuser', tenant_key: tenantKey }

  const templates = ref(makeTemplates())
  const reloadActiveCount = vi.fn()
  const templateExportEvent = ref(null)

  const Host = defineComponent({
    setup() {
      useTemplateRealtime(templates, reloadActiveCount)
      return () => null
    },
  })

  const wrapper = mount(Host, {
    global: { provide: { templateExportEvent } },
  })

  return { wrapper, templates, reloadActiveCount, templateExportEvent }
}

const dispatch = (name, detail) => window.dispatchEvent(new CustomEvent(name, { detail }))

const exportedPayload = (overrides = {}) => ({
  tenant_key: TENANT,
  template_ids: [1],
  exported_at: '2026-08-11T00:00:00Z',
  ...overrides,
})

// ---------------------------------------------------------------------------
// Group 1 — template:exported
// ---------------------------------------------------------------------------

describe('useTemplateRealtime — template:exported', () => {
  let ctx

  beforeEach(() => {
    ctx = mountHost()
  })

  it('stamps last_exported_at and clears may_be_stale on the named rows ONLY', () => {
    dispatch('template:exported', exportedPayload({ template_ids: [1] }))

    const [named, untouched] = ctx.templates.value
    expect(named.last_exported_at).toBe('2026-08-11T00:00:00Z')
    expect(named.may_be_stale).toBe(false)

    // The row that was not named must be exactly as it started. This is the
    // real assertion of the group — a handler that patched every row would
    // satisfy the two above and still be wrong.
    expect(untouched.last_exported_at).toBeNull()
    expect(untouched.may_be_stale).toBe(true)
  })

  it('patches every row named, when more than one is', () => {
    dispatch('template:exported', exportedPayload({ template_ids: [1, 2] }))

    for (const t of ctx.templates.value) {
      expect(t.last_exported_at).toBe('2026-08-11T00:00:00Z')
      expect(t.may_be_stale).toBe(false)
    }
  })

  it('drops a payload belonging to another tenant', () => {
    dispatch('template:exported', exportedPayload({ tenant_key: OTHER_TENANT }))

    // Nothing moved. This is the isolation boundary: another tenant's export
    // must never stamp rows on this screen.
    for (const t of ctx.templates.value) {
      expect(t.last_exported_at).toBeNull()
      expect(t.may_be_stale).toBe(true)
    }
  })

  it.each([
    ['tenant_key', { tenant_key: undefined }],
    ['template_ids', { template_ids: undefined }],
    ['exported_at', { exported_at: undefined }],
  ])('ignores a payload missing %s', (_field, missing) => {
    dispatch('template:exported', exportedPayload(missing))

    for (const t of ctx.templates.value) {
      expect(t.last_exported_at).toBeNull()
      expect(t.may_be_stale).toBe(true)
    }
  })

  it('drops every payload while no user is loaded', () => {
    // currentTenantKey reads through `currentUser?.tenant_key`, so before the
    // user store has resolved it is undefined. An event arriving in that window
    // must not be treated as belonging to the current tenant.
    const signedOut = mountHost({ tenantKey: null })

    dispatch('template:exported', exportedPayload({ template_ids: [1, 2] }))

    for (const t of signedOut.templates.value) {
      expect(t.last_exported_at).toBeNull()
    }
  })
})

// ---------------------------------------------------------------------------
// Group 2 — template:updated
// ---------------------------------------------------------------------------

describe('useTemplateRealtime — template:updated', () => {
  let ctx

  beforeEach(() => {
    ctx = mountHost()
  })

  it('mirrors is_active and may_be_stale onto the addressed row', () => {
    dispatch('template:updated', { template_id: 2, is_active: true, may_be_stale: false })

    const row = ctx.templates.value.find((t) => t.id === 2)
    expect(row.is_active).toBe(true)
    expect(row.may_be_stale).toBe(false)
  })

  it('leaves a field absent from the payload untouched — absent is not false', () => {
    dispatch('template:updated', { template_id: 1, may_be_stale: false })

    const row = ctx.templates.value.find((t) => t.id === 1)
    expect(row.may_be_stale).toBe(false)
    // is_active was not in the payload, so it must be left alone. A handler
    // that assigned unconditionally would write `undefined` over it here.
    expect(row.is_active).toBe(true)
  })

  it('applies an explicit false — false is not absent', () => {
    // The mirror image of the test above, and the one that pins `!== undefined`
    // rather than a truthiness check. A truthy test would skip this payload and
    // leave the agent switched on after the server said it was switched off.
    dispatch('template:updated', { template_id: 1, is_active: false })

    expect(ctx.templates.value.find((t) => t.id === 1).is_active).toBe(false)
  })

  it('ignores an event with no template_id', () => {
    dispatch('template:updated', { is_active: false })

    expect(ctx.templates.value.map((t) => t.is_active)).toEqual([true, false])
  })

  it('ignores an event addressing a template that is not on screen', () => {
    dispatch('template:updated', { template_id: 999, is_active: false })

    expect(ctx.templates.value.map((t) => t.is_active)).toEqual([true, false])
  })

  it('refreshes the active count when updated_fields includes is_active', () => {
    dispatch('template:updated', {
      template_id: 1,
      is_active: false,
      updated_fields: ['is_active'],
    })

    expect(ctx.reloadActiveCount).toHaveBeenCalledTimes(1)
  })

  it('does NOT refresh the active count for an unrelated field change', () => {
    dispatch('template:updated', {
      template_id: 1,
      may_be_stale: true,
      updated_fields: ['description'],
    })

    expect(ctx.reloadActiveCount).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Group 3 — setup:agents_downloaded
// ---------------------------------------------------------------------------

describe('useTemplateRealtime — setup:agents_downloaded', () => {
  it('stamps every row and clears both staleness and the user-managed flag', () => {
    const ctx = mountHost()

    dispatch('setup:agents_downloaded', {})

    for (const t of ctx.templates.value) {
      expect(t.last_exported_at).not.toBeNull()
      expect(t.may_be_stale).toBe(false)
      // The only handler that clears this third flag: a giljo_setup download
      // supersedes a user's "I manage this myself" dismissal.
      expect(t.user_managed_export).toBe(false)
    }
  })
})

// ---------------------------------------------------------------------------
// Group 4 — the injected export event (the second entry point)
// ---------------------------------------------------------------------------

describe('useTemplateRealtime — injected templateExportEvent', () => {
  it('funnels a provided export event into the same handler', async () => {
    const ctx = mountHost()

    ctx.templateExportEvent.value = exportedPayload({ template_ids: [2] })
    await flushPromises()

    const row = ctx.templates.value.find((t) => t.id === 2)
    expect(row.last_exported_at).toBe('2026-08-11T00:00:00Z')
    expect(row.may_be_stale).toBe(false)
  })

  it('applies the tenant guard on the injected path too', async () => {
    const ctx = mountHost()

    ctx.templateExportEvent.value = exportedPayload({ tenant_key: OTHER_TENANT })
    await flushPromises()

    for (const t of ctx.templates.value) {
      expect(t.last_exported_at).toBeNull()
    }
  })
})

// ---------------------------------------------------------------------------
// Group 5 — teardown
// ---------------------------------------------------------------------------

describe('useTemplateRealtime — teardown', () => {
  it('stops responding to all three events after unmount', () => {
    const ctx = mountHost()

    ctx.wrapper.unmount()

    dispatch('template:exported', exportedPayload({ template_ids: [1, 2] }))
    dispatch('template:updated', {
      template_id: 1,
      is_active: false,
      updated_fields: ['is_active'],
    })
    dispatch('setup:agents_downloaded', {})

    // Asserted as behaviour rather than as a removeEventListener spy: a handler
    // removed with a different function reference would pass such a spy and
    // still leak. Unchanged rows prove the listeners are genuinely gone.
    for (const t of ctx.templates.value) {
      expect(t.last_exported_at).toBeNull()
      expect(t.may_be_stale).toBe(true)
      expect(t.user_managed_export).toBe(true)
    }
    expect(ctx.templates.value.map((t) => t.is_active)).toEqual([true, false])
    expect(ctx.reloadActiveCount).not.toHaveBeenCalled()
  })
})
