import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const { showToastMock, apiMock } = vi.hoisted(() => ({
  showToastMock: vi.fn(),
  apiMock: {
    visionDocuments: {
      upload: vi.fn(),
      listByProduct: vi.fn(),
    },
  },
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock('@/services/api', () => ({
  default: apiMock,
}))

vi.mock('@/utils/uploadValidation', () => ({
  validateUploadFiles: (files) => {
    const invalid = files.filter(f => f._invalid)
    return {
      valid: invalid.length === 0,
      invalid: invalid.map(f => ({ file: f, message: 'Invalid file' })),
    }
  },
}))

vi.mock('@/utils/errorMessages', () => ({
  parseErrorResponse: (err) => ({ message: err?.response?.data?.detail || 'Error' }),
}))

import { useProductVisionUpload } from './useProductVisionUpload'

describe('useProductVisionUpload', () => {
  let editingProduct, autoSavedForAnalysis

  beforeEach(() => {
    setActivePinia(createPinia())
    editingProduct = ref(null)
    autoSavedForAnalysis = ref(null)
    showToastMock.mockReset()
    apiMock.visionDocuments.upload.mockReset()
    apiMock.visionDocuments.listByProduct.mockReset()
    apiMock.visionDocuments.listByProduct.mockResolvedValue({ data: [] })
  })

  it('returns expected shape', () => {
    const result = useProductVisionUpload({ editingProduct, autoSavedForAnalysis })
    expect(result).toHaveProperty('uploadVisionFilesOnAttach')
    expect(result).toHaveProperty('uploadingVision')
    expect(result).toHaveProperty('uploadProgress')
    expect(result).toHaveProperty('visionUploadError')
    expect(result).toHaveProperty('existingVisionDocuments')
    expect(result).toHaveProperty('resetUploadState')
  })

  it('does nothing if files array is empty', async () => {
    const { uploadVisionFilesOnAttach, uploadingVision } = useProductVisionUpload({ editingProduct, autoSavedForAnalysis })
    await uploadVisionFilesOnAttach({ productName: 'Test', files: [] })
    expect(uploadingVision.value).toBe(false)
    expect(apiMock.visionDocuments.upload).not.toHaveBeenCalled()
  })

  it('shows toast and aborts when validation fails', async () => {
    const { uploadVisionFilesOnAttach } = useProductVisionUpload({ editingProduct, autoSavedForAnalysis })
    const badFile = new File(['x'], 'bad.exe', { type: 'application/x-exe' })
    badFile._invalid = true
    await uploadVisionFilesOnAttach({ productName: 'Test', files: [badFile] })
    expect(showToastMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
    expect(apiMock.visionDocuments.upload).not.toHaveBeenCalled()
  })

  it('uploads files when editingProduct is set (edit mode)', async () => {
    editingProduct.value = { id: 'prod-123' }
    apiMock.visionDocuments.upload.mockResolvedValue({ data: { chunk_count: 3, is_summarized: true } })
    const { uploadVisionFilesOnAttach, uploadProgress, existingVisionDocuments } = useProductVisionUpload({ editingProduct, autoSavedForAnalysis })
    const file = new File(['content'], 'vision.md', { type: 'text/markdown' })
    await uploadVisionFilesOnAttach({ productName: 'Test', files: [file] })
    expect(apiMock.visionDocuments.upload).toHaveBeenCalledTimes(1)
    expect(uploadProgress.value).toBe(100)
    expect(showToastMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
    expect(apiMock.visionDocuments.listByProduct).toHaveBeenCalledWith('prod-123')
    expect(existingVisionDocuments.value).toEqual([])
  })

  it('handles 409 conflict with dedicated error message', async () => {
    editingProduct.value = { id: 'prod-123' }
    const conflictError = { response: { status: 409 } }
    apiMock.visionDocuments.upload.mockRejectedValue(conflictError)
    const { uploadVisionFilesOnAttach, visionUploadError } = useProductVisionUpload({ editingProduct, autoSavedForAnalysis })
    const file = new File(['x'], 'vision.md', { type: 'text/markdown' })
    await uploadVisionFilesOnAttach({ productName: 'Test', files: [file] })
    expect(visionUploadError.value).toContain('already exists')
    expect(showToastMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
  })

  it('resetUploadState clears all state', () => {
    const { uploadingVision, uploadProgress, visionUploadError, existingVisionDocuments, resetUploadState } = useProductVisionUpload({ editingProduct, autoSavedForAnalysis })
    uploadingVision.value = true
    uploadProgress.value = 50
    visionUploadError.value = 'error'
    existingVisionDocuments.value = [{ id: 'd1' }]
    resetUploadState()
    expect(uploadingVision.value).toBe(false)
    expect(uploadProgress.value).toBe(0)
    expect(visionUploadError.value).toBeNull()
    expect(existingVisionDocuments.value).toEqual([])
  })
})
