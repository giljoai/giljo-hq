import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { useProjectTaxonomy } from '@/composables/useProjectTaxonomy'
import api from '@/services/api'

vi.mock('@/services/api', () => ({
  default: {
    projects: {
      getNextSeries: vi.fn(),
      checkSeries: vi.fn(),
      usedSubseries: vi.fn(),
    },
  },
}))

// Wait long enough for the 300ms debounce inside the composable + microtasks.
const wait = (ms = 350) => new Promise((resolve) => setTimeout(resolve, ms))

describe('useProjectTaxonomy - auto-fill next serial (UI-0004)', () => {
  let projectTypes
  let projectData
  let editingProject

  beforeEach(() => {
    vi.clearAllMocks()
    projectTypes = ref([
      { id: 'type-1', label: 'Backend', abbreviation: 'BE', color: '#fff' },
    ])
    projectData = ref({
      project_type_id: null,
      series_number: null,
      subseries: null,
    })
    editingProject = ref(null)
  })

  it('(a) auto-fills next serial in create mode when serial input is empty', async () => {
    api.projects.getNextSeries.mockResolvedValue({
      data: { next_series_number: 42 },
    })
    api.projects.checkSeries.mockResolvedValue({ data: { available: true } })
    api.projects.usedSubseries.mockResolvedValue({ data: { used_subseries: [] } })

    const t = useProjectTaxonomy({ projectTypes, projectData, editingProject })
    projectData.value.project_type_id = 'type-1'

    t.handleTypeChange('type-1')
    await wait()

    expect(api.projects.getNextSeries).toHaveBeenCalledWith('type-1', null)
    expect(t.seriesNumberInput.value).toBe('0042')
    expect(projectData.value.series_number).toBe(42)
    expect(api.projects.checkSeries).toHaveBeenCalled()
  })

  it('(b) does NOT auto-fill in edit mode (editingProject set)', async () => {
    editingProject.value = { id: 'proj-9', series_number: 7 }
    const t = useProjectTaxonomy({ projectTypes, projectData, editingProject })

    t.handleTypeChange('type-1')
    await wait(50)

    expect(api.projects.getNextSeries).not.toHaveBeenCalled()
    expect(t.seriesNumberInput.value).toBe('')
  })

  it('(c) does NOT overwrite when seriesNumberInput already has a value', async () => {
    api.projects.checkSeries.mockResolvedValue({ data: { available: true } })
    api.projects.usedSubseries.mockResolvedValue({ data: { used_subseries: [] } })

    const t = useProjectTaxonomy({ projectTypes, projectData, editingProject })
    t.seriesNumberInput.value = '0123'
    projectData.value.series_number = 123
    projectData.value.project_type_id = 'type-1'

    t.handleTypeChange('type-1')
    await wait()

    expect(api.projects.getNextSeries).not.toHaveBeenCalled()
    expect(t.seriesNumberInput.value).toBe('0123')
    expect(projectData.value.series_number).toBe(123)
  })

  it('(d) duplicate guard: when checkSeries reports unavailable, result is false and message says "taken"', async () => {
    api.projects.getNextSeries.mockResolvedValue({
      data: { next_series_number: 5 },
    })
    api.projects.checkSeries.mockResolvedValue({ data: { available: false } })
    api.projects.usedSubseries.mockResolvedValue({ data: { used_subseries: [] } })

    const t = useProjectTaxonomy({ projectTypes, projectData, editingProject })
    projectData.value.project_type_id = 'type-1'

    t.handleTypeChange('type-1')
    await wait()

    expect(t.seriesCheckResult.value).toBe(false)
    expect(t.seriesCheckMessage.value).toContain('taken')
  })

  it('(e) getNextSeries failure is swallowed (console.warn) and field stays empty', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    api.projects.getNextSeries.mockRejectedValue(new Error('boom'))

    const t = useProjectTaxonomy({ projectTypes, projectData, editingProject })
    projectData.value.project_type_id = 'type-1'

    expect(() => t.handleTypeChange('type-1')).not.toThrow()
    await wait()

    expect(t.seriesNumberInput.value).toBe('')
    expect(projectData.value.series_number).toBeNull()
    expect(warnSpy).toHaveBeenCalled()
    warnSpy.mockRestore()
  })

  it('(a-bis) handleTypeCreated also auto-fills in create mode', async () => {
    api.projects.getNextSeries.mockResolvedValue({
      data: { next_series_number: 9 },
    })
    api.projects.checkSeries.mockResolvedValue({ data: { available: true } })
    api.projects.usedSubseries.mockResolvedValue({ data: { used_subseries: [] } })

    const t = useProjectTaxonomy({ projectTypes, projectData, editingProject })
    const newType = { id: 'type-2', label: 'New', abbreviation: 'NW', color: '#aaa' }

    t.handleTypeCreated(newType)
    await wait()

    expect(api.projects.getNextSeries).toHaveBeenCalledWith('type-2', null)
    expect(t.seriesNumberInput.value).toBe('0009')
    expect(projectData.value.series_number).toBe(9)
  })

  it('skips __add_custom__ sentinel without auto-fill', async () => {
    const t = useProjectTaxonomy({ projectTypes, projectData, editingProject })
    t.handleTypeChange('__add_custom__')
    await wait(50)
    expect(api.projects.getNextSeries).not.toHaveBeenCalled()
    expect(t.showAddTypeModal.value).toBe(true)
  })
})
