/**
 * useProductVisionUpload.js — FE-6006 unit 3b
 *
 * Encapsulates the vision-file upload flow for ProductsView:
 *   - Client-side file validation
 *   - Auto-create product in create mode (silent save to get UUID)
 *   - Per-file upload with progress tracking
 *   - Toast notifications per file
 *   - Refresh existing docs list after upload
 *
 * The composable returns upload state refs plus the handler function.
 * The caller owns `editingProduct` and `autoSavedForAnalysis` — they
 * are passed in so mutations propagate back to the view.
 */
import { ref } from 'vue'
import { useToast } from '@/composables/useToast'
import { useProductStore } from '@/stores/products'
import { validateUploadFiles } from '@/utils/uploadValidation'
import { parseErrorResponse } from '@/utils/errorMessages'
import api from '@/services/api'

export function useProductVisionUpload({ editingProduct, autoSavedForAnalysis }) {
  const { showToast } = useToast()
  const productStore = useProductStore()

  const visionFiles = ref([])
  const uploadingVision = ref(false)
  const uploadProgress = ref(0)
  const visionUploadError = ref(null)
  /**
   * FE-9553c: is retrying SAFE, or would it duplicate work already done?
   *
   * null  -- nothing has failed.
   * true  -- the attempt created nothing server-side, so a retry is clean.
   * false -- something WAS created and could not be bound, so a retry mints a
   *          second one and the operator needs to know that before pressing.
   *
   * Published rather than inferred from the message text: a caller
   * string-matching the copy would silently start offering the wrong remedy the
   * first time anyone reworded it.
   */
  const visionUploadRetrySafe = ref(null)
  const existingVisionDocuments = ref([])

  async function loadExistingVisionDocuments(productId) {
    try {
      const response = await api.visionDocuments.listByProduct(productId)
      existingVisionDocuments.value = response.data || []
    } catch (error) {
      console.error('[useProductVisionUpload] Failed to load vision documents:', error)
      existingVisionDocuments.value = []
    }
  }

  /**
   * Say what actually went wrong when nothing was created.
   *
   * The old single message was "Check your connection and try again", which is
   * wrong for a rate-limited request: a 429 is not a connection
   * problem, and telling someone to check their network when they are being
   * rate-limited sends them to debug the wrong thing.
   */
  function describeCreateFailure(error) {
    const status = error?.response?.status
    if (status === 429) {
      return 'Too many requests just now. Wait a few seconds and try again — nothing was created.'
    }
    if (status === 401 || status === 403) {
      return 'Your session is no longer signed in. Sign in again, then retry — nothing was created.'
    }
    if (status && status >= 500) {
      return 'The server could not create the product just now. Nothing was created, so trying again is safe.'
    }
    if (error?.response) {
      const parsed = parseErrorResponse(error)
      return `${parsed.message || 'The product could not be created'} — nothing was created, so trying again is safe.`
    }
    return 'Could not reach the server. Check your connection and try again — nothing was created.'
  }

  function validateFiles(files) {
    visionFiles.value = files
    const result = validateUploadFiles(files)
    if (result.valid) return true
    const firstFailure = result.invalid[0]
    showToast({
      message: `${firstFailure.file?.name || 'File'}: ${firstFailure.message}`,
      type: 'error',
      timeout: 7000,
    })
    visionFiles.value = []
    return false
  }

  // SEC-0001 Phase 2: client-side pre-check mirrors backend UploadConfig.
  // Backend (api/endpoints/vision_documents.py + upload_guard.py) remains
  // the authoritative security boundary.
  async function uploadVisionFilesOnAttach({ productName, files }) {
    if (!files || files.length === 0) return
    if (!validateFiles(files)) return

    try {
      let productId
      if (editingProduct.value) {
        productId = editingProduct.value.id
      } else {
        // In create mode: silently create the product to get a UUID
        const product = await productStore.createProduct({ name: productName })

        // The product may already EXIST server-side at this point even when we
        // cannot use it: createProduct returns `response.data`, and its call is
        // written `(await api.products?.create(...)) || { data: null }`, so a
        // response carrying no usable body is a normal outcome there rather
        // than an error. Reading `.id` off that used to throw a TypeError,
        // which the catch below swallowed into a generic toast -- leaving a
        // product created and the caller holding nothing, with no way to tell
        // that apart from a validation refusal that created nothing.
        //
        // Named explicitly so callers can distinguish the two, because the
        // remedies differ: nothing was created (retry is clean) versus
        // something WAS created (retry would duplicate it).
        if (!product?.id) {
          const err = new Error(
            'The product was created but the server returned no usable record, so the upload could not be attached to it.',
          )
          err.code = 'PRODUCT_CREATED_BUT_UNBOUND'
          throw err
        }

        editingProduct.value = product
        autoSavedForAnalysis.value = product.id
        productId = product.id
      }

      uploadingVision.value = true
      uploadProgress.value = 0
      visionUploadError.value = null
      visionUploadRetrySafe.value = null

      for (let i = 0; i < files.length; i++) {
        const file = files[i]
        try {
          const formData = new FormData()
          formData.append('product_id', productId)
          formData.append('document_name', file.name.replace(/\.[^/.]+$/, ''))
          formData.append('document_type', 'vision')
          formData.append('vision_file', file)
          formData.append('auto_chunk', 'true')

          const response = await api.visionDocuments.upload(formData)
          uploadProgress.value = ((i + 1) / files.length) * 100

          const chunkCount = response.data?.chunk_count || 0
          const isSummarized = response.data?.is_summarized || false
          const statusParts = []
          if (isSummarized) statusParts.push('analyzed')
          if (chunkCount > 0) statusParts.push(`${chunkCount} chunks`)

          showToast({
            message: `${file.name} uploaded${statusParts.length ? ` (${statusParts.join(', ')})` : ''}`,
            type: 'success',
            timeout: 3000,
          })
        } catch (uploadError) {
          console.error(`[useProductVisionUpload] Failed to upload ${file.name}:`, uploadError)

          // SEC-0001 Phase 2: Surface backend {error_code, message} verbatim
          // (UPLOAD_TOO_LARGE / UPLOAD_TYPE_NOT_ALLOWED / UPLOAD_CONTENT_NOT_TEXT /
          // UPLOAD_FILENAME_INVALID). 409 gets dedicated UX copy.
          let errorMessage
          if (uploadError?.response?.status === 409) {
            errorMessage = `${file.name}: Document already exists. Please rename and try again.`
          } else if (uploadError?.response) {
            const parsed = parseErrorResponse(uploadError)
            errorMessage = `${file.name}: ${parsed.message || 'Upload failed'}`
          } else {
            errorMessage = `Failed to upload ${file.name}`
          }

          visionUploadError.value = errorMessage
          showToast({ message: errorMessage, type: 'error', timeout: 7000 })
        }
      }

      uploadingVision.value = false
      visionFiles.value = []
      await loadExistingVisionDocuments(productId)
    } catch (error) {
      console.error('[useProductVisionUpload] Failed to upload vision files:', error)
      uploadingVision.value = false
      // Published so a caller can render the failure rather than having to
      // infer it from an unset editingProduct -- inferring it is what let the
      // tutorial screen strand the operator in silence.
      const created = error?.code === 'PRODUCT_CREATED_BUT_UNBOUND'
      visionUploadRetrySafe.value = !created
      visionUploadError.value = created
        ? 'A product was created but the file could not be attached to it. Open Products to see it, or try again from there.'
        : describeCreateFailure(error)
      showToast({ message: visionUploadError.value, type: 'error', timeout: 5000 })
    }
  }

  function resetUploadState() {
    visionFiles.value = []
    existingVisionDocuments.value = []
    uploadingVision.value = false
    uploadProgress.value = 0
    visionUploadError.value = null
    visionUploadRetrySafe.value = null
  }

  return {
    visionFiles,
    uploadingVision,
    uploadProgress,
    visionUploadError,
    visionUploadRetrySafe,
    existingVisionDocuments,
    loadExistingVisionDocuments,
    uploadVisionFilesOnAttach,
    resetUploadState,
  }
}
