import { ref } from 'vue'
import { useProductStore } from '@/stores/products'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'

/**
 * @param {Function} patchProductForm - completion hook; receives the mapped form data.
 * @param {object}   [options]
 * @param {boolean}  [options.copyPromptOnStage=true] - whether staging an analysis also
 *   writes the prompt to the clipboard. TRUE (the default, and what ProductForm relies
 *   on) keeps the historical behaviour: there, staging is itself an explicit button
 *   press, so the copy is the user's own action. The tutorial's upload screen stages as
 *   a side effect of dropping a file, where a silent clipboard write is exactly what the
 *   operator ruled out — it opts OUT here and owns a visible copy control instead.
 *   Deliberately a per-CONSUMER option, not a per-CALL argument: stageAnalysis's arity is
 *   asserted by TSK-9206's specs, and the policy belongs to the screen, not the call site.
 */
export function useVisionAnalysis(patchProductForm, { copyPromptOnStage = true } = {}) {
  const productStore = useProductStore()
  const { copy: copyToClipboard } = useClipboard()
  const { showToast } = useToast()

  const analysisPromptCopied = ref(false)
  const promptFallbackText = ref(null)
  // The staged prompt, always published so a consumer that opted out of the
  // automatic copy can display it and offer its own copy control.
  const analysisPromptText = ref('')
  const analysisInProgress = ref(false)
  const analysisAgentConnected = ref(false)
  const analysisHintVisible = ref(false)
  let analysisHintTimer = null

  // FE-9166: polling fallback. The 'vision-analysis-complete' window-event chain
  // (backend WS -> systemEventRoutes -> dispatchWindowEvent -> onVisionAnalysisComplete)
  // is lost forever if the tab's WebSocket is disconnected at emit time, leaving
  // the wizard stuck on "Analyzing". This interval polls the product row directly
  // and runs the SAME completion routine so the two paths cannot drift.
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

  // Maps a freshly-fetched product row onto the wizard form. Single source of
  // truth for both the event path and the poll path (FE-9166).
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

  // Shared completion routine — patch the form (when a product came back), then
  // tear down all in-flight timers and clear the two "in progress" flags. Called
  // by BOTH the window-event path (onVisionAnalysisComplete) and the poll path.
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

    // Persist custom instructions BEFORE copying so the agent (which fetches the
    // product via get_vision_document) sees the latest text. Non-blocking on failure —
    // the user's primary action is copying the prompt, not waiting for an API.
    if (customInstructions) {
      try {
        await productStore.updateProduct(productId, {
          extraction_custom_instructions: customInstructions,
        })
      } catch (err) {
        console.warn('[useVisionAnalysis] Failed to persist extraction_custom_instructions:', err)
      }
    }

    // BE-9164: the detailed two-role analysis brief now lives server-side in
    // VISION_EXTRACTION_PROMPT and is returned by get_vision_document as
    // extraction_instructions (single source of truth). This wizard prompt only
    // points the agent at that flow.
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

  // FE-9166: recovery fallback for a lost 'vision-analysis-complete' event.
  // Polls the product row every ANALYSIS_POLL_INTERVAL_MS; when the backend has
  // flipped vision_analysis_complete, runs the shared completion routine (which
  // also clears this interval). Overlapping ticks are skipped while a fetch is
  // in flight; the interval is torn down by completeAnalysis / resetAnalysisState.
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

    // FE-9166: try/finally guarantees the two flags reset once a matching event
    // arrives even if fetchProductById rejects — otherwise the wizard stays
    // stuck on "Analyzing". completeAnalysis handles the happy path (patch +
    // teardown); the finally is the safety net for a failed fetch.
    //
    // FE-9320: the finally used to stopPolling() as well. completeAnalysis is
    // the ONLY thing that advances the wizard (it is what calls patchProductForm),
    // and it can only run with a product in hand — so when the fetch threw or
    // returned null, the advance was skipped AND the poll that would have
    // retried it was torn down in the same breath. That left the upload screen
    // on "Waiting for your agent's analysis…" permanently, with no way forward.
    // The poll now survives a failed fetch and retries every tick; the event
    // already told us the analysis is done, so there IS something to find.
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
