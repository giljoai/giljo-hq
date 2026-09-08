/**
 * useProjectTaxonomy.fe9502c.spec.js — FE-9502c
 *
 * The tabbed product shell needs series-number lookups to resolve against
 * the VIEWED tab's product, not whichever product happens to be server-active
 * (api/endpoints/projects/series.py's product_id override, this same
 * project). Proves the composable actually forwards `productId` to every
 * one of the three live-lookup API calls -- the override is useless if
 * nothing on the frontend passes it.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref, nextTick } from 'vue'
import { useProjectTaxonomy } from './useProjectTaxonomy'
import api from '@/services/api'

const VIEWED_PRODUCT_ID = 'prod-viewed-A'

describe('useProjectTaxonomy — FE-9502c forwards productId (the viewed tab)', () => {
  let projectTypes
  let projectData
  let productId

  beforeEach(() => {
    vi.clearAllMocks()
    projectTypes = ref([{ id: 'type-be', abbreviation: 'BE', label: 'Backend', color: '#6DB3E4' }])
    projectData = ref({ project_type_id: null, series_number: null, subseries: null })
    productId = ref(VIEWED_PRODUCT_ID)
    api.projects.getNextSeries.mockResolvedValue({ data: { next_series_number: 3 } })
    api.projects.checkSeries.mockResolvedValue({ data: { available: true } })
    api.projects.usedSubseries.mockResolvedValue({ data: { used_subseries: [] } })
  })

  it('autoFillNextSeries passes productId through to getNextSeries', async () => {
    const tax = useProjectTaxonomy({ projectTypes, projectData, productId })
    tax.handleTypeChange('type-be')
    await nextTick()

    expect(api.projects.getNextSeries).toHaveBeenCalledWith('type-be', VIEWED_PRODUCT_ID)
  })

  it('checkSeriesAvailability passes productId through to checkSeries and usedSubseries', async () => {
    vi.useFakeTimers()
    const tax = useProjectTaxonomy({ projectTypes, projectData, productId })
    projectData.value.project_type_id = 'type-be'
    tax.onSeriesInput('0005')
    await vi.runAllTimersAsync()
    vi.useRealTimers()

    expect(api.projects.checkSeries).toHaveBeenCalledWith(
      'type-be',
      5,
      null,
      null,
      expect.any(Object),
      VIEWED_PRODUCT_ID,
    )
    expect(api.projects.usedSubseries).toHaveBeenCalledWith(
      'type-be',
      5,
      null,
      expect.any(Object),
      VIEWED_PRODUCT_ID,
    )
  })

  it('omitting productId falls through to the server-active default (undefined arg, not a fabricated id)', async () => {
    const tax = useProjectTaxonomy({ projectTypes, projectData })
    tax.handleTypeChange('type-be')
    await nextTick()

    expect(api.projects.getNextSeries).toHaveBeenCalledWith('type-be', null)
  })
})
