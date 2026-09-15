import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { useProjectTaxonomy } from './useProjectTaxonomy'
import api from '@/services/api'

describe('useProjectTaxonomy', () => {
  let projectTypes
  let projectData

  beforeEach(() => {
    projectTypes = ref([
      { id: 'type-be', abbreviation: 'BE', label: 'Backend', color: '#6DB3E4' },
      { id: 'type-fe', abbreviation: 'FE', label: 'Frontend', color: '#5EC48E' },
    ])
    projectData = ref({
      project_type_id: null,
      series_number: null,
      subseries: null,
    })
  })

  it('initializes with default state', () => {
    const tax = useProjectTaxonomy({ projectTypes, projectData })
    expect(tax.showAddTypeModal.value).toBe(false)
    expect(tax.seriesNumberInput.value).toBe('')
    expect(tax.seriesChecking.value).toBe(false)
    expect(tax.seriesCheckResult.value).toBeNull()
    expect(tax.seriesCheckMessage.value).toBe('')
    expect(tax.usedSubseries.value).toEqual([])
  })

  it('typeDropdownItems includes all types plus add-custom entry', () => {
    const { typeDropdownItems } = useProjectTaxonomy({ projectTypes, projectData })
    expect(typeDropdownItems.value).toHaveLength(3)
    expect(typeDropdownItems.value.at(-1).id).toBe('__add_custom__')
    expect(typeDropdownItems.value[0].id).toBe('type-be')
  })

  it('excludes the reserved TSK type from typeDropdownItems', () => {
    projectTypes.value = [
      ...projectTypes.value,
      { id: 'type-tsk', abbreviation: 'TSK', label: 'Task', color: '#8b5cf6' },
    ]
    const { typeDropdownItems } = useProjectTaxonomy({ projectTypes, projectData })
    expect(typeDropdownItems.value.some((i) => i.abbreviation === 'TSK')).toBe(false)
    expect(typeDropdownItems.value).toHaveLength(3)
  })

  it('surfaces an excluded-but-current TSK type as a disabled entry when editing', () => {
    projectTypes.value = [
      ...projectTypes.value,
      { id: 'type-tsk', abbreviation: 'TSK', label: 'Task', color: '#8b5cf6' },
    ]
    const editingProject = ref({ id: 'p-conv', project_type_id: 'type-tsk' })
    const { typeDropdownItems } = useProjectTaxonomy({
      projectTypes,
      projectData,
      editingProject,
    })
    const tsk = typeDropdownItems.value.find((i) => i.id === 'type-tsk')
    expect(tsk).toBeDefined()
    expect(tsk.disabled).toBe(true)
    expect(tsk.abbreviation).toBe('TSK')
  })

  it('subseriesItems returns 26 letters when usedSubseries is empty', () => {
    const { subseriesItems } = useProjectTaxonomy({ projectTypes, projectData })
    expect(subseriesItems.value).toHaveLength(26)
    expect(subseriesItems.value[0].value).toBe('a')
    expect(subseriesItems.value[25].value).toBe('z')
  })

  it('subseriesItems excludes used letters', () => {
    const { subseriesItems, usedSubseries } = useProjectTaxonomy({ projectTypes, projectData })
    usedSubseries.value = ['a', 'b', 'c']
    expect(subseriesItems.value).toHaveLength(23)
    expect(subseriesItems.value.every((item) => !['a', 'b', 'c'].includes(item.value))).toBe(true)
  })

  it('handleTypeChange opens AddTypeModal and clears type when __add_custom__ is selected', () => {
    const { handleTypeChange, showAddTypeModal } = useProjectTaxonomy({ projectTypes, projectData })
    handleTypeChange('__add_custom__')
    expect(showAddTypeModal.value).toBe(true)
    expect(projectData.value.project_type_id).toBeNull()
  })

  it('handleTypeChange resets series check state', () => {
    const tax = useProjectTaxonomy({ projectTypes, projectData })
    tax.seriesCheckResult.value = true
    tax.seriesCheckMessage.value = 'available'
    tax.handleTypeChange('type-fe')
    expect(tax.seriesCheckResult.value).toBeNull()
    expect(tax.seriesCheckMessage.value).toBe('')
  })

  it('handleTypeCreated adds the new type and selects it', () => {
    const { handleTypeCreated } = useProjectTaxonomy({ projectTypes, projectData })
    const newType = { id: 'type-new', abbreviation: 'NW', label: 'New', color: '#fff' }
    handleTypeCreated(newType)
    expect(projectTypes.value.some((t) => t.id === 'type-new')).toBe(true)
    expect(projectData.value.project_type_id).toBe('type-new')
  })

  it('onSeriesInput clears state when input is empty', () => {
    const { onSeriesInput, seriesCheckResult, seriesCheckMessage } = useProjectTaxonomy({ projectTypes, projectData })
    seriesCheckResult.value = true
    seriesCheckMessage.value = 'available'
    onSeriesInput('')
    expect(projectData.value.series_number).toBeNull()
    expect(seriesCheckResult.value).toBeNull()
    expect(seriesCheckMessage.value).toBe('')
  })

  it('onSeriesInput sets error state for invalid number', () => {
    const { onSeriesInput, seriesCheckResult, seriesCheckMessage } = useProjectTaxonomy({ projectTypes, projectData })
    onSeriesInput('0')
    expect(seriesCheckResult.value).toBe(false)
    expect(seriesCheckMessage.value).toBe('Enter 1-9999')
  })

  it('onSeriesInput sets error state for number > 9999', () => {
    const { onSeriesInput, seriesCheckResult } = useProjectTaxonomy({ projectTypes, projectData })
    onSeriesInput('10000')
    expect(seriesCheckResult.value).toBe(false)
  })

  it('onSeriesInput sets error state for non-numeric', () => {
    const { onSeriesInput, seriesCheckResult } = useProjectTaxonomy({ projectTypes, projectData })
    onSeriesInput('abc')
    expect(seriesCheckResult.value).toBe(false)
  })

  it('onSeriesInput sets series_number and triggers check for valid input', async () => {
    vi.useFakeTimers()
    api.projects.checkSeries.mockResolvedValue({ data: { available: true } })
    api.projects.usedSubseries.mockResolvedValue({ data: { used_subseries: [] } })

    const { onSeriesInput } = useProjectTaxonomy({ projectTypes, projectData })
    onSeriesInput('5')
    expect(projectData.value.series_number).toBe(5)

    vi.useRealTimers()
  })

  it('resetTaxonomy clears all taxonomy state', () => {
    const tax = useProjectTaxonomy({ projectTypes, projectData })
    tax.seriesNumberInput.value = '0001'
    tax.seriesCheckResult.value = true
    tax.seriesCheckMessage.value = 'available'
    tax.usedSubseries.value = ['a']
    tax.resetTaxonomy()
    expect(tax.seriesNumberInput.value).toBe('')
    expect(tax.seriesCheckResult.value).toBeNull()
    expect(tax.seriesCheckMessage.value).toBe('')
    expect(tax.usedSubseries.value).toEqual([])
  })
})
