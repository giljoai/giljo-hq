import { ref } from 'vue'
import { useProductStore } from '@/stores/products'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'

export function useVisionAnalysis(patchProductForm, { copyPromptOnStage = true } = {}) {
  const productStore = useProductStore()
  const { copy: copyToClipboard } = useClipboard()
  const { showToast } = useToast()

  const analysisPromptCopied = ref(false)
  const promptFallbackText = ref(null)
  const analysisPromptText = ref('')
  const analysisInProgress = ref(false)
  const analysisAgentConnected = ref(false)
  const analysisHintVisible = ref(false)
  let analysisHintTimer = null

  const ANALYSIS_POLL_INTERVAL_MS = 10_000
  let analysisPollTimer = null
  let analysisPollInFlight = false

  function clearHintTimer() {
    clearTimeout(analysisHintTimer)
    analysisHintTimer = null
  }

  function stopPolling() {
    if (analysisPollTimer) {
      clearInterval(analysisPollTimer)
      analysisPollTimer = null
    }
    analysisPollInFlight = false
  }

  function resetAnalysisState() {
    analysisInProgress.value = false
    analysisAgentConnected.value = false
    analysisHintVisible.value = false
    clearHintTimer()
    stopPolling()
  }

  function patchFormFromProduct(updated) {
    const ts = updated.tech_stack || {}
    const arch = updated.architecture || {}
    const tc = updated.test_config || {}

    patchProductForm({
      name: updated.name || '',
      description: updated.description || '',
      projectPath: updated.project_path || '',
      targetPlatforms: updated.target_platforms || ['all'],
      techStack: {
        programming_languages: ts.programming_languages || '',
        frontend_frameworks: ts.frontend_frameworks || '',
        backend_frameworks: ts.backend_frameworks || '',
        databases_storage: ts.databases_storage || '',
        infrastructure: ts.infrastructure || '',
      },
      architecture: {
        primary_pattern: arch.primary_pattern || '',
        design_patterns: arch.design_patterns || '',
        api_style: arch.api_style || '',
        architecture_notes: arch.architecture_notes || '',
        coding_conventions: arch.coding_conventions || '',
      },
      coreFeatures: updated.core_features || '',
      brandGuidelines: updated.brand_guidelines || '',
      testConfig: {
        quality_standards: tc.quality_standards || '',
        test_strategy: tc.test_strategy || 'TDD',
        coverage_target: tc.coverage_target || 80,
        testing_frameworks: tc.testing_frameworks || '',
      },
      extractionCustomInstructions: updated.extraction_custom_instructions || '',
    })
  }

  function completeAnalysis(updated) {
    if (updated) {
      patchFormFromProduct(updated)
    }
    clearHintTimer()
    stopPolling()
    analysisInProgress.value = false
    analysisAgentConnected.value = false
  }

  async function stageAnalysis(productForm, productId) {
    if (!productId) {
      console.warn('[useVisionAnalysis] stageAnalysis called but no product ID available.')
      return
    }

    const productName = productForm.name || 'this product'
    const customInstructions = (productForm.extractionCustomInstructions || '').trim()

    if (customInstructions) {
      try {
        await productStore.updateProduct(productId, {
          extraction_custom_instructions: customInstructions,
        })
      } catch (err) {
        console.warn('[useVisionAnalysis] Failed to persist extraction_custom_instructions:', err)
      }
    }

    let prompt =
      `Analyze the vision documents for product "${productName}".\n` +
      `1. Call get_vision_document(product_id="${productId}") and FOLLOW the extraction_instructions embedded in the response.\n` +
      `2. Write the results with update_product_context(product_id="${productId}") — the per-document and consolidated summaries plus the product card fields. It is a merge-write and is SAFE TO CALL IN STAGES: split the work across several calls rather than sending one large one, and set emit_completion=true on your final call to unlock the rest of the setup wizard. Every response reports vision_analysis_complete and missing_for_completion, so you never have to guess whether you are done.`

    if (customInstructions) {
      prompt += `\n\nAdditional extraction guidance from the product owner:\n${customInstructions}`
    }

    promptFallbackText.value = null
    analysisPromptText.value = prompt

    if (copyPromptOnStage) {
      const didCopy = await copyToClipboard(prompt)

      if (didCopy) {
        analysisPromptCopied.value = true
        showToast({ message: 'Discovery prompt copied. Paste into your AI agent to analyze your vision doc.', type: 'success', timeout: 4000 })
        setTimeout(() => { analysisPromptCopied.value = false }, 3000)
      } else {
        promptFallbackText.value = prompt
        showToast({ message: 'Clipboard blocked. Select the prompt below and press Ctrl+C.', type: 'warning', timeout: 5000 })
      }
    }

    analysisInProgress.value = true

    analysisHintVisible.value = false
    clearTimeout(analysisHintTimer)
    analysisHintTimer = setTimeout(() => { analysisHintVisible.value = true }, 60000)

    startPolling(productId)
  }

  function startPolling(productId) {
    stopPolling()
    analysisPollTimer = setInterval(async () => {
      if (analysisPollInFlight) return
      analysisPollInFlight = true
      try {
        const updated = await productStore.fetchProductById(productId)
        if (updated && updated.vision_analysis_complete === true) {
          completeAnalysis(updated)
        }
      } catch (err) {
        console.warn('[useVisionAnalysis] poll fetch failed:', err)
      } finally {
        analysisPollInFlight = false
      }
    }, ANALYSIS_POLL_INTERVAL_MS)
  }

  function onVisionAnalysisStarted(event, currentProductId) {
    const productId = event.detail?.product_id
    if (productId && productId === currentProductId) {
      analysisAgentConnected.value = true
    }
  }

  async function onVisionAnalysisComplete(event, currentProductId) {
    const productId = event.detail?.product_id
    if (!productId || productId !== currentProductId) return

    analysisHintVisible.value = false

    let updated = null
    try {
      updated = await productStore.fetchProductById(productId)
    } finally {
      clearHintTimer()
      analysisInProgress.value = false
      analysisAgentConnected.value = false
    }
    if (updated) completeAnalysis(updated)
  }

  return {
    analysisPromptCopied,
    analysisPromptText,
    promptFallbackText,
    analysisInProgress,
    analysisAgentConnected,
    analysisHintVisible,
    resetAnalysisState,
    stageAnalysis,
    onVisionAnalysisStarted,
    onVisionAnalysisComplete,
  }
}
