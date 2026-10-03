import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ref } from 'vue'
import { useProjectTaxonomy } from './useProjectTaxonomy'
import api from '@/services/api'

describe('useProjectTaxonomy series check scheduling', () => {
  let projectData
  let tax

  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    api.projects.checkSeries.mockResolvedValue({ data: { available: true } })
    api.projects.usedSubseries.mockResolvedValue({ data: { used_subseries: [] } })
    projectData = ref({ project_type_id: 'type-be', series_number: 7, subseries: null })
    tax = useProjectTaxonomy({ projectTypes: ref([{ id: 'type-be' }]), projectData })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  const checkedNumbers = () => api.projects.checkSeries.mock.calls.map((c) => c[1])

  it.each([
    ['handleTypeChange', (t) => t.handleTypeChange('type-be')],
    ['handleTypeCreated', (t) => t.handleTypeCreated({ id: 'type-be' })],
    ['onSubseriesChange', (t) => t.onSubseriesChange()],
  ])('%s checks the series number current when the timer fires', async (_name, act) => {
    act(tax)
    expect(tax.seriesChecking.value).toBe(true)
    projectData.value.series_number = 8
    await vi.advanceTimersByTimeAsync(299)
    expect(checkedNumbers()).toEqual([])
    await vi.advanceTimersByTimeAsync(1)
    expect(checkedNumbers()).toEqual([8])
  })

  it('onSeriesInput checks the number typed', async () => {
    tax.onSeriesInput('12')
    expect(tax.seriesChecking.value).toBe(true)
    await vi.advanceTimersByTimeAsync(300)
    expect(checkedNumbers()).toEqual([12])
  })

  it('repeat calls inside the window send one request', async () => {
    tax.onSubseriesChange()
    tax.handleTypeChange('type-be')
    tax.onSeriesInput('9')
    await vi.advanceTimersByTimeAsync(300)
    expect(checkedNumbers()).toEqual([9])
  })

  it('an auto-filled series number is checked', async () => {
    projectData.value.series_number = null
    api.projects.getNextSeries.mockResolvedValue({ data: { next_series_number: 42 } })
    tax.handleTypeChange('type-be')
    await vi.advanceTimersByTimeAsync(0)
    expect(tax.seriesNumberInput.value).toBe('0042')
    expect(tax.seriesChecking.value).toBe(true)
    await vi.advanceTimersByTimeAsync(300)
    expect(checkedNumbers()).toEqual([42])
  })

  it('no series number: onSubseriesChange schedules nothing', async () => {
    projectData.value.series_number = null
    tax.onSubseriesChange()
    expect(tax.seriesChecking.value).toBe(false)
    await vi.advanceTimersByTimeAsync(300)
    expect(checkedNumbers()).toEqual([])
  })
})
