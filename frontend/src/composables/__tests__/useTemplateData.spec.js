
import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'
import { useTemplateData } from '@/composables/useTemplateData'

vi.mock('@/services/api', () => {
  const apiObj = { templates: { list: vi.fn(), activeCount: vi.fn(), importDefaults: vi.fn() } }
  return { api: apiObj, default: apiObj }
})

function makeTemplate(overrides = {}) {
  return {
    id: 'tpl-1',
    name: 'analyzer',
    role: 'analyzer',
    category: 'role',
    is_active: true,
    may_be_stale: false,
    user_managed_export: false,
    last_exported_at: '2026-01-01T12:00:00Z',
    updated_at: '2026-01-01T12:00:00Z',
    ...overrides,
  }
}

function setup(rows) {
  const search = ref('')
  const filterRole = ref(null)
  const filterStatus = ref(null)
  const data = useTemplateData(search, filterRole, filterStatus, ref('prod-1'), ref(false))
  data.templates.value = rows
  return { filterRole, filterStatus, ...data }
}

describe('useTemplateData — status filter (FE-9203 regression)', () => {
  const rows = [
    makeTemplate({ id: 'a', name: 'analyzer', role: 'analyzer', product_active: true }),
    makeTemplate({ id: 'b', name: 'reviewer', role: 'reviewer', product_active: false }),
    makeTemplate({ id: 'c', name: 'tester', role: 'tester', product_active: true }),
  ]

  it('filters on the per-product switch — "active" returns only the enabled agents', () => {
    const { filterStatus, filteredTemplates } = setup(rows)
    filterStatus.value = 'active'
    expect(filteredTemplates.value.map((t) => t.id)).toEqual(['a', 'c'])
  })

  it('"inactive" returns only the switched-off agents', () => {
    const { filterStatus, filteredTemplates } = setup(rows)
    filterStatus.value = 'inactive'
    expect(filteredTemplates.value.map((t) => t.id)).toEqual(['b'])
  })

  it('the "active" filter is NEVER empty when active templates exist (the original bug: t.status is undefined, everything filtered out)', () => {
    const { filterStatus, filteredTemplates } = setup(rows)
    filterStatus.value = 'active'
    expect(filteredTemplates.value.length).toBeGreaterThan(0)
  })
})

describe('useTemplateData — the status filter follows the per-product switch', () => {
  it('"active" keeps an agent with an active assignment', () => {
    const rows = [makeTemplate({ id: 'a', is_active: false, product_active: true })]
    const { filterStatus, filteredTemplates } = setup(rows)
    filterStatus.value = 'active'
    expect(filteredTemplates.value.map((t) => t.id)).toEqual(['a'])
  })

  it('"inactive" keeps an agent with no assignment at all', () => {
    const rows = [makeTemplate({ id: 'a', is_active: true })]
    const { filterStatus, filteredTemplates } = setup(rows)
    filterStatus.value = 'inactive'
    expect(filteredTemplates.value.map((t) => t.id)).toEqual(['a'])
  })

  it('"active" keeps an agent the viewed product has an explicit ON row for', () => {
    const rows = [makeTemplate({ id: 'a', product_active: true })]
    const { filterStatus, filteredTemplates } = setup(rows)
    filterStatus.value = 'active'
    expect(filteredTemplates.value.map((t) => t.id)).toEqual(['a'])
  })

  it('"inactive" keeps an agent that is OFF for the viewed product', () => {
    const rows = [makeTemplate({ id: 'b', is_active: true, product_active: false })]
    const { filterStatus, filteredTemplates } = setup(rows)
    filterStatus.value = 'inactive'
    expect(filteredTemplates.value.map((t) => t.id)).toEqual(['b'])
  })
})

describe('useTemplateData — role filter (FE-9203 regression)', () => {
  const rows = [
    makeTemplate({ id: 'a', role: 'analyzer' }),
    makeTemplate({ id: 'b', role: 'reviewer' }),
    makeTemplate({ id: 'c', role: 'analyzer', name: 'analyzer-fast' }),
  ]

  it('filters on the real role field', () => {
    const { filterRole, filteredTemplates } = setup(rows)
    filterRole.value = 'analyzer'
    expect(filteredTemplates.value.map((t) => t.id)).toEqual(['a', 'c'])
  })

  it('availableRoles derives distinct sorted roles from the loaded data — never a hardcoded list', () => {
    const { availableRoles } = setup(rows)
    expect(availableRoles.value).toEqual(['analyzer', 'reviewer'])
  })

  it('availableRoles skips rows without a role', () => {
    const { availableRoles } = setup([...rows, makeTemplate({ id: 'd', role: null })])
    expect(availableRoles.value).toEqual(['analyzer', 'reviewer'])
  })
})

describe('useTemplateData — orchestrator row behavior (unchanged)', () => {
  const rows = [makeTemplate({ id: 'a', is_active: true })]

  it('prepends the system orchestrator row when no filters are set', () => {
    const { filteredTemplates } = setup(rows)
    expect(filteredTemplates.value[0].id).toBe('__orchestrator__')
    expect(filteredTemplates.value).toHaveLength(2)
  })

  it('hides the orchestrator row when any filter is active', () => {
    const { filterStatus, filteredTemplates } = setup(rows)
    filterStatus.value = 'active'
    expect(filteredTemplates.value.every((t) => t.id !== '__orchestrator__')).toBe(true)
  })
})

describe('useTemplateData — importDefaults (FE-9203 Part 2)', () => {
  it('calls the import endpoint, refreshes data, and returns the summary', async () => {
    const api = (await import('@/services/api')).default
    const summary = { added: ['implementer'], added_as_duplicate: [], skipped_identical: [] }
    api.templates.importDefaults.mockResolvedValueOnce({ data: summary })
    api.templates.list.mockResolvedValueOnce({ data: [] })
    api.templates.activeCount.mockResolvedValueOnce({ data: { active_count: 1, limit: 15 } })

    const { importDefaults, importingDefaults } = setup([])
    const result = await importDefaults()

    expect(api.templates.importDefaults).toHaveBeenCalledTimes(1)
    expect(api.templates.list).toHaveBeenCalledTimes(1)
    expect(api.templates.activeCount).toHaveBeenCalledTimes(1)
    expect(result).toEqual(summary)
    expect(importingDefaults.value).toBe(false)
  })

  it('sets importingDefaults while in flight and clears it on failure', async () => {
    const api = (await import('@/services/api')).default
    let rejectImport
    api.templates.importDefaults.mockImplementationOnce(
      () => new Promise((_, reject) => (rejectImport = reject)),
    )

    const { importDefaults, importingDefaults } = setup([])
    const pending = importDefaults()
    expect(importingDefaults.value).toBe(true)

    rejectImport(new Error('boom'))
    await expect(pending).rejects.toThrow('boom')
    expect(importingDefaults.value).toBe(false)
  })
})
