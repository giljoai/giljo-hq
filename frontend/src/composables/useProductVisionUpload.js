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
    })
    visionFiles.value = []
    return false
  }

  async function uploadVisionFilesOnAttach({ productName, files }) {
    if (!files || files.length === 0) return
    visionUploadError.value = null
    visionUploadRetrySafe.value = null
    if (!validateFiles(files)) return

    try {
      let productId
      if (editingProduct.value) {
        productId = editingProduct.value.id
      } else {
        const product = await productStore.createProduct({ name: productName })

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
          })
        } catch (uploadError) {
          console.error(`[useProductVisionUpload] Failed to upload ${file.name}:`, uploadError)

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
          visionUploadRetrySafe.value = true
          showToast({ message: errorMessage, type: 'error' })
        }
      }

      uploadingVision.value = false
      visionFiles.value = []
      await loadExistingVisionDocuments(productId)
    } catch (error) {
      console.error('[useProductVisionUpload] Failed to upload vision files:', error)
      uploadingVision.value = false
      const created = error?.code === 'PRODUCT_CREATED_BUT_UNBOUND'
      visionUploadRetrySafe.value = !created
      visionUploadError.value = created
        ? 'A product was created but the file could not be attached to it. Open Products to see it, or try again from there.'
        : describeCreateFailure(error)
      showToast({ message: visionUploadError.value, type: 'error' })
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
