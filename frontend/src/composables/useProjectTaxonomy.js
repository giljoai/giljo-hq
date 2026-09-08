/**
 * useProjectTaxonomy Composable
 *
 * Encapsulates project type selection, series number availability checking,
 * and subseries management for the project create/edit form.
 *
 * Extracted from ProjectsView.vue (Handover 0950k).
 *
 * @param {object} params
 * @param {import('vue').Ref<Array>} params.projectTypes - Available project types (mutated on handleTypeCreated)
 * @param {import('vue').Ref<object>} params.projectData - Form data ref (project_type_id, series_number, subseries)
 * @param {import('vue').Ref<object|null>} [params.editingProject] - Currently editing project (for exclude ID)
 * @param {import('vue').Ref<string|null>} [params.productId] - FE-9502c: the
 *   product to scope series-number lookups to (the viewed tab). Falls back
 *   to the server's active product when omitted, same as before tabs.
 */
import { ref, computed, onBeforeUnmount, getCurrentInstance } from 'vue'
import api from '@/services/api'
import { RESERVED_TASK_TYPE_ABBR } from '@/utils/constants'

export function useProjectTaxonomy({
  projectTypes,
  projectData,
  editingProject = ref(null),
  productId = ref(null),
}) {
  const showAddTypeModal = ref(false)
  const seriesNumberInput = ref('')
  const seriesChecking = ref(false)
  const seriesCheckResult = ref(null)
  const seriesCheckMessage = ref('')
  const usedSubseries = ref([])
  let seriesCheckTimer = null
  let seriesAbortController = null

  const typeDropdownItems = computed(() => {
    // TSK is reserved for tasks (BE-6049c) — never offer it as a selectable
    // project type.
    const items = projectTypes.value
      .filter((t) => t.abbreviation !== RESERVED_TASK_TYPE_ABBR)
      .map((t) => ({
        id: t.id,
        display: `${t.abbreviation} - ${t.label}`,
        abbreviation: t.abbreviation,
        color: t.color,
      }))
    // A converted project ALREADY HAS type TSK (the read-time origin signal,
    // ENTRY 7). TSK is excluded from the selectable set above, so the bound
    // `project_type_id` would otherwise render blank. Surface the current type
    // as a DISABLED, non-selectable entry so it displays without being a valid
    // choice. Generic: handles any excluded-but-current type, not just TSK.
    const currentId = editingProject.value?.project_type_id
    if (currentId && !items.some((i) => i.id === currentId)) {
      const currentType = projectTypes.value.find((t) => t.id === currentId)
      if (currentType) {
        items.push({
          id: currentType.id,
          display: `${currentType.abbreviation} - ${currentType.label}`,
          abbreviation: currentType.abbreviation,
          color: currentType.color,
          disabled: true,
        })
      }
    }
    items.push({ id: '__add_custom__', display: 'Add custom type...', color: 'transparent', abbreviation: '' })
    return items
  })

  const subseriesItems = computed(() => {
    const items = []
    for (let i = 0; i < 26; i++) {
      const letter = String.fromCharCode(97 + i)
      if (!usedSubseries.value.includes(letter)) {
        items.push({ title: letter, value: letter })
      }
    }
    return items
  })

  /**
   * Auto-fill the next available serial number for the given project type.
   * Only runs in create mode (no editingProject) when the serial input is empty.
   * Failures are swallowed (console.warn) so dropdown selection never throws.
   * UI-0004.
   */
  async function autoFillNextSeries(typeId) {
    if (!typeId || typeId === '__add_custom__') return
    if (editingProject.value) return
    const currentInput = (seriesNumberInput.value || '').trim()
    if (currentInput !== '' || projectData.value.series_number != null) return
    try {
      const { data } = await api.projects.getNextSeries(typeId, productId.value)
      const next = data?.next_series_number
      if (typeof next !== 'number') return
      // Re-check guards after async await — user may have typed meanwhile.
      const inputNow = (seriesNumberInput.value || '').trim()
      if (inputNow !== '' || projectData.value.series_number != null) return
      seriesNumberInput.value = String(next).padStart(4, '0')
      projectData.value.series_number = next
      seriesChecking.value = true
      if (seriesCheckTimer) clearTimeout(seriesCheckTimer)
      seriesCheckTimer = setTimeout(() => checkSeriesAvailability(next), 300)
    } catch (err) {
      // Never throw out of handleTypeChange — leave field empty for manual entry.

      console.warn('[useProjectTaxonomy] getNextSeries failed:', err)
    }
  }

  function handleTypeChange(typeId) {
    if (typeId === '__add_custom__') {
      showAddTypeModal.value = true
      projectData.value.project_type_id = null
      return
    }
    seriesCheckResult.value = null
    seriesCheckMessage.value = ''
    usedSubseries.value = []
    if (projectData.value.series_number) {
      seriesChecking.value = true
      if (seriesCheckTimer) clearTimeout(seriesCheckTimer)
      seriesCheckTimer = setTimeout(() => checkSeriesAvailability(projectData.value.series_number), 300)
    } else {
      // Create mode + empty serial → auto-fill next available (UI-0004).
      autoFillNextSeries(typeId)
    }
  }

  function handleTypeCreated(newType) {
    projectTypes.value.push(newType)
    projectData.value.project_type_id = newType.id
    usedSubseries.value = []
    if (projectData.value.series_number) {
      seriesChecking.value = true
      if (seriesCheckTimer) clearTimeout(seriesCheckTimer)
      seriesCheckTimer = setTimeout(() => checkSeriesAvailability(projectData.value.series_number), 300)
    } else {
      // Create mode + empty serial → auto-fill next available (UI-0004).
      autoFillNextSeries(newType.id)
    }
  }

  function onSeriesInput(val) {
    if (seriesCheckTimer) clearTimeout(seriesCheckTimer)

    const trimmed = (val || '').trim()
    if (!trimmed) {
      projectData.value.series_number = null
      usedSubseries.value = []
      seriesCheckResult.value = null
      seriesCheckMessage.value = ''
      return
    }

    const num = parseInt(trimmed, 10)
    if (isNaN(num) || num < 1 || num > 9999) {
      projectData.value.series_number = null
      usedSubseries.value = []
      seriesCheckResult.value = false
      seriesCheckMessage.value = 'Enter 1-9999'
      return
    }

    projectData.value.series_number = num
    usedSubseries.value = []

    seriesChecking.value = true
    seriesCheckTimer = setTimeout(() => checkSeriesAvailability(num), 300)
  }

  async function checkSeriesAvailability(num) {
    if (!num) {
      seriesChecking.value = false
      return
    }
    if (seriesAbortController) seriesAbortController.abort()
    seriesAbortController = new AbortController()
    const { signal } = seriesAbortController

    const requestedTypeId = projectData.value.project_type_id
    const excludeId = editingProject.value?.id || null
    try {
      const [checkRes, usedRes] = await Promise.all([
        api.projects.checkSeries(
          requestedTypeId,
          num,
          projectData.value.subseries,
          excludeId,
          { signal },
          productId.value,
        ),
        api.projects.usedSubseries(
          requestedTypeId,
          num,
          excludeId,
          { signal },
          productId.value,
        ),
      ])
      if (projectData.value.project_type_id !== requestedTypeId) return
      seriesCheckResult.value = checkRes.data.available
      seriesCheckMessage.value = checkRes.data.available
        ? `${String(num).padStart(4, '0')} available`
        : `${String(num).padStart(4, '0')} taken`
      usedSubseries.value = usedRes.data.used_subseries || []
    } catch (err) {
      if (err?.name === 'AbortError' || err?.name === 'CanceledError') return
      seriesCheckResult.value = null
      seriesCheckMessage.value = ''
      usedSubseries.value = []
    } finally {
      seriesChecking.value = false
    }
  }

  function onSubseriesChange() {
    if (projectData.value.series_number) {
      if (seriesCheckTimer) clearTimeout(seriesCheckTimer)
      seriesChecking.value = true
      seriesCheckTimer = setTimeout(
        () => checkSeriesAvailability(projectData.value.series_number),
        300,
      )
    }
  }

  function resetTaxonomy() {
    seriesNumberInput.value = ''
    seriesCheckResult.value = null
    seriesCheckMessage.value = ''
    seriesChecking.value = false
    usedSubseries.value = []
    if (seriesCheckTimer) clearTimeout(seriesCheckTimer)
  }

  function cleanup() {
    if (seriesCheckTimer) clearTimeout(seriesCheckTimer)
    if (seriesAbortController) seriesAbortController.abort()
  }

  // Register cleanup automatically when called inside a component setup()
  if (getCurrentInstance()) {
    onBeforeUnmount(cleanup)
  }

  return {
    showAddTypeModal,
    seriesNumberInput,
    seriesChecking,
    seriesCheckResult,
    seriesCheckMessage,
    usedSubseries,
    typeDropdownItems,
    subseriesItems,
    handleTypeChange,
    handleTypeCreated,
    onSeriesInput,
    checkSeriesAvailability,
    onSubseriesChange,
    resetTaxonomy,
    cleanup,
  }
}
